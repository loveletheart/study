import copy
import hashlib
import json
import logging
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, local
from uuid import uuid4

from pydantic import ValidationError
from app.common.database import connect_database
from app.outfits.application.feedback_errors import FeedbackConflictError, FeedbackInvalidError, FeedbackNotFoundError
from app.outfits.domain.quality import check_day, training_text_issues
from app.outfits.infrastructure.schemas import GeneratedDay, GeneratedResponse

logger = logging.getLogger(__name__)
ISSUES = {'clothing_category', 'weather_logic', 'explanation_mismatch', 'preference_mismatch', 'repetition', 'other'}
STATUSES = {'reported', 'draft', 'approved', 'rejected'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


def now():
    return datetime.now(timezone.utc).isoformat()


class SQLiteFeedbackStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._initialized = False
        self._lock = Lock()

    def _ready(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with closing(connect_database(self.path)) as connection, connection:
                connection.execute('''CREATE TABLE IF NOT EXISTS outfit_generations (
                    id TEXT PRIMARY KEY, source_key TEXT UNIQUE, created_at TEXT NOT NULL,
                    source_kind TEXT NOT NULL, exact_prompt INTEGER NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
                    request_json TEXT NOT NULL, raw_response TEXT NOT NULL, schema_valid INTEGER NOT NULL,
                    error_type TEXT)''')
                connection.execute('''CREATE TABLE IF NOT EXISTS outfit_feedback (
                    id TEXT PRIMARY KEY, generation_id TEXT NOT NULL REFERENCES outfit_generations(id),
                    owner_id TEXT NOT NULL, date TEXT NOT NULL, issues_json TEXT NOT NULL, note TEXT NOT NULL,
                    corrected_json TEXT, status TEXT NOT NULL, revision INTEGER NOT NULL,
                    reviewer_kind TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reviewed_at TEXT,
                    UNIQUE(owner_id, generation_id, date))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS outfit_feedback_history (
                    id INTEGER PRIMARY KEY, feedback_id TEXT NOT NULL REFERENCES outfit_feedback(id),
                    revision INTEGER NOT NULL, action TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL)''')
                connection.execute('CREATE INDEX IF NOT EXISTS ix_outfit_feedback_owner ON outfit_feedback(owner_id, updated_at)')
            self._initialized = True

    def capture(self, model, provider, messages, schema, raw_response, *, source_kind='app_request', exact_prompt=True, source_key=None, error_type=None, prompt_version=None):
        self._ready()
        messages = copy.deepcopy(messages)
        if [message.get('role') for message in messages] != ['system', 'user']:
            raise FeedbackInvalidError('날씨 추천의 원본 메시지만 기록할 수 있습니다.')
        payload = json.loads(messages[1]['content'])
        if not isinstance(payload.get('weather_days'), list) or not 1 <= len(payload['weather_days']) <= 7:
            raise FeedbackInvalidError('기록할 날씨 입력이 올바르지 않습니다.')
        if not isinstance(raw_response, str) or len(raw_response.encode('utf-8')) > 1_048_576:
            raise FeedbackInvalidError('원본 답변의 크기를 확인해 주세요.')
        from app.outfits.infrastructure.prompts import PROMPT_VERSION, PERSONALIZATION_VERSION
        version = prompt_version or (PERSONALIZATION_VERSION if payload.get('preferences') else PROMPT_VERSION)
        valid = False
        try:
            generated = GeneratedResponse.model_validate_json(raw_response, strict=True)
            valid = [day.date.isoformat() for day in generated.days] == [day['date'] for day in payload['weather_days']]
        except (ValidationError, ValueError):
            pass
        identifier = str(uuid4())
        with closing(connect_database(self.path)) as connection, connection:
            if source_key:
                existing = connection.execute('SELECT id FROM outfit_generations WHERE source_key=?', (source_key,)).fetchone()
                if existing:
                    return existing['id']
            connection.execute('INSERT INTO outfit_generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                               (identifier, source_key, now(), source_kind, int(exact_prompt), provider, model, version,
                                encoded({'messages': messages, 'schema': schema}), raw_response, int(valid), error_type))
        return identifier

    def generation(self, identifier):
        self._ready()
        with closing(connect_database(self.path)) as connection:
            row = connection.execute('SELECT * FROM outfit_generations WHERE id=?', (str(identifier),)).fetchone()
        if row is None:
            raise FeedbackNotFoundError()
        return dict(row)

    def generations(self, *, source_kind=None):
        self._ready()
        with closing(connect_database(self.path)) as connection:
            rows = connection.execute('SELECT * FROM outfit_generations WHERE (? IS NULL OR source_kind=?) ORDER BY created_at, id', (source_kind, source_kind)).fetchall()
        return [dict(row) for row in rows]

    def _context(self, generation, date):
        request = json.loads(generation['request_json'])
        payload = json.loads(request['messages'][1]['content'])
        weather = next((day for day in payload['weather_days'] if day['date'] == date), None)
        if weather is None:
            raise FeedbackInvalidError('원본 답변에 포함된 날짜만 수정할 수 있습니다.')
        original = None
        try:
            days = json.loads(generation['raw_response']).get('days', [])
            original = next((day for day in days if isinstance(day, dict) and day.get('date') == date), None)
        except (ValueError, AttributeError, TypeError):
            pass
        return request, payload, weather, original

    def _correction(self, corrected, selected_date):
        if corrected is None:
            return None
        try:
            result = GeneratedDay.model_validate_json(encoded(corrected), strict=True).model_dump(mode='json')
        except (ValidationError, ValueError) as error:
            raise FeedbackInvalidError('수정안의 의류 구성과 설명 형식을 확인해 주세요.') from error
        if result['date'] != selected_date:
            raise FeedbackInvalidError('수정안의 날짜는 원본 날짜와 같아야 합니다.')
        return result

    def _validate_fields(self, issues, note):
        if not issues or len(issues) > 6 or any(issue not in ISSUES for issue in issues):
            raise FeedbackInvalidError('오류 종류를 선택해 주세요.')
        if len(note) > 2000:
            raise FeedbackInvalidError('메모는 2,000자 이하로 작성해 주세요.')

    def create(self, owner, generation_id, selected_date, issues, note='', corrected=None):
        self._validate_fields(issues, note)
        generation = self.generation(generation_id)
        self._context(generation, selected_date)
        corrected = self._correction(corrected, selected_date)
        identifier, timestamp = str(uuid4()), now()
        with closing(connect_database(self.path)) as connection, connection:
            existing = connection.execute('SELECT id FROM outfit_feedback WHERE owner_id=? AND generation_id=? AND date=?', (str(owner), str(generation_id), selected_date)).fetchone()
            if existing:
                raise FeedbackConflictError('이미 등록한 수정안이 있습니다. 내 수정안에서 계속 편집해 주세요.')
            connection.execute('INSERT INTO outfit_feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                               (identifier, str(generation_id), str(owner), selected_date, encoded(list(dict.fromkeys(issues))), note,
                                encoded(corrected) if corrected else None, 'draft' if corrected else 'reported', 1, None, timestamp, timestamp, None))
            self._history(connection, identifier, 'created')
        return self.get(owner, identifier)

    def _owned(self, connection, owner, identifier):
        row = connection.execute('SELECT * FROM outfit_feedback WHERE id=? AND owner_id=?', (str(identifier), str(owner))).fetchone()
        if row is None:
            raise FeedbackNotFoundError()
        return dict(row)

    def _history(self, connection, identifier, action):
        snapshot = dict(connection.execute('SELECT * FROM outfit_feedback WHERE id=?', (identifier,)).fetchone())
        connection.execute('INSERT INTO outfit_feedback_history(feedback_id,revision,action,snapshot_json,created_at) VALUES(?,?,?,?,?)', (identifier, snapshot['revision'], action, encoded(snapshot), now()))

    def _view(self, row):
        generation = self.generation(row['generation_id'])
        request, payload, weather, original = self._context(generation, row['date'])
        corrected = json.loads(row['corrected_json']) if row['corrected_json'] else None
        checks = check_day(corrected, weather, payload.get('preferences')) if corrected else {'errors': [], 'warnings': []}
        return {key: row[key] for key in ('id', 'generation_id', 'date', 'note', 'status', 'revision', 'created_at', 'updated_at', 'reviewed_at', 'reviewer_kind')} | {
            'issues': json.loads(row['issues_json']), 'original_day': original, 'corrected_day': corrected,
            'weather': weather, 'preferences': payload.get('preferences'),
            'engine': {key: generation[key] for key in ('provider', 'model', 'prompt_version')}, 'checks': checks,
        }

    def get(self, owner, identifier):
        self._ready()
        with closing(connect_database(self.path)) as connection:
            row = self._owned(connection, owner, identifier)
        return self._view(row)

    def list(self, owner, *, status=None, limit=50, offset=0):
        self._ready()
        if status is not None and status not in STATUSES:
            raise FeedbackInvalidError()
        with closing(connect_database(self.path)) as connection:
            values = (str(owner), status, status)
            total = connection.execute('SELECT COUNT(*) FROM outfit_feedback WHERE owner_id=? AND (? IS NULL OR status=?)', values).fetchone()[0]
            rows = connection.execute('SELECT * FROM outfit_feedback WHERE owner_id=? AND (? IS NULL OR status=?) ORDER BY updated_at DESC,id LIMIT ? OFFSET ?', (*values, min(max(limit, 1), 100), max(offset, 0))).fetchall()
        return {'items': [self._view(dict(row)) for row in rows], 'total': total}

    def update(self, owner, identifier, revision, issues, note, corrected):
        self._ready()
        self._validate_fields(issues, note)
        with closing(connect_database(self.path)) as connection, connection:
            row = self._owned(connection, owner, identifier)
            if row['revision'] != revision:
                raise FeedbackConflictError()
            corrected = self._correction(corrected, row['date'])
            changed = connection.execute('UPDATE outfit_feedback SET issues_json=?,note=?,corrected_json=?,status=?,revision=revision+1,reviewer_kind=NULL,reviewed_at=NULL,updated_at=? WHERE id=? AND owner_id=? AND revision=?',
                                         (encoded(list(dict.fromkeys(issues))), note, encoded(corrected) if corrected else None, 'draft' if corrected else 'reported', now(), str(identifier), str(owner), revision)).rowcount
            if changed != 1:
                raise FeedbackConflictError()
            self._history(connection, str(identifier), 'edited')
        return self.get(owner, identifier)

    def review(self, owner, identifier, revision, *, approved, confirmed=False, reviewer_kind='user'):
        self._ready()
        view = self.get(owner, identifier)
        if view['revision'] != revision:
            raise FeedbackConflictError()
        if approved:
            if not confirmed or view['corrected_day'] is None:
                raise FeedbackInvalidError('수정 정답을 확인한 뒤 검수를 확정해 주세요.')
            if view['checks']['errors']:
                raise FeedbackInvalidError(' '.join(issue['message'] for issue in view['checks']['errors'][:3]))
        if reviewer_kind not in {'user', 'assistant'}:
            raise FeedbackInvalidError()
        with closing(connect_database(self.path)) as connection, connection:
            self._owned(connection, owner, identifier)
            changed = connection.execute('UPDATE outfit_feedback SET status=?,revision=revision+1,reviewer_kind=?,reviewed_at=?,updated_at=? WHERE id=? AND owner_id=? AND revision=?',
                                         ('approved' if approved else 'rejected', reviewer_kind, now(), now(), str(identifier), str(owner), revision)).rowcount
            if changed != 1:
                raise FeedbackConflictError()
            self._history(connection, str(identifier), 'approved' if approved else 'rejected')
        return self.get(owner, identifier)

    def export_records(self, owner, *, include_assistant=False):
        self._ready()
        with closing(connect_database(self.path)) as connection:
            rows = connection.execute("SELECT * FROM outfit_feedback WHERE owner_id=? AND status='approved' ORDER BY created_at,id", (str(owner),)).fetchall()
        records = []
        for row in rows:
            row = dict(row)
            if row['reviewer_kind'] != 'user' and not include_assistant:
                continue
            view = self._view(row)
            if view['checks']['errors'] or view['corrected_day'] is None:
                continue
            generation = self.generation(row['generation_id'])
            request, payload, weather, original = self._context(generation, row['date'])
            user = {key: copy.deepcopy(payload[key]) for key in ('timezone', 'units', 'unprovided_weather', 'look_examples', 'preferences', 'personal_requirements') if key in payload}
            schema = GeneratedResponse.model_json_schema()
            schema['properties']['days'].update(minItems=1, maxItems=1)
            schema['$defs']['GeneratedDay']['properties']['date']['enum'] = [row['date']]
            user.update(weather_days=[weather], output_schema=schema)
            messages = [copy.deepcopy(request['messages'][0]), {'role': 'user', 'content': encoded(user)}, {'role': 'assistant', 'content': encoded({'days': [view['corrected_day']]})}]
            weather_key = {key: value for key, value in weather.items() if key != 'date'}
            group = hashlib.sha256(json.dumps([weather_key], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            record = {'id': row['id'], 'scenario_group': 'reviewed-weather-' + group, 'review_status': 'approved', 'reviewer': row['reviewer_kind'], 'reviewer_kind': row['reviewer_kind'], 'reviewed_at': row['reviewed_at'], 'source': generation['source_kind'], 'generation_id': generation['id'], 'source_exact_prompt': bool(generation['exact_prompt']), 'prompt_transform': 'single_day_projection; original immutable snapshot retained locally', 'engine': view['engine'], 'messages': messages}
            if original and not training_text_issues(original):
                record['rejected'] = encoded({'days': [original]})
            records.append(record)
        return records


class RecordingChatClient:
    """동기 모델 호출의 원본을 기록하고 생성 식별자를 인스턴스·스레드별로 격리한다."""

    def __init__(self, client, store, provider, *, source_kind='app_request'):
        """장기 실행 스레드의 컨텍스트에 누적되지 않는 기록 상태를 준비한다."""
        self.client, self.store, self.provider = client, store, provider
        self.source_kind = source_kind
        self._local = local()

    @property
    def last_generation_id(self):
        """현재 스레드에서 이 클라이언트가 마지막으로 저장한 생성 식별자를 반환한다."""
        return getattr(self._local, 'generation_id', None)

    def chat(self, model, messages, schema):
        """이전 기록을 비우고 성공 응답이나 전송 오류의 원본을 저장한다."""
        self._local.generation_id = None
        try:
            result = self.client.chat(model, messages, schema)
        except Exception as error:
            self._record(model, messages, schema, '', type(error).__name__)
            raise
        self._record(model, messages, schema, result)
        return result

    def _record(self, model, messages, schema, result, error_type=None):
        """원본 저장에 성공한 경우에만 현재 스레드의 생성 식별자를 갱신한다."""
        try:
            self._local.generation_id = self.store.capture(model, self.provider, messages, schema, result, source_kind=self.source_kind, error_type=error_type)
        except Exception as error:
            logger.warning('추천 검수용 원본 기록 저장 실패: cause=%s', type(error).__name__)
