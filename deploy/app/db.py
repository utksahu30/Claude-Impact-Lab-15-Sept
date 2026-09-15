# app/db.py
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
from .config import settings

# Connect args for SQLite to ensure threads share access cleanly
connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args
)


# Configure SQLite for Write-Ahead Logging (WAL) and busy timeout
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


def init_db():
    """Initializes all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency for yielding database sessions."""
    with Session(engine) as session:
        yield session
