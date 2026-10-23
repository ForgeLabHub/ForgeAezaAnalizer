import base64
import hashlib
import os
import secrets
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.config import Settings


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class TokenSigner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.key = self._load_key(settings.private_key)
        self.public_key = self.key.public_key()
        der = self.public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.kid = base64url(hashlib.sha256(der).digest())

    @staticmethod
    def _load_key(path: Path) -> rsa.RSAPrivateKey:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            encoded = key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            try:
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
                    file.write(encoded)
            except FileExistsError:
                pass
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("AUTH_PRIVATE_KEY must contain an RSA key of at least 2048 bits")
        return key

    def jwks(self) -> dict:
        numbers = self.public_key.public_numbers()

        def encode(number: int) -> str:
            return base64url(number.to_bytes((number.bit_length() + 7) // 8, "big"))

        return {"keys": [{
            "kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
            "n": encode(numbers.n), "e": encode(numbers.e),
        }]}

    def access_token(self, user_id: str, session_id: str, expires_in: int, scope: str) -> str:
        now = int(time.time())
        return jwt.encode({
            "iss": self.settings.issuer, "aud": self.settings.api_audience,
            "sub": user_id, "sid": session_id, "iat": now, "nbf": now,
            "exp": now + expires_in, "jti": secrets.token_urlsafe(16),
            "token_use": "access", "scope": scope,
        }, self.key, algorithm="RS256", headers={"kid": self.kid, "typ": "at+jwt"})

    def id_token(
        self, claims: dict, session_id: str, auth_time: int, expires_in: int,
        nonce: str | None, access_token: str,
    ) -> str:
        now = int(time.time())
        payload = {
            **claims, "iss": self.settings.issuer, "aud": self.settings.client_id,
            "iat": now, "exp": now + expires_in, "sid": session_id,
            "auth_time": auth_time, "amr": ["pwd"],
            "at_hash": base64url(hashlib.sha256(access_token.encode()).digest()[:16]),
        }
        if nonce is not None:
            payload["nonce"] = nonce
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": self.kid})

    def verify_access(self, token: str) -> dict:
        if len(token) > 8192 or jwt.get_unverified_header(token).get("typ") != "at+jwt":
            raise jwt.InvalidTokenError("Invalid access token")
        payload = jwt.decode(
            token, self.public_key, algorithms=["RS256"],
            audience=self.settings.api_audience, issuer=self.settings.issuer,
            options={"require": ["exp", "iat", "nbf", "sub", "sid", "token_use", "scope"], "strict_aud": True},
        )
        if payload["token_use"] != "access" or not isinstance(payload["sid"], str):
            raise jwt.InvalidTokenError("Invalid access token")
        return payload
