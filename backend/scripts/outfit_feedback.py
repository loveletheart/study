import argparse
import hashlib
import json
import sys
from contextlib import closing
from dataclasses import fields
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.common.config import get_settings
from app.common.database import connect_database
from app.outfits.domain.models import OutfitWeather
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore
from app.outfits.infrastructure.prompts import PROMPT_VERSION, build_messages
from app.outfits.infrastructure.schemas import GeneratedResponse


def import_cache(store):
    allowed = {field.name for field in fields(OutfitWeather)}
    with closing(connect_database(store.path)) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='outfit_result_cache'").fetchone()
        rows = connection.execute('SELECT rowid,payload FROM outfit_result_cache WHERE payload IS NOT NULL').fetchall() if exists else []
    imported, skipped = 0, 0
    for row in rows:
        payload = json.loads(row['payload'])
        engine = payload.get('engine', {})
        if engine.get('generation_id') or engine.get('prompt_version') != PROMPT_VERSION:
            skipped += 1
            continue
        days = payload.get('daily') or [payload.get('recommendation')]
        if not days or any(not day for day in days):
            skipped += 1
            continue
        weather = []
        answers = []
        for day in days:
            values = {key: value for key, value in day['weather'].items() if key in allowed}
            values['date'] = date.fromisoformat(values['date'])
            weather.append(OutfitWeather(**values))
            answers.append({key: day[key] for key in ('date', 'best', 'worst', 'reasons', 'avoid_reasons', 'precautions')})
        schema = GeneratedResponse.model_json_schema()
        schema['properties']['days'].update(minItems=len(days), maxItems=len(days))
        schema['$defs']['GeneratedDay']['properties']['date']['enum'] = [day['date'] for day in answers]
        raw = json.dumps({'days': answers}, ensure_ascii=False)
        key = 'cache:' + hashlib.sha256(bytes(row['payload']) if isinstance(row['payload'], bytes) else row['payload'].encode()).hexdigest()
        identifier = store.capture(engine['model'], engine['provider'], build_messages(tuple(weather), schema), schema, raw,
                                   source_kind='app_cache_import', exact_prompt=False, source_key=key, prompt_version=engine['prompt_version'])
        payload['engine']['generation_id'] = identifier
        with closing(connect_database(store.path)) as connection, connection:
            count = connection.execute('UPDATE outfit_result_cache SET payload=? WHERE rowid=? AND payload=?',
                                       (json.dumps(payload, ensure_ascii=False).encode(), row['rowid'], row['payload'])).rowcount
        imported += count
    return {'imported': imported, 'skipped': skipped, 'source': 'cached served output; historical prompt reconstructed, not exact wire input'}


def main():
    parser = argparse.ArgumentParser(description='추천 원본·수정 정답의 로컬 검수와 내보내기')
    parser.add_argument('--database', type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('import-cache')
    commands.add_parser('candidates')
    correction = commands.add_parser('import-corrections')
    correction.add_argument('--file', type=Path, required=True)
    correction.add_argument('--approve-assistant-reviewed', action='store_true')
    export = commands.add_parser('export')
    export.add_argument('--owner', default='operator:local')
    export.add_argument('--include-assistant-reviewed', action='store_true')
    export.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    store = SQLiteFeedbackStore(args.database or get_settings().database_path)
    if args.command == 'import-cache':
        print(json.dumps(import_cache(store), ensure_ascii=False))
    elif args.command == 'candidates':
        for row in store.generations():
            payload = json.loads(json.loads(row['request_json'])['messages'][1]['content'])
            print(json.dumps({'id': row['id'], 'source': row['source_kind'], 'model': row['model'], 'schema_valid': bool(row['schema_valid']), 'dates': [day['date'] for day in payload['weather_days']]}, ensure_ascii=False))
    elif args.command == 'import-corrections':
        count = 0
        for line in args.file.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get('reviewer_kind') != 'assistant' or entry.get('review_method') != 'manual_text_review':
                raise SystemExit('Operator imports must explicitly identify assistant manual review, not human approval')
            row = store.create('operator:local', entry['generation_id'], entry['date'], entry['issues'], entry.get('note', ''), entry['corrected_day'])
            if args.approve_assistant_reviewed:
                store.review('operator:local', row['id'], row['revision'], approved=True, confirmed=True, reviewer_kind='assistant')
            count += 1
        print(json.dumps({'imported': count, 'assistant_review_approved': args.approve_assistant_reviewed, 'human_approved': False}))
    else:
        records = store.export_records(args.owner, include_assistant=args.include_assistant_reviewed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as destination:
            destination.write(''.join(json.dumps(record, ensure_ascii=False) + '\n' for record in records))
        print(json.dumps({'records': len(records), 'output': str(args.output), 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
