import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ledger:ledger@localhost:5432/ledger")

# Support graceful testing fallback if PostgreSQL is not locally accessible
engine = None
try:
    if DATABASE_URL.startswith("postgresql"):
        # Test connection with a short timeout
        test_engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
        with test_engine.connect() as conn:
            pass
        engine = test_engine
    else:
        engine = create_engine(DATABASE_URL)
except Exception:
    # Fallback to local SQLite for isolated test environments
    sqlite_url = "sqlite:///./ledger_fallback.db"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
