import argparse
import getpass
import sqlite3

from backend.config import Settings
from backend.database import UserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize SQLite or manage auth users")
    parser.add_argument("command", choices=("init", "create", "list", "show"))
    parser.add_argument("login", nargs="?")
    arguments = parser.parse_args()
    repository = UserRepository(Settings.from_env().database)
    repository.initialize()

    if arguments.command == "init":
        print(f"Database initialized: {repository.path}")
        return

    if arguments.command == "list":


        rows = repository.all()
        print(f"Database: {repository.path}")
        if not rows:
            print("No users.")
            return
        for user in rows:
            state = "active" if user.is_active else "disabled"
            print(f"{user.login}\t{user.id}\t{state}")
        return

    if arguments.command == "show":
        if not arguments.login:
            parser.error("show requires a login")
        found = repository.credentials(arguments.login)
        if found is None:
            parser.error(f"user not found: {arguments.login}")
        user = found[0]
        state = "active" if user.is_active else "disabled"
        print(f"login: {user.login}\nid: {user.id}\nstate: {state}")
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
