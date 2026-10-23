import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent


def checked_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.fragment
        or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("URLs must use HTTPS; HTTP is allowed only on loopback")
    return value


@dataclass(frozen=True)
class Settings:
    issuer: str = "http://localhost:8000"
    database: Path = ROOT / "db/auth.sqlite3"
    private_key: Path = ROOT / "db/private_key.pem"
    frontend_login_url: str = "http://localhost:3000/login"
    client_id: str = "website"
    client_secret: str = ""
    redirect_uris: tuple[str, ...] = ("http://localhost:3000/auth/callback",)
    cookie_secure: bool = False
    access_token_ttl: int = 900
    session_ttl: int = 28800
    user_cache_ttl: int = 30
    flow_ttl: int = 300
    code_ttl: int = 60
    cache_capacity: int = 10000

    def __post_init__(self) -> None:
        checked_url(self.issuer)
        checked_url(self.frontend_login_url)
        if urlsplit(self.issuer).query or self.issuer.endswith("/"):
            raise ValueError("AUTH_ISSUER must have no query or trailing slash")
        if not self.client_id or not self.redirect_uris:
            raise ValueError("Configure an OIDC client and its redirect URIs")
        for uri in self.redirect_uris:
            checked_url(uri)
        if any(value <= 0 for value in (
            self.access_token_ttl, self.session_ttl, self.user_cache_ttl,
            self.flow_ttl, self.code_ttl, self.cache_capacity,
        )):
            raise ValueError("TTLs and cache capacity must be positive")
        if urlsplit(self.issuer).scheme == "https" and not self.cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true with HTTPS")

    @property
    def api_audience(self) -> str:
        return f"{self.issuer}/api"

    @property
    def frontend_origin(self) -> str:
        url = urlsplit(self.frontend_login_url)
        return f"{url.scheme}://{url.netloc}"

    @classmethod
    def from_env(cls) -> "Settings":
        def path(name: str, default: str) -> Path:
            value = Path(os.getenv(name, default))
            return value if value.is_absolute() else ROOT / value

        return cls(
            issuer=os.getenv("AUTH_ISSUER", "http://localhost:8000"),
            database=path("AUTH_DATABASE", "db/auth.sqlite3"),
            private_key=path("AUTH_PRIVATE_KEY", "db/private_key.pem"),
            frontend_login_url=os.getenv("AUTH_FRONTEND_LOGIN_URL", "http://localhost:3000/login"),
            client_id=os.getenv("OIDC_CLIENT_ID", "website"),
            client_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
            redirect_uris=tuple(uri.strip() for uri in os.getenv(
                "OIDC_REDIRECT_URIS", "http://localhost:3000/auth/callback"
            ).split(",") if uri.strip()),
            cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
            access_token_ttl=int(os.getenv("AUTH_ACCESS_TOKEN_TTL", "900")),
            session_ttl=int(os.getenv("AUTH_SESSION_TTL", "28800")),
            user_cache_ttl=int(os.getenv("AUTH_USER_CACHE_TTL", "30")),
        )
