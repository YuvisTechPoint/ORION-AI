"""Create user table (and any missing tables) using SQLAlchemy metadata.

This is a simple migration helper for local/dev use. For production, use Alembic.
"""
from core.db import engine, Base
# Import models to ensure they are registered on Base
import models.db_models  # noqa: F401

if __name__ == "__main__":
    print("Creating missing tables (if any)...")
    Base.metadata.create_all(bind=engine)
    print("Done. Tables created/verified.")
