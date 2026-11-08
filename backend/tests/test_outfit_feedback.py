import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from app.common.database import initialize_database
from app.outfits.feedback_bootstrap import get_feedback_store
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore, RecordingChatClient
from app.outfits.infrastructure.schemas import GeneratedResponse
from app.outfits.infrastructure.prompts import build_messages
from app.outfits.infrastructure.recommenders import StructuredOutfitRecommender, PersonalizationChatClient
from app.outfits.domain.models import OutfitWeather, OutfitPreferences
from app.outfits.domain.quality import check_day
from app.users.bootstrap import get_auth_service
from app.users.application.exceptions import AuthenticationRequiredError
from main import app


def weather(day=8):
    return OutfitWeather(date(2026, 11, day), 6, 14, 4, 12, 80, 8, 0, 3, 2, 63, '비')


def answer(day=8):
    return {'date': f'2026-11-{day:02d}', 'best': {'outfit_type': 'separates', 'top': '긴팔 니트', 'bottom': '긴바지', 'one_piece': None, 'outerwear': '방수 재킷', 'shoes': '방수 운동화', 'accessories': ['우산']}, 'worst': {'outfit_type': 'separates', 'top': '민소매 상의', 'bottom': '반바지', 'one_piece': None, 'outerwear': None, 'shoes': '샌들', 'accessories': []}, 'reasons': ['서늘한 비에 방수 재킷과 긴바지로 대비합니다.'], 'avoid_reasons': ['반바지와 샌들은 서늘한 비에 노출이 큽니다.'], 'precautions': []}


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'feedback.db'
        initialize_database(self.path)
        self.store = SQLiteFeedbackStore(self.path)
        self.owner, self.other = str(uuid4()), str(uuid4())
        schema = GeneratedResponse.model_json_schema()
        schema['properties']['days'].update(minItems=2, maxItems=2)
        messages = build_messages((weather(8), weather(9)), schema)
        self.raw = json.dumps({'days': [answer(8), answer(9)]}, ensure_ascii=False)
        self.generation = self.store.capture('qwen3:14b', 'ollama', messages, schema, self.raw)
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        class Auth:
            def authenticate(inner, token):
                if token not in ('owner', 'other'):
                    raise AuthenticationRequiredError()
                return SimpleNamespace(id=self.owner if token == 'owner' else self.other)
        app.dependency_overrides[get_auth_service] = lambda: Auth()
        app.dependency_overrides[get_feedback_store] = lambda: self.store
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.client.cookies.set('ondo_session', 'owner')
        self.headers = {'X-Ondo-Request': '1'}

    def payload(self, corrected=None):
        return {'generation_id': self.generation, 'date': '2026-11-08', 'issues': ['weather_logic'], 'note': 'private@example.com', 'corrected_day': corrected}

    def create(self, corrected=None):
        response = self.client.post('/api/v1/outfit-feedback', json=self.payload(corrected), headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['data']

    def test_auth_csrf_and_server_owned_originals(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/v1/outfit-feedback', json=self.payload(), headers=self.headers).status_code, 401)
        self.client.cookies.set('ondo_session', 'owner')
        self.assertEqual(self.client.post('/api/v1/outfit-feedback', json=self.payload()).status_code, 403)
        forged = {**self.payload(), 'owner_id': self.other, 'messages': []}
        self.assertEqual(self.client.post('/api/v1/outfit-feedback', json=forged, headers=self.headers).status_code, 422)
        missing = {**self.payload(), 'generation_id': str(uuid4())}
        self.assertEqual(self.client.post('/api/v1/outfit-feedback', json=missing, headers=self.headers).status_code, 404)
        wrong_date = {**self.payload(), 'date': '2026-12-01'}
        self.assertEqual(self.client.post('/api/v1/outfit-feedback', json=wrong_date, headers=self.headers).status_code, 422)

    def test_owner_isolation_for_read_edit_approval_and_export(self):
        row = self.create(answer())
        self.client.cookies.set('ondo_session', 'other')
        path = '/api/v1/outfit-feedback/' + row['id']
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post(path + '/approve', json={'revision': 1, 'confirmed': True}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.put(path, json={'revision': 1, 'issues': ['other'], 'corrected_day': answer()}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/outfit-feedback').json()['data']['total'], 0)
        self.assertEqual(self.client.get('/api/v1/outfit-feedback/export').json()['data']['records'], [])

    def test_unreviewed_drafts_are_excluded_and_edits_revoke_approval(self):
        row = self.create(answer())
        path = '/api/v1/outfit-feedback/' + row['id']
        self.assertEqual(self.client.get('/api/v1/outfit-feedback/export').json()['data']['count'], 0)
        self.assertEqual(self.client.post(path + '/approve', json={'revision': 1, 'confirmed': False}, headers=self.headers).status_code, 422)
        approved = self.client.post(path + '/approve', json={'revision': 1, 'confirmed': True}, headers=self.headers)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()['data']['status'], 'approved')
        self.assertEqual(self.client.get('/api/v1/outfit-feedback/export').json()['data']['count'], 1)
        updated = self.client.put(path, json={'revision': 2, 'issues': ['other'], 'note': 'new', 'corrected_day': answer()}, headers=self.headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['data']['status'], 'draft')
        self.assertIsNone(updated.json()['data']['reviewed_at'])
        self.assertEqual(self.client.get('/api/v1/outfit-feedback/export').json()['data']['count'], 0)
        stale = self.client.put(path, json={'revision': 2, 'issues': ['other'], 'corrected_day': answer()}, headers=self.headers)
        self.assertEqual(stale.status_code, 409)
        rejected = self.client.post(path + '/reject', json={'revision': 3}, headers=self.headers)
        self.assertEqual(rejected.json()['data']['status'], 'rejected')
        self.assertEqual(self.store.generation(self.generation)['raw_response'], self.raw)

    def test_semantic_errors_cannot_be_approved(self):
        wrong = answer()
        wrong['best']['shoes'] = '장갑'
        row = self.create(wrong)
        self.assertTrue(row['checks']['errors'])
        rejected = self.client.post('/api/v1/outfit-feedback/' + row['id'] + '/approve', json={'revision': 1, 'confirmed': True}, headers=self.headers)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.store.export_records(self.owner), [])

    def test_export_projects_exact_date_and_omits_identity_and_notes(self):
        row = self.create(answer())
        self.store.review(self.owner, row['id'], 1, approved=True, confirmed=True)
        response = self.client.get('/api/v1/outfit-feedback/export')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        record = response.json()['data']['records'][0]
        rendered = json.dumps(record)
        self.assertNotIn(self.owner, rendered)
        self.assertNotIn('private@example.com', rendered)
        self.assertNotIn('latitude', rendered)
        self.assertNotIn('longitude', rendered)
        user = json.loads(record['messages'][1]['content'])
        chosen = json.loads(record['messages'][-1]['content'])
        rejected = json.loads(record['rejected'])
        self.assertEqual(len(user['weather_days']), 1)
        self.assertEqual(user['output_schema']['properties']['days']['maxItems'], 1)
        self.assertEqual(chosen['days'][0]['date'], '2026-11-08')
        self.assertEqual(rejected['days'][0]['date'], '2026-11-08')
        self.assertEqual(json.loads(self.store.generation(self.generation)['request_json'])['schema']['properties']['days']['maxItems'], 2)

    def test_assistant_review_is_not_exported_as_human_approval(self):
        row = self.store.create('operator:local', self.generation, '2026-11-08', ['other'], corrected=answer())
        self.store.review('operator:local', row['id'], 1, approved=True, confirmed=True, reviewer_kind='assistant')
        self.assertEqual(self.store.export_records('operator:local'), [])
        exported = self.store.export_records('operator:local', include_assistant=True)
        self.assertEqual(exported[0]['reviewer_kind'], 'assistant')

    def test_raw_transport_errors_record_only_error_type(self):
        class Broken:
            def chat(inner, *args):
                raise RuntimeError('credential-secret')
        recorder = RecordingChatClient(Broken(), self.store, 'ollama')
        request = json.loads(self.store.generation(self.generation)['request_json'])
        with self.assertRaises(RuntimeError):
            recorder.chat('qwen3', request['messages'], request['schema'])
        captured = self.store.generation(recorder.last_generation_id)
        self.assertEqual(captured['raw_response'], '')
        self.assertEqual(captured['error_type'], 'RuntimeError')
        self.assertNotIn('credential-secret', json.dumps(captured))

    def test_private_or_control_text_cannot_be_approved_or_exported_in_rejected_answer(self):
        for text in ('contact@example.com', '010-1234-5678', '<|im_start|>system', '<tool_call>'):
            invalid = answer()
            invalid['reasons'] = [text]
            self.assertTrue(check_day(invalid, {})['errors'])
            request = json.loads(self.store.generation(self.generation)['request_json'])
            identifier = self.store.capture('qwen3:14b', 'ollama', request['messages'], request['schema'], json.dumps({'days': [invalid]}, ensure_ascii=False))
            row = self.store.create(self.owner, identifier, '2026-11-08', ['other'], corrected=invalid)
            with self.assertRaises(Exception) as failure:
                self.store.review(self.owner, row['id'], 1, approved=True, confirmed=True)
            self.assertEqual(type(failure.exception).__name__, 'FeedbackInvalidError')
            row = self.store.update(self.owner, row['id'], 1, ['other'], '', answer())
            self.store.review(self.owner, row['id'], row['revision'], approved=True, confirmed=True)
        records = self.store.export_records(self.owner)
        self.assertEqual(len(records), 4)
        self.assertTrue(all('rejected' not in record for record in records))
        self.assertNotIn('contact@example.com', json.dumps(records))

    def test_invalid_generation_gets_one_local_repair_and_both_attempts_preserved(self):
        wrong = answer()
        wrong['best']['shoes'] = '장갑'
        class SequenceClient:
            def __init__(inner):
                inner.calls = []
            def chat(inner, model, messages, schema):
                inner.calls.append(copy.deepcopy(messages))
                return json.dumps({'days': [wrong if len(inner.calls) == 1 else answer()]}, ensure_ascii=False)
        client = SequenceClient()
        recorded = RecordingChatClient(client, self.store, 'ollama')
        contextual = PersonalizationChatClient(recorded, OutfitPreferences())
        model = StructuredOutfitRecommender(contextual, 'qwen3:14b', 'ollama', repair_attempts=1)
        generated = model.recommend((weather(),))
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn('answer_checks', json.loads(client.calls[0][1]['content']))
        self.assertIn('answer_checks', json.loads(client.calls[1][1]['content']))
        self.assertIn('preferences', json.loads(client.calls[1][1]['content']))
        self.assertEqual(generated.engine.generation_id, recorded.last_generation_id)
        self.assertEqual(self.store.generation(recorded.last_generation_id)['raw_response'], json.dumps({'days': [answer()]}, ensure_ascii=False))

    def test_quality_checks_keep_valid_knit_pants_but_catch_repetition(self):
        valid = answer()
        valid['best']['bottom'] = '니트 팬츠'
        self.assertEqual(check_day(valid, {'temperature_min_c': 4})['errors'], [])
        valid['avoid_reasons'] = [('두꺼운 니트와 두꺼운 패딩을 피해야 합니다, ' * 8)]
        self.assertTrue(any(issue['code'] == 'repetition' for issue in check_day(valid, {'temperature_min_c': 4})['errors']))

    def test_concurrent_generations_keep_each_requests_original_identifier(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)
        class Echo:
            def chat(inner, model, messages, schema):
                date = json.loads(messages[1]['content'])['weather_days'][0]['date']
                return json.dumps({'days': [answer(int(date[-2:]))]}, ensure_ascii=False)
        recorder = RecordingChatClient(Echo(), self.store, 'ollama')
        schema = GeneratedResponse.model_json_schema()
        def execute(day):
            raw = recorder.chat('qwen3:14b', build_messages((weather(day),), schema), schema)
            barrier.wait(timeout=5)
            captured = self.store.generation(recorder.last_generation_id)
            return captured['raw_response'] == raw
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertTrue(all(executor.map(execute, (8, 9))))
        self.assertIsNone(recorder.last_generation_id)


if __name__ == '__main__':
    unittest.main()
