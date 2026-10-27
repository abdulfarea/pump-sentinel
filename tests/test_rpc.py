from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pump_sentinel.rpc as rpc_module
from pump_sentinel.rpc import (
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    RpcError,
    SolanaReader,
    validate_pubkey,
)


ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MINT = "4" * 32
WALLET = "5" * 32
AUTHORITY = "6" * 32
LARGEST_EXCLUDED = "7" * 32
LARGEST_INCLUDED = "8" * 32
WALLET_TOKEN = "9" * 32
WALLET_TOKEN_2 = "A" * 32


def b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + (encoded or "")


def pubkey(seed: int) -> str:
    return b58encode(bytes([seed]) * 32)


# Use actual 32-byte base58 values rather than strings that only happen to look
# like public keys.  This also makes the test fixtures exercise decode length.
MINT = pubkey(1)
WALLET = pubkey(2)
AUTHORITY = pubkey(3)
LARGEST_EXCLUDED = pubkey(4)
LARGEST_INCLUDED = pubkey(5)
WALLET_TOKEN = pubkey(6)
WALLET_TOKEN_2 = pubkey(7)
OTHER_WALLET = pubkey(8)


def envelope(result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def rpc_error() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "internal"}}


def mint_result(
    *,
    slot: int = 100,
    owner: str = TOKEN_PROGRAM_ID,
    info: dict | None = None,
    program: str = "spl-token",
    value: object | None = None,
) -> dict:
    if value is None:
        if info is None:
            info = {
                "mintAuthority": AUTHORITY,
                "freezeAuthority": None,
                "supply": "9007199254740993",
                "decimals": 6,
            }
        value = {
            "owner": owner,
            "data": {
                "program": program,
                "parsed": {"type": "mint", "info": info},
            },
        }
    return {"context": {"slot": slot}, "value": value}


def largest_result(*, slot: int = 101, values: list[dict] | None = None) -> dict:
    if values is None:
        values = [
            {"address": LARGEST_EXCLUDED, "amount": "12"},
            {"address": LARGEST_INCLUDED, "amount": 9007199254740993},
        ]
    return {"context": {"slot": slot}, "value": values}


def wallet_account(
    address: str,
    *,
    mint: str = MINT,
    owner: str = WALLET,
    state: str = "initialized",
    amount: str | int = "0",
    program_owner: str = TOKEN_PROGRAM_ID,
) -> dict:
    return {
        "pubkey": address,
        "account": {
            "owner": program_owner,
            "data": {
                "program": "spl-token",
                "parsed": {
                    "type": "account",
                    "info": {
                        "mint": mint,
                        "owner": owner,
                        "state": state,
                        "tokenAmount": {"amount": amount, "decimals": 6},
                    },
                },
            },
        },
    }


def reader_for(handler):
    def consistent_handler(request):
        response = handler(request)
        try:
            body = response.json()
        except ValueError:
            return response
        if isinstance(body, dict) and "jsonrpc" in body:
            body["id"] = json.loads(request.content)["id"]
            return httpx.Response(response.status_code, json=body)
        return response
    client = httpx.Client(transport=httpx.MockTransport(consistent_handler))
    return SolanaReader("https://rpc.example.invalid", client=client)


def test_validate_pubkey_decodes_exactly_32_bytes_without_curve_check():
    assert validate_pubkey(MINT) == MINT
    assert validate_pubkey("1" * 32) == "1" * 32
    for value in ("", "0" * 32, "1" * 31, "1" * 33, "not-base58!", None):
        with pytest.raises(RpcError):
            validate_pubkey(value)  # type: ignore[arg-type]


def test_tls_policy_allows_local_http_and_rejects_remote_http_without_secret_leak():
    local = SolanaReader("http://127.0.0.1:8899", client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
    local.close()

    secret_url = "http://rpc.example.invalid/?api_key=super-secret"
    with pytest.raises(RpcError) as raised:
        SolanaReader(secret_url)
    assert "super-secret" not in str(raised.value)
    assert "rpc.example.invalid" not in str(raised.value)


def test_call_allowlist_and_json_result_only():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=envelope({"context": {"slot": 1}, "value": []}))

    reader = reader_for(handler)
    try:
        result = reader.call("getTokenLargestAccounts", [MINT, {"commitment": "confirmed"}])
        assert result == {"context": {"slot": 1}, "value": []}
        assert seen[0]["method"] == "getTokenLargestAccounts"
        assert seen[0]["params"] == [MINT, {"commitment": "confirmed"}]
        for denied in ("sendTransaction", "signTransaction", "getProgramAccounts"):
            with pytest.raises(RpcError):
                reader.call(denied, [])
        assert len(seen) == 1
    finally:
        reader.close()


def test_call_retries_429_and_5xx_with_bounded_sleep(monkeypatch):
    responses = [
        httpx.Response(429, json={"error": "busy"}),
        httpx.Response(503, json={"error": "busy"}),
        httpx.Response(200, json=envelope({"context": {"slot": 9}, "value": []})),
    ]
    sleeps: list[float] = []
    monkeypatch.setattr(rpc_module.time, "sleep", sleeps.append)

    def handler(_: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reader = SolanaReader("https://rpc.example.invalid", max_retries=2, client=client)
    try:
        assert reader.call("getTokenLargestAccounts", [MINT]) ["context"]["slot"] == 9
        assert len(sleeps) == 2
        assert all(0 <= delay <= 1.0 for delay in sleeps)
    finally:
        reader.close()


def test_snapshot_full_schema_preserves_large_raw_amounts_and_filters_exclusions():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(
                200,
                json=envelope(mint_result(info={
                    "mintAuthority": AUTHORITY,
                    "freezeAuthority": None,
                    "supply": "9007199254740993",
                    "decimals": 6,
                    "extensions": [
                        {"extension": "mintCloseAuthority", "state": {"closeAuthority": AUTHORITY}},
                    ],
                })),
            )
        if method == "getTokenLargestAccounts":
            return httpx.Response(200, json=envelope(largest_result()))
        if method == "getTokenAccountsByOwner":
            assert json.loads(request.content)["params"] == [
                WALLET,
                {"mint": MINT},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ]
            return httpx.Response(
                200,
                json=envelope({
                    "context": {"slot": 102},
                    "value": [
                        wallet_account(WALLET_TOKEN, state="frozen", amount="7"),
                        wallet_account(WALLET_TOKEN_2, state="initialized", amount=9007199254740993),
                    ],
                }),
            )
        raise AssertionError(method)

    reader = reader_for(handler)
    try:
        snapshot = reader.snapshot(MINT, WALLET, [LARGEST_EXCLUDED])
    finally:
        reader.close()

    assert snapshot["mint"] == MINT
    assert isinstance(snapshot["observed_at"], float)
    assert isinstance(snapshot["data_age_seconds"], float)
    assert snapshot["data_age_seconds"] >= 0.0
    assert snapshot["complete"] is True
    assert snapshot["program"] == TOKEN_PROGRAM_ID
    assert snapshot["mint_authority"] == AUTHORITY
    assert snapshot["freeze_authority"] is None
    assert snapshot["extensions"] == ["mintCloseAuthority"]
    assert snapshot["unknown_extensions"] is False
    assert snapshot["supply_raw"] == "9007199254740993"
    assert snapshot["decimals"] == 6
    assert snapshot["largest_accounts"] == [
        {"address": LARGEST_EXCLUDED, "amount_raw": "12"},
        {"address": LARGEST_INCLUDED, "amount_raw": "9007199254740993"},
    ]
    assert snapshot["excluded_accounts"] == [LARGEST_EXCLUDED]
    assert snapshot["wallet_balance_raw"] == "9007199254741000"
    assert snapshot["wallet_frozen_accounts"] == [WALLET_TOKEN]
    assert snapshot["slots"] == {
        "getAccountInfo": 100,
        "getTokenLargestAccounts": 101,
        "getTokenAccountsByOwner": 102,
    }


def test_snapshot_missing_authorities_and_null_account_are_incomplete():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            info = {"supply": "10", "decimals": 0}
            return httpx.Response(200, json=envelope(mint_result(info=info)))
        return httpx.Response(200, json=envelope(largest_result(values=[])))

    reader = reader_for(handler)
    try:
        missing = reader.snapshot(MINT)
    finally:
        reader.close()
    assert missing["complete"] is False
    assert missing["mint_authority"] is None
    assert missing["freeze_authority"] is None
    assert missing["supply_raw"] == "10"

    def null_handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(200, json=envelope({"context": {"slot": 77}, "value": None}))
        return httpx.Response(200, json=envelope(largest_result(values=[])))

    reader = reader_for(null_handler)
    try:
        null_snapshot = reader.snapshot(MINT)
    finally:
        reader.close()
    assert null_snapshot["complete"] is False
    assert null_snapshot["slots"]["getAccountInfo"] == 77
    assert null_snapshot["supply_raw"] == "0"
    assert calls == 2


def test_snapshot_records_partial_largest_failure_and_validates_slots():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(200, json=envelope(mint_result()))
        return httpx.Response(200, json=rpc_error())

    reader = reader_for(handler)
    try:
        snapshot = reader.snapshot(MINT)
    finally:
        reader.close()
    assert snapshot["complete"] is False
    assert snapshot["largest_accounts"] == []
    assert snapshot["slots"] == {"getAccountInfo": 100}
    assert snapshot["errors"]


def test_wallet_zero_is_distinct_from_unknown_and_owner_mismatch_is_rejected():
    def zero_handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(200, json=envelope(mint_result()))
        if method == "getTokenLargestAccounts":
            return httpx.Response(200, json=envelope(largest_result(values=[])))
        return httpx.Response(200, json=envelope({"context": {"slot": 3}, "value": []}))

    reader = reader_for(zero_handler)
    try:
        zero = reader.snapshot(MINT, WALLET)
    finally:
        reader.close()
    assert zero["complete"] is True
    assert zero["wallet_balance_raw"] == "0"

    def unknown_handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(200, json=envelope(mint_result()))
        if method == "getTokenLargestAccounts":
            return httpx.Response(200, json=envelope(largest_result(values=[])))
        return httpx.Response(200, json=rpc_error())

    reader = reader_for(unknown_handler)
    try:
        unknown = reader.snapshot(MINT, WALLET)
    finally:
        reader.close()
    assert unknown["complete"] is False
    assert unknown["wallet_balance_raw"] is None

    def mismatch_handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(200, json=envelope(mint_result()))
        if method == "getTokenLargestAccounts":
            return httpx.Response(200, json=envelope(largest_result(values=[])))
        return httpx.Response(
            200,
            json=envelope({
                "context": {"slot": 4},
                "value": [wallet_account(WALLET_TOKEN, owner=OTHER_WALLET, amount="99")],
            }),
        )

    reader = reader_for(mismatch_handler)
    try:
        mismatch = reader.snapshot(MINT, WALLET)
    finally:
        reader.close()
    assert mismatch["complete"] is False
    assert mismatch["wallet_balance_raw"] is None


def test_unknown_and_token2022_extensions_are_reported_without_inventing_authorities():
    info = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "supply": 11,
        "decimals": 0,
        "extensions": [
            {"extension": "pausable", "state": {"paused": False}},
            {"extension": "defaultAccountState", "state": {"state": "frozen"}},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(
                200,
                json=envelope(mint_result(owner=TOKEN_2022_PROGRAM_ID, program="spl-token-2022", info=info)),
            )
        return httpx.Response(200, json=envelope(largest_result(values=[])))

    reader = reader_for(handler)
    try:
        snapshot = reader.snapshot(MINT)
    finally:
        reader.close()
    assert snapshot["complete"] is True
    assert snapshot["program"] == TOKEN_2022_PROGRAM_ID
    assert snapshot["extensions"] == ["pausable", "defaultAccountState"]
    assert snapshot["unknown_extensions"] is True
    assert snapshot["mint_authority"] is None
    assert snapshot["freeze_authority"] is None


def test_boolean_amounts_and_missing_wallet_state_are_malformed():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "getAccountInfo":
            return httpx.Response(200, json=envelope(mint_result()))
        if method == "getTokenLargestAccounts":
            return httpx.Response(
                200,
                json=envelope(largest_result(values=[{"address": LARGEST_INCLUDED, "amount": True}])),
            )
        return httpx.Response(
            200,
            json=envelope({
                "context": {"slot": 5},
                "value": [wallet_account(WALLET_TOKEN, amount="1", state="unknown")],
            }),
        )

    reader = reader_for(handler)
    try:
        snapshot = reader.snapshot(MINT, WALLET)
    finally:
        reader.close()
    assert snapshot["complete"] is False
    assert snapshot["largest_accounts"] == []
    assert snapshot["wallet_balance_raw"] is None


def test_malformed_json_is_safe_and_never_includes_endpoint():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    reader = reader_for(handler)
    try:
        with pytest.raises(RpcError) as raised:
            reader.call("getAccountInfo", [MINT])
    finally:
        reader.close()
    assert "rpc.example.invalid" not in str(raised.value)
    assert "not-json" not in str(raised.value)


def test_call_rejects_mismatched_response_id():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"jsonrpc": "2.0", "id": 999,
                                           "result": {"value": [], "context": {"slot": 1}}})))
    reader = SolanaReader("https://rpc.example.invalid", client=client)
    try:
        with pytest.raises(RpcError):
            reader.call("getTokenLargestAccounts", [MINT])
    finally:
        reader.close()


def test_rejects_unbounded_retries():
    with pytest.raises(RpcError):
        SolanaReader("https://rpc.example.invalid", max_retries=1000)


def test_more_than_twenty_largest_accounts_fails_closed():
    def handler(request):
        method = json.loads(request.content)["method"]
        result = mint_result() if method == "getAccountInfo" else largest_result(
            values=[{"address": pubkey(i), "amount": "1"} for i in range(1, 22)])
        return httpx.Response(200, json=envelope(result))
    reader = reader_for(handler)
    try:
        assert reader.snapshot(MINT)["complete"] is False
    finally:
        reader.close()


def test_unhashable_program_owner_is_incomplete_not_crash():
    def handler(request):
        method = json.loads(request.content)["method"]
        result = mint_result(owner=["malformed"]) if method == "getAccountInfo" else largest_result(values=[])
        return httpx.Response(200, json=envelope(result))
    reader = reader_for(handler)
    try:
        snapshot = reader.snapshot(MINT)
        assert snapshot["complete"] is False
        assert snapshot["program"] is None
    finally:
        reader.close()
