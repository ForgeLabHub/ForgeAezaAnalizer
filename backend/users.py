import argparse
import getpass
import sqlite3

from backend.config import Settings
from backend.database import UserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize SQLite or create an auth user")
    parser.add_argument("command", choices=("init", "create"))
    parser.add_argument("login", nargs="?")
    arguments = parser.parse_args()
    repository = UserRepository(Settings.from_env().database)
    repository.initialize()
    if arguments.command == "init":
        print(f"Database initialized: {repository.path}")
        return
    if not arguments.login:
        parser.error("create requires a login")
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords do not match")
    try:
        user = repository.create(arguments.login, password)
    except (ValueError, sqlite3.IntegrityError) as error:
        parser.error(str(error))
    print(f"User created: {user.login} ({user.id})")


if __name__ == "__main__":
    main()
