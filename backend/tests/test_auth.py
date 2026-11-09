"""실제 임시 SQLite와 쿠키로 인증·프로필·권한을 검증한다. 외부 API는 사용하지 않는다."""

import hashlib
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.common.database import initialize_database, connect_database
from app.users.application.services import AuthService, UserService
from app.users.application.dto import CreateUserCommand
from app.users.bootstrap import get_auth_service, get_user_service
from app.users.infrastructure.repositories import SQLiteAuthRepository
from app.users.infrastructure.security import ScryptPasswordSecurity
from app.users.infrastructure.unit_of_work import SQLiteUserUnitOfWork
from app.weather.domain.models import Location
from app.weather.infrastructure.location_catalog import SQLiteLocationCatalog
from app.outfits.domain.models import OutfitPreferences, ClothingPreference, AvoidItem
from app.outfits.infrastructure.prompts import _personal_requirements
from app.outfits.infrastructure.cache import SQLitePersonalizedOutfitCache
from main import app


PASSWORD = " test-password-123 "
HEADERS = {"X-Ondo-Request": "1"}


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "auth.db"
        initialize_database(self.path)
        self.now = 1900000000.0
        self.store = SQLiteAuthRepository(self.path)
        self.locations = SQLiteLocationCatalog(self.path)
        self.locations.save((Location(1, "서울", 37.5, 127, "KR"),))
        self.security = ScryptPasswordSecurity()
        self.service = AuthService(self.store, self.security, self.locations, clock=lambda: self.now)
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        app.dependency_overrides[get_auth_service] = lambda: self.service
        app.dependency_overrides[get_user_service] = lambda: UserService(SQLiteUserUnitOfWork(self.path))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def signup(self, email="user@example.com", name="온도 사용자", password=PASSWORD):
        response = self.client.post("/api/v1/users/auth/register", json={"name": name, "email": email, "password": password}, headers=HEADERS)
        self.assertEqual(response.status_code, 201, response.text)
        return response

    def profile(self, **changes):
        return {"name": "새 닉네임", "location_id": 1, "preferences": {"cold_sensitivity": "cold", "style": "formal", "activity": "outdoor", "clothing_preference": "menswear", "avoid_items": ["sandals", "shorts"]}, **changes}

    def test_registration_normalizes_email_and_uses_private_cookie(self):
        response = self.signup(" User@Example.com ")
        self.assertEqual(response.json()["data"]["user"]["email"], "user@example.com")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertIn("Path=/api/v1", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)
        self.assertNotIn("password", response.text)
        self.assertNotIn("token", response.text)

    def test_password_and_session_tokens_are_not_stored_in_plain_text(self):
        self.signup()
        token = self.client.cookies.get("ondo_session")
        with closing(connect_database(self.path)) as connection:
            password_hash = connection.execute("SELECT password_hash FROM user_credentials").fetchone()[0]
            token_hash = connection.execute("SELECT token_hash FROM user_sessions").fetchone()[0]
        self.assertNotEqual(token, token_hash)
        self.assertEqual(token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(PASSWORD, password_hash)
        self.assertTrue(self.security.verify(PASSWORD, password_hash))
        self.assertFalse(self.security.verify(PASSWORD.strip(), password_hash))
        self.assertNotEqual(password_hash, self.security.hash(PASSWORD))

    def test_login_rotates_session_and_logout_invalidates_it(self):
        self.signup()
        previous = self.client.cookies.get("ondo_session")
        response = self.client.post("/api/v1/users/auth/login", json={"email": "USER@example.com", "password": PASSWORD}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(previous, self.client.cookies.get("ondo_session"))
        self.assertEqual(self.client.get("/api/v1/users/me", headers={"Cookie": f"ondo_session={previous}"}).status_code, 401)
        token = self.client.cookies.get("ondo_session")
        self.assertEqual(self.client.post("/api/v1/users/auth/logout", headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/users/me", headers={"Cookie": f"ondo_session={token}"}).status_code, 401)

    def test_session_expiry_and_restart(self):
        self.signup()
        restarted = AuthService(SQLiteAuthRepository(self.path), self.security, self.locations, clock=lambda: self.now)
        token = self.client.cookies.get("ondo_session")
        self.assertEqual(restarted.me(token).user.email, "user@example.com")
        self.now += AuthService.SESSION_SECONDS + 1
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)

    def test_login_failure_does_not_disclose_account_existence(self):
        self.signup()
        bodies = []
        for email in ("user@example.com", "missing@example.com"):
            response = self.client.post("/api/v1/users/auth/login", json={"email": email, "password": "wrong-password"}, headers=HEADERS)
            self.assertEqual(response.status_code, 401)
            bodies.append(response.json())
        self.assertEqual(bodies[0], bodies[1])

    def test_mutations_reject_missing_header_and_cross_site(self):
        for headers in ({}, {**HEADERS, "Sec-Fetch-Site": "cross-site"}):
            response = self.client.post("/api/v1/users/auth/register", json={"name": "테스트", "email": "test@example.com", "password": PASSWORD}, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.put("/api/v1/users/me/profile", json=self.profile()).status_code, 403)

    def test_unauthenticated_profile_and_other_account_are_protected(self):
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)
        self.assertEqual(self.client.put("/api/v1/users/me/profile", json=self.profile(), headers=HEADERS).status_code, 401)
        first = self.signup().json()["data"]["user"]["id"]
        own = self.client.get(f"/api/v1/users/{first}")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.headers["cache-control"], "no-store")
        self.signup("other@example.com")
        self.assertEqual(self.client.get(f"/api/v1/users/{first}").status_code, 403)

    def test_profile_is_persisted_and_canonicalizes_avoid_items(self):
        self.signup()
        response = self.client.put("/api/v1/users/me/profile", json=self.profile(), headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]
        self.assertEqual(result["profile"]["preferences"]["avoid_items"], ["sandals", "shorts"])
        self.assertEqual(result["profile"]["location"]["id"], 1)
        self.assertEqual(result["user"]["name"], "새 닉네임")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["data"], result)

    def test_invalid_location_and_unknown_profile_fields_do_not_replace_profile(self):
        self.signup()
        self.assertEqual(self.client.put("/api/v1/users/me/profile", json=self.profile(), headers=HEADERS).status_code, 200)
        before = self.client.get("/api/v1/users/me").json()["data"]
        for values in (self.profile(location_id=999), self.profile(height_cm=180), self.profile(preferences={"clothing_preference": "unsupported"})):
            self.assertEqual(self.client.put("/api/v1/users/me/profile", json=values, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/users/me").json()["data"], before)

    def test_duplicate_signup_does_not_change_password(self):
        self.signup()
        response = self.client.post("/api/v1/users/auth/register", json={"name": "다른 사용자", "email": "USER@example.com", "password": "different-password"}, headers=HEADERS)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post("/api/v1/users/auth/login", json={"email": "user@example.com", "password": PASSWORD}, headers=HEADERS).status_code, 200)

    def test_existing_users_survive_migration_and_cannot_be_claimed(self):
        UserService(SQLiteUserUnitOfWork(self.path)).create_user(CreateUserCommand("이전 사용자", "legacy@example.com"))
        initialize_database(self.path)
        response = self.client.post("/api/v1/users/auth/login", json={"email": "legacy@example.com", "password": PASSWORD}, headers=HEADERS)
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(self.store.credentials("legacy@example.com"))

    def test_login_requests_are_rate_limited_across_service_instances(self):
        with patch.object(self.security, "verify", return_value=False):
            for _ in range(10):
                self.assertEqual(self.client.post("/api/v1/users/auth/login", json={"email": "missing@example.com", "password": PASSWORD}, headers=HEADERS).status_code, 401)
            self.assertEqual(self.client.post("/api/v1/users/auth/login", json={"email": "missing@example.com", "password": PASSWORD}, headers=HEADERS).status_code, 429)
            self.now += 901
            self.assertEqual(self.client.post("/api/v1/users/auth/login", json={"email": "missing@example.com", "password": PASSWORD}, headers=HEADERS).status_code, 401)

    def test_secure_cookie_can_be_enabled_for_https(self):
        with patch("app.users.presentation.router.get_settings", return_value=SimpleNamespace(session_cookie_secure=True)):
            self.assertIn("Secure", self.signup().headers["set-cookie"])


class NewRecommendationInputTests(unittest.TestCase):
    def test_preferences_canonicalization_and_cache_separation(self):
        first = OutfitPreferences(clothing_preference=ClothingPreference.MENSWEAR, avoid_items=(AvoidItem.SHORTS, AvoidItem.SANDALS))
        second = OutfitPreferences(clothing_preference=ClothingPreference.MENSWEAR, avoid_items=(AvoidItem.SANDALS, AvoidItem.SHORTS, AvoidItem.SHORTS))
        self.assertEqual(first, second)
        cache = object.__new__(SQLitePersonalizedOutfitCache)
        cache._scope = "test"
        self.assertEqual(cache._profile_key(1, "today", first), cache._profile_key(1, "today", second))
        self.assertNotEqual(cache._profile_key(1, "today", first), cache._profile_key(1, "today", OutfitPreferences()))
        requirements = _personal_requirements(first)
        self.assertIn("남성복", requirements["선호_의류"])
        self.assertIn("반바지", requirements["피할_의류"])
        self.assertNotIn("email", requirements)
