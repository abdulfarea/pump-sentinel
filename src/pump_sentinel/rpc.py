"""Read-only Solana JSON-RPC collection helpers.

This module intentionally contains no signing, transaction-building, or trade
functionality.  All errors exposed by the public API are deliberately generic
and in Portuguese so that response bodies and endpoint credentials cannot leak
through exception text.
"""

from __future__ import annotations

import math
import random
import time
from urllib.parse import urlsplit

import httpx


TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
TOKEN_PROGRAM_IDS = frozenset({TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID})

_ALLOWED_METHODS = frozenset(
    {
        "getAccountInfo",
        "getTokenLargestAccounts",
        "getTokenAccountsByOwner",
    }
)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_VALUES = {character: index for index, character in enumerate(_BASE58_ALPHABET)}
_RECOGNIZED_EXTENSIONS = frozenset(
    {
        "pausable",
        "scaledUiAmount",
        "confidentialMintBurn",
        "confidentialTransferMint",
        "confidentialTransferFeeConfig",
        "mintCloseAuthority",
    }
)


class RpcError(Exception):
    """Safe, user-facing error raised by the RPC collector."""


def validate_pubkey(value: str) -> str:
    """Validate that *value* is base58 encoding of exactly 32 bytes.

    Curve membership is intentionally not checked.  Solana account addresses
    are encoded byte strings here, and this helper is also used for safe shape
    validation of RPC fields.
    """

    if not isinstance(value, str) or not 32 <= len(value) <= 44:
        raise RpcError("Chave pública inválida.")

    number = 0
    for character in value:
        digit = _BASE58_VALUES.get(character)
        if digit is None:
            raise RpcError("Chave pública inválida.")
        number = number * 58 + digit

    leading_zeroes = len(value) - len(value.lstrip("1"))
    if number:
        byte_length = (number.bit_length() + 7) // 8
        decoded = number.to_bytes(byte_length, "big")
    else:
        decoded = b""
    decoded = b"\x00" * leading_zeroes + decoded
    if len(decoded) != 32:
        raise RpcError("Chave pública inválida.")
    return value


class _MalformedResponse(Exception):
    """Internal marker for a structurally unsafe RPC result."""


class SolanaReader:
    """Small, read-only Solana JSON-RPC client."""

    def __init__(
        self,
        rpc_url: str,
        timeout_seconds: float = 10,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self._validate_rpc_url(rpc_url)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
        ):
            raise RpcError("Tempo limite inválido.")
        if (isinstance(max_retries, bool) or not isinstance(max_retries, int)
                or not 0 <= max_retries <= 5):
            raise RpcError("Número de tentativas inválido.")

        self.rpc_url = rpc_url
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = max_retries
        self._client = client if client is not None else httpx.Client(timeout=self.timeout_seconds)
        self._closed = False
        self._request_id = 0

    @staticmethod
    def _validate_rpc_url(rpc_url: str) -> None:
        if not isinstance(rpc_url, str) or not rpc_url:
            raise RpcError("URL RPC inválida.")
        try:
            parsed = urlsplit(rpc_url)
            scheme = parsed.scheme.lower()
            hostname = parsed.hostname
            # Accessing .port catches malformed port syntax without echoing the URL.
            _ = parsed.port
        except (TypeError, ValueError):
            raise RpcError("URL RPC inválida.") from None

        if scheme not in {"https", "http"} or not parsed.netloc or not hostname:
            raise RpcError("URL RPC inválida.")
        if scheme == "http" and hostname.lower() not in {"localhost", "127.0.0.1"}:
            raise RpcError("A URL RPC deve usar HTTPS.")

    def close(self) -> None:
        """Close the underlying HTTP client; safe to call more than once."""

        if not self._closed:
            self._closed = True
            try:
                self._client.close()
            except Exception:
                # Closing must not expose a transport URL or implementation detail.
                raise RpcError("Falha ao fechar o cliente RPC.") from None

    def call(self, method: str, params: list) -> dict:
        """Call one of the explicitly allowlisted read-only RPC methods."""

        if method not in _ALLOWED_METHODS:
            raise RpcError("Método RPC não permitido.")
        if not isinstance(params, list):
            raise RpcError("Parâmetros RPC inválidos.")
        if self._closed:
            raise RpcError("Cliente RPC fechado.")

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    self.rpc_url,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException:
                if attempt >= self.max_retries:
                    raise RpcError("Tempo limite ao consultar o nó Solana.") from None
                self._retry_sleep(attempt)
                continue
            except httpx.RequestError:
                if attempt >= self.max_retries:
                    raise RpcError("Falha de rede ao consultar o nó Solana.") from None
                self._retry_sleep(attempt)
                continue
            except (TypeError, ValueError):
                raise RpcError("Parâmetros RPC inválidos.") from None
            except Exception:
                # A custom transport may throw a non-httpx network exception.  Do
                # not pass its text through because it can contain the URL.
                raise RpcError("Falha ao consultar o nó Solana.") from None

            status = response.status_code
            if status == 429 or 500 <= status <= 599:
                if attempt >= self.max_retries:
                    raise RpcError("Falha temporária do nó Solana.")
                self._retry_sleep(attempt)
                continue
            if status < 200 or status >= 300:
                raise RpcError("Resposta HTTP inválida do nó Solana.")

            try:
                envelope = response.json()
            except (TypeError, ValueError):
                raise RpcError("Resposta JSON inválida do nó Solana.") from None
            if not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0":
                raise RpcError("Resposta JSON-RPC inválida.")
            if (isinstance(envelope.get("id"), bool)
                    or envelope.get("id") != payload["id"]):
                raise RpcError("Identificador da resposta RPC inconsistente.")
            if envelope.get("error") is not None or "result" not in envelope:
                raise RpcError("Erro retornado pelo nó Solana.")
            result = envelope.get("result")
            if not isinstance(result, dict):
                raise RpcError("Resultado RPC inválido.")
            return result

        # The loop always returns or raises; this keeps static type checkers happy.
        raise RpcError("Falha ao consultar o nó Solana.")

    @staticmethod
    def _retry_sleep(attempt: int) -> None:
        # A small bounded delay avoids hammering a provider while remaining easy
        # for callers/tests to monkeypatch.  Jitter is intentionally tiny.
        delay = min(1.0, 0.10 * (2**attempt))
        delay = min(1.0, delay + random.uniform(0.0, 0.05))
        time.sleep(delay)

    def snapshot(
        self,
        mint: str,
        wallet: str | None = None,
        excluded_accounts: list[str] | None = None,
    ) -> dict:
        """Collect a bounded mint/holder snapshot without changing chain state."""

        observed_at = float(time.time())
        excluded_output = list(excluded_accounts) if isinstance(excluded_accounts, list) else []
        snapshot = {
            "mint": mint if isinstance(mint, str) else "",
            "observed_at": observed_at,
            "data_age_seconds": 0.0,
            "complete": True,
            "errors": [],
            "program": None,
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "unknown_extensions": False,
            "supply_raw": "0",
            "decimals": 0,
            "largest_accounts": [],
            "excluded_accounts": excluded_output,
            "wallet_balance_raw": None,
            "wallet_frozen_accounts": [],
            "slots": {},
        }
        errors: list[str] = snapshot["errors"]

        def fail(message: str) -> None:
            snapshot["complete"] = False
            errors.append(message)

        mint_valid = True
        try:
            validate_pubkey(mint)
        except RpcError:
            mint_valid = False
            fail("Mint inválida.")

        excluded_set: set[str] = set()
        if excluded_accounts is not None and not isinstance(excluded_accounts, list):
            fail("Lista de contas excluídas inválida.")
        else:
            for account in excluded_output:
                try:
                    validate_pubkey(account)
                except RpcError:
                    fail("Conta excluída inválida.")
                else:
                    excluded_set.add(account)

        wallet_valid = wallet is None
        if wallet is not None:
            try:
                validate_pubkey(wallet)
            except RpcError:
                wallet_valid = False
                fail("Carteira inválida.")
            else:
                wallet_valid = True

        if not mint_valid:
            return snapshot

        # Mint account metadata.
        try:
            result = self.call(
                "getAccountInfo",
                [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            )
        except RpcError:
            fail("Falha ao consultar informações da mint.")
        else:
            mint_malformed = False
            try:
                slot = self._context_slot(result)
                snapshot["slots"]["getAccountInfo"] = slot
            except _MalformedResponse:
                mint_malformed = True

            value = result.get("value")
            if not isinstance(value, dict):
                mint_malformed = True
            else:
                owner = value.get("owner")
                if not isinstance(owner, str) or owner not in TOKEN_PROGRAM_IDS:
                    mint_malformed = True
                else:
                    # The parsed `program` label is usually `spl-token`, while
                    # downstream policy needs the canonical program address.
                    snapshot["program"] = owner
                data = value.get("data")
                if not isinstance(data, dict):
                    mint_malformed = True
                else:
                    parsed = data.get("parsed")
                    if not isinstance(parsed, dict) or parsed.get("type") != "mint":
                        mint_malformed = True
                    else:
                        info = parsed.get("info")
                        if not isinstance(info, dict):
                            mint_malformed = True
                        else:
                            for key, output_key in (
                                ("mintAuthority", "mint_authority"),
                                ("freezeAuthority", "freeze_authority"),
                            ):
                                if key not in info:
                                    # Do not turn an absent field into a false null.
                                    mint_malformed = True
                                    continue
                                authority = info[key]
                                if authority is None:
                                    snapshot[output_key] = None
                                elif isinstance(authority, str):
                                    try:
                                        validate_pubkey(authority)
                                    except RpcError:
                                        mint_malformed = True
                                    else:
                                        snapshot[output_key] = authority
                                else:
                                    mint_malformed = True

                            if "supply" not in info:
                                mint_malformed = True
                            else:
                                try:
                                    snapshot["supply_raw"] = self._decimal_raw(info["supply"])
                                except _MalformedResponse:
                                    mint_malformed = True

                            if "decimals" not in info:
                                mint_malformed = True
                            else:
                                try:
                                    snapshot["decimals"] = self._nonnegative_int(info["decimals"])
                                except _MalformedResponse:
                                    mint_malformed = True

                            extension_malformed = self._read_extensions(info, snapshot)
                            mint_malformed = mint_malformed or extension_malformed
            if mint_malformed:
                fail("Resposta de informações da mint malformada.")

        # Largest token accounts.
        try:
            result = self.call(
                "getTokenLargestAccounts",
                [mint, {"commitment": "confirmed"}],
            )
        except RpcError:
            fail("Falha ao consultar as maiores contas.")
        else:
            largest_malformed = False
            try:
                snapshot["slots"]["getTokenLargestAccounts"] = self._context_slot(result)
            except _MalformedResponse:
                largest_malformed = True

            values = result.get("value")
            if not isinstance(values, list) or len(values) > 20:
                largest_malformed = True
            else:
                for account in values:
                    if not isinstance(account, dict):
                        largest_malformed = True
                        continue
                    address = account.get("address")
                    amount = account.get("amount")
                    try:
                        validate_pubkey(address)
                        amount_raw = self._decimal_raw(amount)
                    except (RpcError, _MalformedResponse):
                        largest_malformed = True
                        continue
                    snapshot["largest_accounts"].append(
                        {"address": address, "amount_raw": amount_raw}
                    )
            if largest_malformed:
                fail("Resposta de maiores contas malformada.")

        # Wallet token accounts.  An empty, valid list is a known zero balance;
        # any malformed/mismatched item makes the aggregate unknown instead.
        if wallet is not None and wallet_valid:
            wallet_malformed = False
            wallet_total = 0
            frozen_accounts: list[str] = []
            try:
                result = self.call(
                    "getTokenAccountsByOwner",
                    [
                        wallet,
                        {"mint": mint},
                        {"encoding": "jsonParsed", "commitment": "confirmed"},
                    ],
                )
            except RpcError:
                fail("Falha ao consultar o saldo da carteira.")
            else:
                try:
                    snapshot["slots"]["getTokenAccountsByOwner"] = self._context_slot(result)
                except _MalformedResponse:
                    wallet_malformed = True

                values = result.get("value")
                if not isinstance(values, list):
                    wallet_malformed = True
                else:
                    for account in values:
                        if not isinstance(account, dict):
                            wallet_malformed = True
                            continue
                        try:
                            account_address = account.get("pubkey", account.get("address"))
                            validate_pubkey(account_address)
                            account_data = account.get("account")
                            if not isinstance(account_data, dict):
                                raise _MalformedResponse

                            account_owner = account_data.get("owner")
                            if account_owner not in TOKEN_PROGRAM_IDS:
                                raise _MalformedResponse
                            data = account_data.get("data")
                            if not isinstance(data, dict):
                                raise _MalformedResponse
                            parsed = data.get("parsed")
                            if not isinstance(parsed, dict) or parsed.get("type") != "account":
                                raise _MalformedResponse
                            info = parsed.get("info")
                            if not isinstance(info, dict):
                                raise _MalformedResponse

                            account_mint = info.get("mint")
                            if not isinstance(account_mint, str) or account_mint != mint:
                                raise _MalformedResponse
                            parsed_owner = info.get("owner")
                            if not isinstance(parsed_owner, str) or parsed_owner != wallet:
                                raise _MalformedResponse
                            validate_pubkey(parsed_owner)

                            state = info.get("state")
                            if state not in {"initialized", "frozen"}:
                                raise _MalformedResponse
                            token_amount = info.get("tokenAmount")
                            if not isinstance(token_amount, dict):
                                raise _MalformedResponse
                            amount_raw = self._decimal_raw(token_amount.get("amount"))
                            wallet_total += int(amount_raw)
                            if state == "frozen":
                                frozen_accounts.append(account_address)
                        except (RpcError, _MalformedResponse, TypeError, ValueError):
                            wallet_malformed = True
                            continue

                if wallet_malformed:
                    snapshot["wallet_balance_raw"] = None
                    snapshot["wallet_frozen_accounts"] = []
                    fail("Resposta de saldo da carteira malformada.")
                else:
                    snapshot["wallet_balance_raw"] = str(wallet_total)
                    snapshot["wallet_frozen_accounts"] = frozen_accounts

        snapshot["data_age_seconds"] = max(0.0, float(time.time()) - observed_at)
        return snapshot

    @staticmethod
    def _context_slot(result: object) -> int:
        if not isinstance(result, dict):
            raise _MalformedResponse
        context = result.get("context")
        if not isinstance(context, dict):
            raise _MalformedResponse
        slot = context.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
            raise _MalformedResponse
        return slot

    @staticmethod
    def _decimal_raw(value: object) -> str:
        if isinstance(value, bool):
            raise _MalformedResponse
        if isinstance(value, int):
            if value < 0:
                raise _MalformedResponse
            return str(value)
        if isinstance(value, str) and value and all("0" <= char <= "9" for char in value):
            return value
        raise _MalformedResponse

    @staticmethod
    def _nonnegative_int(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _MalformedResponse
        return value

    @staticmethod
    def _read_extensions(info: dict, snapshot: dict) -> bool:
        extensions = info.get("extensions")
        if extensions is None:
            return False
        if not isinstance(extensions, list):
            snapshot["unknown_extensions"] = True
            return True

        malformed = False
        names: list[str] = snapshot["extensions"]
        for extension in extensions:
            if not isinstance(extension, dict):
                snapshot["unknown_extensions"] = True
                malformed = True
                continue
            name = extension.get("extension")
            if not isinstance(name, str) or not name:
                snapshot["unknown_extensions"] = True
                malformed = True
                continue
            names.append(name)
            if "state" not in extension:
                snapshot["unknown_extensions"] = True
                malformed = True
            if name not in _RECOGNIZED_EXTENSIONS:
                snapshot["unknown_extensions"] = True
        return malformed
