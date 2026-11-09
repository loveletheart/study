"""빌드된 화면의 제공 경로와 기존 API의 공존을 확인한다. 외부 요청은 하지 않는다."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from main import app, frontend_dist


@unittest.skipUnless((frontend_dist / "index.html").is_file(), "프론트엔드 빌드 후 실행")
class FrontendServingTests(unittest.TestCase):
    def setUp(self):
        # 수명 주기를 시작하지 않아 운영 DB와 백그라운드 모델 생성에 접근하지 않는다.
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_built_frontend_and_its_assets_are_served(self):
        response = self.client.get("/app/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn('lang="ko"', response.text)
        scripts = re.findall(r'src="(/app/assets/[^\"]+\.js)"', response.text)
        self.assertTrue(scripts)
        script_response = self.client.get(scripts[0])
        self.assertEqual(script_response.status_code, 200)
        self.assertEqual(script_response.headers["content-type"].split(";")[0], "text/javascript")
        self.assertEqual(self.client.get("/app/favicon.svg").status_code, 200)

    def test_existing_root_health_and_api_schema_are_preserved(self):
        self.assertEqual(self.client.get("/").json()["data"], {"message": "Hello FastAPI"})
        self.assertEqual(self.client.get("/health").json()["data"], {"status": "ok"})
        self.assertIn("/api/v1/outfits/regions/{location_id}/today", self.client.get("/openapi.json").json()["paths"])

    def test_static_mount_does_not_expose_project_files(self):
        for path in ("/app/.env", "/app/package.json", "/app/%2e%2e/.env", "/app/%2e%2e/study.db"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


@unittest.skipUnless((frontend_dist / "index.html").is_file(), "프론트엔드 빌드 후 실행")
class FrontendMimeTests(unittest.TestCase):
    def test_plain_text_javascript_registration_is_overridden_on_startup(self):
        """OS의 잘못된 .js 등록이 있어도 브라우저가 모듈을 실행할 수 있는 형식을 제공한다."""
        result = subprocess.run(
            [sys.executable, "-c", """
import mimetypes
from starlette.responses import FileResponse

mimetypes.add_type('text/plain', '.js')
assert FileResponse('bundle.js').headers['content-type'].startswith('text/plain')
from main import app, frontend_dist

assert any(getattr(route, 'path', None) == '/app' for route in app.routes)
scripts = list((frontend_dist / 'assets').glob('*.js'))
assert scripts, '빌드된 JavaScript 파일이 필요합니다.'
for script in scripts:
    content_type = FileResponse(script).headers['content-type'].split(';')[0]
    assert content_type == 'text/javascript', content_type
"""],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
