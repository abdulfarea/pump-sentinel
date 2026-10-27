from __future__ import annotations

import time

import pytest

from pump_sentinel import engine
from pump_sentinel.engine import (
    CLASSIC_TOKEN_PROGRAM,
    TOKEN_2022_PROGRAM,
    analyze_snapshot,
)


NOW = time.time()


def _account(address: str, amount: int | str) -> dict[str, str]:
    return {"address": address, "amount_raw": str(amount)}


def _snapshot(**overrides: object) -> dict:
    base = {
        "mint": "Mint111111111111111111111111111111111111111",
        "observed_at": NOW,
        "complete": True,
        "errors": [],
        "program": CLASSIC_TOKEN_PROGRAM,
        "mint_authority": None,
        "freeze_authority": None,
        "extensions": [],
        "unknown_extensions": False,
        "supply_raw": "100000",
        "decimals": 2,
        "largest_accounts": [_account("wallet-a", 10000), _account("wallet-b", 10000)],
        "excluded_accounts": [],
        "wallet_balance_raw": "12345",
        "slots": {"rpc_a": 100, "rpc_b": 100},
        "previous_wallet_balance_raw": None,
        "data_age_seconds": 0.0,
    }
    base.update(overrides)
    return base


def _codes(result: dict) -> set[str]:
    return {finding["code"] for finding in result["findings"]}


def test_baseline_is_observe_and_preserves_decimal_raw_math(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine.time, "time", lambda: NOW)
    result = analyze_snapshot(_snapshot(previous_wallet_balance_raw="12000"))

    assert result["posture"] == "OBSERVE"
    assert result["pause_new_actions"] is False
    assert result["findings"] == []
    assert result["heuristic_score"] == 0
    assert result["metrics"]["largest_account_pct"] == pytest.approx(10.0)
    assert result["metrics"]["top10_accounts_pct"] == pytest.approx(20.0)
    assert result["metrics"]["wallet_balance_ui"] == "123.45"
    assert result["metrics"]["wallet_delta_raw"] == "345"
    assert all("segurança" not in limitation.lower() or "garantia" in limitation.lower() for limitation in result["limitations"])


def test_authorities_are_critical_pause_findings() -> None:
    result = analyze_snapshot(
        _snapshot(mint_authority="AuthorityMint", freeze_authority="AuthorityFreeze")
    )

    assert result["posture"] == "PAUSE"
    assert result["pause_new_actions"] is True
    assert {"MINT_AUTHORITY_PRESENT", "FREEZE_AUTHORITY_PRESENT"} <= _codes(result)
    assert all(finding["severity"] == "CRITICAL" for finding in result["findings"])


def test_incomplete_snapshot_and_reported_errors_fail_closed() -> None:
    result = analyze_snapshot(_snapshot(complete=False, errors=["rpc indisponível"]))

    assert result["posture"] == "PAUSE"
    assert result["pause_new_actions"] is True
    assert {"INCOMPLETE_SNAPSHOT", "SNAPSHOT_ERRORS"} <= _codes(result)


def test_stale_observed_at_cannot_be_hidden_by_reported_age(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine.time, "time", lambda: NOW)
    result = analyze_snapshot(_snapshot(observed_at=NOW - 121.0, data_age_seconds=0.0))

    assert result["posture"] == "PAUSE"
    assert "STALE_DATA" in _codes(result)
    assert result["metrics"]["data_age_seconds"] == pytest.approx(121.0)


def test_future_timestamp_allows_small_clock_tolerance_but_pauses_beyond_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine.time, "time", lambda: NOW)

    within_tolerance = analyze_snapshot(_snapshot(observed_at=NOW + 5.0, data_age_seconds=0.0))
    beyond_tolerance = analyze_snapshot(_snapshot(observed_at=NOW + 5.01, data_age_seconds=0.0))

    assert "FUTURE_TIMESTAMP" not in _codes(within_tolerance)
    assert within_tolerance["posture"] == "OBSERVE"
    assert "FUTURE_TIMESTAMP" in _codes(beyond_tolerance)
    assert beyond_tolerance["posture"] == "PAUSE"


def test_slot_skew_threshold_is_strictly_greater_than_limit() -> None:
    edge = analyze_snapshot(_snapshot(slots={"rpc_a": 100, "rpc_b": 250}))
    beyond = analyze_snapshot(_snapshot(slots={"rpc_a": 100, "rpc_b": 251}))

    assert edge["metrics"]["slot_skew"] == 150
    assert "SLOT_SKEW" not in _codes(edge)
    assert "SLOT_SKEW" in _codes(beyond)
    assert beyond["posture"] == "PAUSE"


def test_raw_amounts_above_float_exact_range_keep_exact_ui_and_delta() -> None:
    supply = "9007199254740993"
    wallet = "9007199254740993"
    previous = "9007199254740000"
    result = analyze_snapshot(
        _snapshot(
            supply_raw=supply,
            largest_accounts=[_account("large", supply)],
            wallet_balance_raw=wallet,
            previous_wallet_balance_raw=previous,
            decimals=3,
        )
    )

    assert result["metrics"]["wallet_balance_ui"] == "9007199254740.993"
    assert result["metrics"]["wallet_delta_raw"] == "993"
    assert result["metrics"]["largest_account_pct"] == 100.0
    assert "SINGLE_ACCOUNT_CONCENTRATION" in _codes(result)


def test_zero_supply_has_no_undefined_percentages() -> None:
    result = analyze_snapshot(
        _snapshot(supply_raw="0", largest_accounts=[], wallet_balance_raw=None)
    )

    assert result["posture"] == "PAUSE"
    assert "ZERO_SUPPLY" in _codes(result)
    assert result["metrics"]["largest_account_pct"] is None
    assert result["metrics"]["top10_accounts_pct"] is None


def test_excluded_pool_is_not_removed_from_full_supply_denominator() -> None:
    result = analyze_snapshot(
        _snapshot(
            supply_raw="1000",
            largest_accounts=[_account("known-pool", 800), _account("wallet", 100)],
            excluded_accounts=["known-pool"],
            wallet_balance_raw=None,
        )
    )

    assert result["metrics"]["largest_account_pct"] == pytest.approx(10.0)
    assert result["metrics"]["top10_accounts_pct"] == pytest.approx(10.0)
    assert result["metrics"]["raw_largest_account_pct"] == pytest.approx(80.0)
    assert result["metrics"]["raw_top10_accounts_pct"] == pytest.approx(90.0)
    assert "EXCLUDED_ACCOUNTS_CAUTION" in _codes(result)
    assert "SINGLE_ACCOUNT_CONCENTRATION" not in _codes(result)


def test_malformed_fields_fail_closed_without_raising() -> None:
    malformed_cases = [
        {"program": ["not-hashable-program"]},
        {"supply_raw": "1.5"},
        {"decimals": True},
        {"largest_accounts": [{"address": "wallet", "amount_raw": "NaN"}]},
        {"excluded_accounts": [None]},
        {"wallet_balance_raw": "-1"},
        {"slots": {"rpc": "not-an-int"}},
        {"extensions": [""]},
        {"unknown_extensions": "false"},
        {"data_age_seconds": float("nan")},
    ]

    for changes in malformed_cases:
        result = analyze_snapshot(_snapshot(**changes))
        assert result["posture"] == "PAUSE", changes
        assert result["pause_new_actions"] is True, changes
        assert result["heuristic_score"] <= 100
        assert result["findings"], changes


def test_token2022_flagged_extension_is_explicit_high_pause() -> None:
    result = analyze_snapshot(
        _snapshot(
            program=TOKEN_2022_PROGRAM,
            extensions=["pausable"],
        )
    )

    finding = next(item for item in result["findings"] if item["code"] == "TOKEN2022_FLAGGED_EXTENSION")
    assert finding["severity"] == "HIGH"
    assert result["posture"] == "PAUSE"
    assert result["pause_new_actions"] is True


def test_token2022_known_metadata_extension_requires_caution() -> None:
    result = analyze_snapshot(
        _snapshot(
            program=TOKEN_2022_PROGRAM,
            extensions=["tokenMetadata"],
        )
    )

    assert "TOKEN2022_EXTENSION_CAUTION" in _codes(result)
    assert result["posture"] == "CAUTION"
    assert result["pause_new_actions"] is False


def test_token2022_unknown_extension_pauses_even_if_boolean_is_false() -> None:
    result = analyze_snapshot(
        _snapshot(
            program=TOKEN_2022_PROGRAM,
            extensions=["futureExtensionFromNewRuntime"],
            unknown_extensions=False,
        )
    )

    assert "UNKNOWN_EXTENSION" in _codes(result)
    assert result["posture"] == "PAUSE"


def test_unknown_extension_flag_pauses() -> None:
    result = analyze_snapshot(
        _snapshot(
            program=TOKEN_2022_PROGRAM,
            extensions=[],
            unknown_extensions=True,
        )
    )

    assert "UNKNOWN_EXTENSION" in _codes(result)
    assert result["pause_new_actions"] is True


def test_concentration_threshold_edges_are_not_flagged() -> None:
    amounts = [20] + [5] * 8 + [0]
    accounts = [_account(f"account-{index}", amount) for index, amount in enumerate(amounts)]
    result = analyze_snapshot(
        _snapshot(
            supply_raw="100",
            largest_accounts=accounts,
            wallet_balance_raw=None,
        ),
        {"max_single_account_pct": 20.0, "max_top10_accounts_pct": 60.0},
    )

    assert result["metrics"]["largest_account_pct"] == pytest.approx(20.0)
    assert result["metrics"]["top10_accounts_pct"] == pytest.approx(60.0)
    assert "SINGLE_ACCOUNT_CONCENTRATION" not in _codes(result)
    assert "TOP10_CONCENTRATION" not in _codes(result)
    assert result["posture"] == "OBSERVE"


def test_optional_frozen_wallet_accounts_are_high_not_a_scam_label() -> None:
    result = analyze_snapshot(_snapshot(wallet_frozen_accounts=["wallet-b"]))

    finding = next(item for item in result["findings"] if item["code"] == "WALLET_FROZEN_ACCOUNTS")
    assert finding["severity"] == "HIGH"
    assert "fraude" in finding["message"]
    assert result["posture"] == "PAUSE"


def test_output_shape_always_contains_required_fields_for_non_dict_input() -> None:
    result = analyze_snapshot(None)  # type: ignore[arg-type]

    assert {
        "mint",
        "observed_at",
        "heuristic_score",
        "posture",
        "pause_new_actions",
        "findings",
        "metrics",
        "limitations",
    } <= result.keys()
    assert result["posture"] == "PAUSE"
