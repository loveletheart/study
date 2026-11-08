"""빌드된 화면의 제공 경로와 기존 API의 공존을 확인한다. 외부 요청은 하지 않는다."""

import re
import unittest

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
        self.assertEqual(self.client.get(scripts[0]).status_code, 200)
        self.assertEqual(self.client.get("/app/favicon.svg").status_code, 200)

    def test_existing_root_health_and_api_schema_are_preserved(self):
        self.assertEqual(self.client.get("/").json()["data"], {"message": "Hello FastAPI"})
        self.assertEqual(self.client.get("/health").json()["data"], {"status": "ok"})
        self.assertIn("/api/v1/outfits/regions/{location_id}/today", self.client.get("/openapi.json").json()["paths"])

    def test_static_mount_does_not_expose_project_files(self):
        for path in ("/app/.env", "/app/package.json", "/app/%2e%2e/.env", "/app/%2e%2e/study.db"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
