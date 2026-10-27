from pump_sentinel.state import StateStore


def sample(balance="100", complete=True):
    snapshot = {"mint": "mint1", "observed_at": 100.0, "complete": complete,
                "wallet_balance_raw": balance}
    report = {"mint": "mint1", "observed_at": 100.0, "posture": "OBSERVE", "findings": [],
              "metrics": {"wallet_balance_ui": balance}}
    return snapshot, report


def test_state_is_scoped_by_wallet_and_mint(tmp_path):
    store = StateStore(str(tmp_path / "data/state.sqlite3"))
    try:
        snapshot, report = sample()
        assert store.save("wallet1", snapshot, report)
        assert not store.save("wallet1", snapshot, report)
        assert store.previous_balance("wallet1", "mint1") == "100"
        assert store.previous_balance("wallet2", "mint1") is None
        assert store.previous_balance("wallet1", "mint2") is None
    finally:
        store.close()


def test_partial_failure_does_not_advance_baseline(tmp_path):
    store = StateStore(str(tmp_path / "state.sqlite3"))
    try:
        store.save("wallet", *sample())
        store.save("wallet", *sample("200", False))
        assert store.previous_balance("wallet", "mint1") == "100"
        store.save("wallet", *sample(None, False))
        assert store.previous_balance("wallet", "mint1") == "100"
    finally:
        store.close()


def test_history_retention(tmp_path):
    store = StateStore(str(tmp_path / "state.sqlite3"), max_history=3)
    try:
        for _ in range(6):
            store.save("wallet", *sample())
        assert store.db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 3
    finally:
        store.close()


def test_permissions_and_persistence(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = StateStore(str(path))
    store.save("wallet", *sample())
    store.close()
    assert path.stat().st_mode & 0o777 == 0o600
    reopened = StateStore(str(path))
    try:
        assert reopened.previous_balance("wallet", "mint1") == "100"
    finally:
        reopened.close()
