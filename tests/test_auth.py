import hashlib
import secrets
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
from fastapi.testclient import TestClient

from backend.auth.cache import CacheFull, TTLCache
from backend.auth.service import AuthError
from backend.auth.tokens import TokenSigner, base64url
from backend.config import Settings
from backend.database import UserRepository
from backend.main import create_app


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.settings = Settings(database=root / "users.sqlite3", private_key=root / "key.pem")
        cls.users = UserRepository(cls.settings.database)
        cls.users.initialize()
        cls.password = "correct horse battery staple"
        cls.user = cls.users.create("alice", cls.password)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.client = TestClient(create_app(self.settings), base_url=self.settings.issuer)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.auth = self.client.app.state.auth
        self.verifier = secrets.token_urlsafe(48)

    def login(self, **extra):
        return self.client.post("/auth/login", json={"login": "alice", "password": self.password, **extra})

    def authorize(self, **extra):
        parameters = {
            "client_id": self.settings.client_id, "redirect_uri": self.settings.redirect_uris[0],
            "response_type": "code", "scope": "openid profile", "state": "frontend-state",
            "nonce": "frontend-nonce", "code_challenge_method": "S256",
            "code_challenge": base64url(hashlib.sha256(self.verifier.encode()).digest()), **extra,
        }
        return self.client.get("/oidc/authorize", params=parameters, follow_redirects=False)

    def code(self, **extra):
        self.assertEqual(self.login().status_code, 200)
        response = self.authorize(**extra)
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        self.assertEqual(query["state"], ["frontend-state"])
        return query["code"][0]

    def exchange(self, code, **extra):
        fields = {
            "grant_type": "authorization_code", "client_id": self.settings.client_id,
            "code": code, "redirect_uri": self.settings.redirect_uris[0],
            "code_verifier": self.verifier, **extra,
        }
        return self.client.post("/oidc/token", data=fields)

    def test_login_cache_refresh_and_logout(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        self.assertNotIn(self.password, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        with patch.object(self.auth.users, "find", side_effect=AssertionError("Profile should be cached")):
            self.assertEqual(self.client.get("/auth/me").json(), self.user.claims())
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/auth/refresh").status_code, 200)
        self.assertEqual(self.client.post("/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh").status_code, 401)

    def test_invalid_credentials_are_indistinguishable(self):
        missing = self.login(login="unknown")
        wrong = self.login(password="incorrect password")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json(), wrong.json())
        self.assertNotIn("auth_session", self.client.cookies)

    def test_validation_does_not_echo_password(self):
        password = "sensitive" * 200
        response = self.login(password=password)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(password, response.text)
        self.assertNotIn("input", response.text)

    def test_rate_limit_and_origin_check(self):
        preflight = self.client.options("/auth/login", headers={
            "Origin": self.settings.frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(preflight.headers["access-control-allow-origin"], self.settings.frontend_origin)
        self.assertEqual(preflight.headers["access-control-allow-credentials"], "true")
        response = self.client.post("/auth/login", headers={"Origin": "https://attacker.example"}, json={
            "login": "alice", "password": self.password,
        })
        self.assertEqual(response.status_code, 403)
        for _ in range(10):
            self.assertTrue(self.auth.limiter.check("testclient"))
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(self.client.post("/auth/logout", headers={"Origin": "null"}).status_code, 403)

    def test_oidc_from_login_redirect_to_signed_id_token(self):
        authorization = self.authorize()
        self.assertEqual(authorization.status_code, 302)
        location = urlsplit(authorization.headers["location"])
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}", self.settings.frontend_login_url)
        request_id = parse_qs(location.query)["request_id"][0]
        logged_in = self.login(request_id=request_id)
        self.assertEqual(logged_in.status_code, 200)
        callback = urlsplit(logged_in.json()["redirect_url"])
        query = parse_qs(callback.query)
        self.assertEqual(query["state"], ["frontend-state"])
        response = self.exchange(query["code"][0])
        self.assertEqual(response.status_code, 200)
        tokens = response.json()
        key = jwt.PyJWK.from_dict(self.client.get("/oidc/jwks").json()["keys"][0]).key
        claims = jwt.decode(tokens["id_token"], key, algorithms=["RS256"], audience="website", issuer=self.settings.issuer)
        self.assertEqual(claims["sub"], self.user.id)
        self.assertEqual(claims["nonce"], "frontend-nonce")
        self.assertEqual(claims["preferred_username"], "alice")
        self.assertEqual(claims["at_hash"], base64url(hashlib.sha256(tokens["access_token"].encode()).digest()[:16]))
        self.assertEqual(self.exchange(query["code"][0]).json()["error"], "invalid_grant")
        self.assertEqual(self.login(request_id=request_id).status_code, 400)
        info = self.client.get("/oidc/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertEqual(info.json(), self.user.claims())
        info = self.client.post("/oidc/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertEqual(info.json(), self.user.claims())

    def test_login_flow_is_bound_to_browser(self):
        location = self.authorize().headers["location"]
        request_id = parse_qs(urlsplit(location).query)["request_id"][0]
        self.client.cookies.clear()
        self.assertEqual(self.login(request_id=request_id).status_code, 400)

    def test_invalid_redirect_is_not_followed(self):
        response = self.authorize(redirect_uri="https://attacker.example/callback")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)
        duplicate = self.client.get("/oidc/authorize?client_id=website&client_id=other", follow_redirects=False)
        self.assertEqual(duplicate.status_code, 400)

    def test_pkce_is_required_and_wrong_verifier_consumes_code(self):
        response = self.authorize(code_challenge_method="plain")
        self.assertEqual(parse_qs(urlsplit(response.headers["location"]).query)["error"], ["invalid_request"])
        code = self.code()
        self.assertEqual(self.exchange(code, code_verifier="wrong" * 10).json()["error"], "invalid_grant")
        self.assertEqual(self.exchange(code).json()["error"], "invalid_grant")

    def test_code_exchange_is_atomic(self):
        code = self.code()

        def redeem():
            try:
                self.auth.exchange_code(code, self.settings.redirect_uris[0], self.verifier)
                return "ok"
            except AuthError as error:
                return error.error

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: redeem(), range(2)))
        self.assertCountEqual(results, ["ok", "invalid_grant"])

    def test_expired_code_and_session_are_rejected(self):
        code = self.code()
        with patch.object(self.auth.codes, "clock", return_value=time.monotonic() + 120):
            self.assertEqual(self.exchange(code).json()["error"], "invalid_grant")
        token = self.login().json()["access_token"]
        with patch.object(self.auth.sessions, "clock", return_value=time.monotonic() + self.settings.session_ttl + 1):
            self.assertEqual(self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)

    def test_tampered_expired_and_id_tokens_cannot_authenticate(self):
        code = self.code()
        tokens = self.exchange(code).json()
        decoded = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        wrong_audience = jwt.encode({**decoded, "aud": "other"}, self.auth.signer.key, algorithm="RS256", headers={"typ": "at+jwt"})
        expired = jwt.encode({**decoded, "exp": int(time.time()) - 1}, self.auth.signer.key, algorithm="RS256", headers={"typ": "at+jwt"})
        parts = tokens["access_token"].split(".")
        parts[1] = base64url(b'{"sub":"attacker"}')
        for token in (tokens["id_token"], ".".join(parts), wrong_audience, expired, "garbage"):
            response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 401)

    def test_scope_and_prompt_none(self):
        response = self.authorize(prompt="none")
        self.assertEqual(parse_qs(urlsplit(response.headers["location"]).query)["error"], ["login_required"])
        code = self.code(scope="openid")
        tokens = self.exchange(code).json()
        info = self.client.get("/oidc/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertEqual(info.json(), {"sub": self.user.id})
        claims = jwt.decode(tokens["id_token"], options={"verify_signature": False})
        self.assertNotIn("preferred_username", claims)
        self.assertIn("request_id", self.authorize(prompt="login").headers["location"])

    def test_profile_cache_reloads_and_disabled_user_loses_session(self):
        self.login()
        self.auth.profiles.pop(self.user.id)
        with patch.object(self.auth.users, "find", return_value=replace(self.user, is_active=False)):
            self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_confidential_client_must_authenticate(self):
        settings = replace(self.settings, client_secret="server-only-client-secret")
        with TestClient(create_app(settings), base_url=settings.issuer) as client:
            client.post("/auth/login", json={"login": "alice", "password": self.password})
            parameters = {
                "client_id": "website", "redirect_uri": settings.redirect_uris[0], "response_type": "code",
                "scope": "openid", "code_challenge_method": "S256",
                "code_challenge": base64url(hashlib.sha256(self.verifier.encode()).digest()),
            }
            response = client.get("/oidc/authorize", params=parameters, follow_redirects=False)
            code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
            fields = {
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": settings.redirect_uris[0], "code_verifier": self.verifier,
            }
            self.assertEqual(client.post("/oidc/token", data=fields).status_code, 401)
            self.assertEqual(client.post("/oidc/token", data=fields, auth=("website", settings.client_secret)).status_code, 200)

    def test_key_is_persistent_and_discovery_is_consistent(self):
        signer = TokenSigner(self.settings)
        self.assertEqual(signer.jwks(), self.auth.signer.jwks())
        discovery = self.client.get("/.well-known/openid-configuration").json()
        self.assertEqual(discovery["issuer"], self.settings.issuer)
        self.assertEqual(discovery["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(discovery["token_endpoint_auth_methods_supported"], ["none"])

    def test_sqlite_has_hashes_and_enforces_unique_login(self):
        user, password_hash = self.users.credentials("ALICE")
        self.assertEqual(user, self.user)
        self.assertNotIn(self.password, password_hash)
        self.assertTrue(password_hash.startswith("scrypt$"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.users.create("ALICE", "another long password")
        self.assertEqual(self.login(login="' OR 1=1 --").status_code, 401)


class CacheTests(unittest.TestCase):
    def test_expiration_and_capacity(self):
        now = [100.0]
        cache = TTLCache(1, clock=lambda: now[0])
        cache.put("key", "value", 10)
        with self.assertRaises(CacheFull):
            cache.put("other", "value", 10)
        now[0] = 111
        self.assertIsNone(cache.get("key"))
        cache.put("other", "new", 10)
        self.assertEqual(cache.pop("other"), "new")
        self.assertIsNone(cache.pop("other"))


if __name__ == "__main__":
    unittest.main()
