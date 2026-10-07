from services.state_store import SQLiteStateStore, build_state_store


def test_build_state_store_returns_sqlite_for_sqlite_url(tmp_path) -> None:
    db_path = tmp_path / "factory.db"
    store = build_state_store(f"sqlite:///{db_path}")
    assert isinstance(store, SQLiteStateStore)


def test_build_state_store_falls_back_to_sqlite_for_broken_postgres(monkeypatch, tmp_path) -> None:
    from services import state_store as state_store_module

    def _raise(_database_url: str):
        raise RuntimeError("postgres down")

    monkeypatch.setattr(state_store_module, "PostgresStateStore", _raise)

    db_path = tmp_path / "fallback.db"
    store = state_store_module.build_state_store(f"postgresql://localhost/devops?fallback={db_path}")
    assert isinstance(store, SQLiteStateStore)
