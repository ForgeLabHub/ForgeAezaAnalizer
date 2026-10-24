import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from backend.auth.passwords import hash_password
from backend.config import ROOT


@dataclass(frozen=True)
class User:
    id: str
    login: str
    is_active: bool
    auth_version: int

    def claims(self) -> dict[str, str]:
        return {"sub": self.id, "preferred_username": self.login}


class UserRepository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema_path = ROOT / "db/schema.sql"
        if not schema_path.exists():
            schema_path = Path(__file__).with_name("auth_schema.sql")
        with self.connect() as connection:
            connection.executescript(schema_path.read_text(encoding="utf-8"))

    @staticmethod
    def _user(row: tuple) -> User:
        return User(row[0], row[1], bool(row[2]), row[3])

    def credentials(self, login: str) -> tuple[User, str] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, login, is_active, auth_version, password_hash FROM users WHERE login = ?",
                (login,),
            ).fetchone()
        return (self._user(row), row[4]) if row else None

    def find(self, user_id: str) -> User | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, login, is_active, auth_version FROM users WHERE id = ?", (user_id,),
            ).fetchone()
        return self._user(row) if row else None

    def create(self, login: str, password: str) -> User:
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,128}", login):
            raise ValueError("Login must contain 3 to 128 letters, digits, or _.@-")
        user = User(str(uuid.uuid4()), login, True, 1)
        password_hash = hash_password(password)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO users (id, login, password_hash) VALUES (?, ?, ?)",
                (user.id, login, password_hash),
            )
        return user
