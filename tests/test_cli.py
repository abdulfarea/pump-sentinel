import json
import time

from pump_sentinel import cli

MINT = "So11111111111111111111111111111111111111112"
WALLET = "11111111111111111111111111111111"


class FakeReader:
    calls = 0
    closed = False

    def __init__(self, url):
        FakeReader.calls = 0
        FakeReader.closed = False

    def snapshot(self, mint, wallet, excluded):
        FakeReader.calls += 1
        return {"mint": mint, "observed_at": time.time(), "complete": True, "errors": [],
                "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "mint_authority": None, "freeze_authority": None, "extensions": [],
                "unknown_extensions": False, "supply_raw": "1000", "decimals": 0,
                "largest_accounts": [{"address": MINT, "amount_raw": "100"}],
                "excluded_accounts": excluded, "wallet_balance_raw": "100" if FakeReader.calls == 1 else "90",
                "wallet_frozen_accounts": [], "slots": {"mint": 100, "largest": 100, "wallet": 100}}

    def close(self):
        FakeReader.closed = True


def config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(f'mints = ["{MINT}"]\nwallet = "{WALLET}"\n')
    return str(path)


def test_demo_is_offline(monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise AssertionError("demo não pode usar RPC")
    monkeypatch.setattr(cli, "SolanaReader", denied)
    assert cli.main(["demo"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["simulated"] is True
    assert report["pause_new_actions"] is True


def test_proactive_two_cycles_notice_balance_change(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "SolanaReader", FakeReader)
    ticks = iter(range(0, 1000, 31))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    assert cli.main(["watch", "--config", config(tmp_path), "--cycles", "2"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    reports = [x for x in events if "findings" in x]
    assert len(reports) == 2
    assert reports[1]["metrics"]["wallet_delta_raw"] == "-10"
    assert "WALLET_BALANCE_DECREASE" in [x["code"] for x in reports[1]["findings"]]
    assert len([x for x in events if x.get("event") == "heartbeat"]) == 2
    assert FakeReader.closed


def test_kill_switch_prevents_requests(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "SolanaReader", FakeReader)
    (tmp_path / "PAUSE").touch()
    assert cli.main(["once", "--config", config(tmp_path)]) == 2
    assert FakeReader.calls == 0
    assert json.loads(capsys.readouterr().out)["event"] == "kill_switch"
    assert FakeReader.closed


def test_invalid_json_is_fail_closed_without_traceback(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("not json")
    assert cli.main(["analyze", str(path)]) == 2
    output = capsys.readouterr()
    assert "Traceback" not in output.out + output.err
    assert json.loads(output.out)["pause_new_actions"] is True
