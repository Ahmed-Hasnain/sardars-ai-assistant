"""Purge expired conversation records; run periodically from the project root.

    PYTHONPATH=backend backend/.venv/bin/python -m app.services.purge_conversations
"""

from app.db.session import SessionLocal
from app.services.conversations import purge_expired


def main() -> None:
    deleted = 0
    with SessionLocal() as db:
        while count := purge_expired(db):
            deleted += count
    print(f"Deleted {deleted} expired conversations")


if __name__ == "__main__":
    main()
