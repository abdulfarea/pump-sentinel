"""Configuração sem credenciais, validada antes de qualquer requisição."""
from __future__ import annotations

import math
from pathlib import Path
import tomllib

from .rpc import RpcError, validate_pubkey


class ConfigError(ValueError):
    pass


def _pubkey(value: str) -> str:
    try:
        return validate_pubkey(value)
    except RpcError:
        raise ConfigError("Endereço público inválido; nomes e símbolos não são endereços.") from None


def _number(value: object, low: float, high: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} deve ser numérico.")
    if not math.isfinite(value) or not low <= value <= high:
        raise ConfigError(f"{label} fora dos limites permitidos.")
    return float(value)


def _integer(value: object, low: int, high: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"{label} deve ser inteiro entre {low} e {high}.")
    return value


def load_config(path: str | Path) -> dict:
    file = Path(path).expanduser().resolve()
    try:
        if file.stat().st_size > 65536:
            raise ConfigError("Arquivo de configuração muito grande.")
        with file.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("Não foi possível ler a configuração TOML.") from exc
    allowed = {"wallet", "mints", "interval_seconds", "max_cycles", "state_path",
               "kill_switch_path", "max_history", "excluded_accounts", "policy"}
    if set(config) - allowed:
        raise ConfigError("Há campos desconhecidos na configuração; não inclua credenciais.")
    wallet = config.get("wallet", "")
    if not isinstance(wallet, str):
        raise ConfigError("wallet deve conter somente o endereço público.")
    if wallet:
        _pubkey(wallet)
    mints = config.get("mints", [])
    excluded = config.get("excluded_accounts", [])
    for items, label, limit in [(mints, "mints", 20), (excluded, "excluded_accounts", 200)]:
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ConfigError(f"{label} deve ser uma lista de endereços públicos.")
        if len(items) > limit or len(set(items)) != len(items):
            raise ConfigError(f"{label} contém duplicatas ou excede {limit} entradas.")
        for item in items:
            _pubkey(item)
    if not mints:
        raise ConfigError("Informe pelo menos um mint verificado em config.toml.")
    policy = config.get("policy", {})
    if not isinstance(policy, dict):
        raise ConfigError("policy deve ser uma seção TOML.")
    defaults = {"max_single_account_pct": 20.0, "max_top10_accounts_pct": 60.0,
                "max_data_age_seconds": 120.0, "max_slot_skew": 150}
    if set(policy) - set(defaults):
        raise ConfigError("Há parâmetros de risco desconhecidos.")
    defaults.update(policy)
    for key in ("max_single_account_pct", "max_top10_accounts_pct"):
        defaults[key] = _number(defaults[key], 0.1, 100, key)
    defaults["max_data_age_seconds"] = _number(defaults["max_data_age_seconds"], 5, 3600,
                                                 "max_data_age_seconds")
    defaults["max_slot_skew"] = _integer(defaults["max_slot_skew"], 0, 10000, "max_slot_skew")
    result = dict(config)
    result.update(wallet=wallet, mints=mints, excluded_accounts=excluded, policy=defaults)
    result["interval_seconds"] = _number(config.get("interval_seconds", 60), 30, 3600,
                                         "interval_seconds")
    result["max_cycles"] = _integer(config.get("max_cycles", 0), 0, 1000000, "max_cycles")
    result["max_history"] = _integer(config.get("max_history", 10000), 100, 1000000,
                                      "max_history")
    for key, default in [("state_path", "./data/sentinel.sqlite3"),
                         ("kill_switch_path", "./PAUSE")]:
        value = config.get(key, default)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ConfigError(f"{key} deve ser um caminho local válido.")
        result[key] = str((file.parent / Path(value).expanduser()).resolve())
    return result
