import base64
import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    if not 7 <= len(password) <= 1024:
        raise ValueError("Password must contain 12 to 1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=131072, r=8, p=1,
        dklen=32, maxmem=256 * 1024 * 1024,
    )
    return "scrypt$131072$8$1$" + "$".join(
        base64.b64encode(value).decode() for value in (salt, digest)
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "131072", "8", "1"):
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt, validate=True),
            n=int(n), r=int(r), p=int(p), dklen=32, maxmem=256 * 1024 * 1024,
        )
        return hmac.compare_digest(digest, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False
