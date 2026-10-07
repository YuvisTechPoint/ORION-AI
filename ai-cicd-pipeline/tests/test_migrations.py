import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]


def alembic(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    url = db.as_posix()
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{url}", "SYNC_DATABASE_URL": f"sqlite:///{url}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )


def tables(db: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_downgrade_roundtrip(tmp_path):
    db = tmp_path / "migrate.db"
    up = alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert {"pipeline_runs", "pipeline_artifacts", "alembic_version"} <= tables(db)

    down = alembic(db, "downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert tables(db) == {"alembic_version"}

    again = alembic(db, "upgrade", "head")
    assert again.returncode == 0, again.stderr


def test_upgrade_adopts_create_all_schema(tmp_path):
    from app.database import Base
    from app.models import pipeline_artifact, pipeline_run  # noqa: F401

    db = tmp_path / "bootstrapped.db"
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()

    result = alembic(db, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert "alembic_version" in tables(db)
