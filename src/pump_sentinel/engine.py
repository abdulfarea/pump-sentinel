"""Motor heurístico, somente leitura, para snapshots de tokens Pump.fun.

O módulo não faz chamadas de rede, não assina transações e não executa ordens.
Todos os valores de quantidade são tratados como inteiros decimais para evitar
perda de precisão em valores que excedem o limite de inteiros exatos do float.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
import math
import re
import time
from typing import Any


CLASSIC_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
KNOWN_PROGRAMS = frozenset({CLASSIC_TOKEN_PROGRAM, TOKEN_2022_PROGRAM})

DEFAULT_POLICY: dict[str, float] = {
    "max_single_account_pct": 20.0,
    "max_top10_accounts_pct": 60.0,
    "max_data_age_seconds": 120.0,
    "max_slot_skew": 150.0,
}

# Pequena tolerância para relógios distribuídos; além dela, um timestamp futuro
# é tratado como não confiável. A idade observada continua sendo calculada a
# partir de observed_at mesmo quando o RPC fornece data_age_seconds.
FUTURE_CLOCK_TOLERANCE_SECONDS = 5.0

# Names emitted by the Token-2022 extension registry.  This list is
# intentionally explicit: an extension absent from it is not silently ignored.
KNOWN_TOKEN_2022_EXTENSIONS = frozenset(
    {
        "transferFeeConfig",
        "transferHook",
        "permanentDelegate",
        "nonTransferable",
        "defaultAccountState",
        "metadataPointer",
        "tokenMetadata",
        "groupPointer",
        "groupMemberPointer",
        "interestBearingConfig",
        "confidentialTransferMint",
        "confidentialTransferAccount",
        "cpiGuard",
        "memoTransfer",
        "immutableOwner",
        "transferFeeAmount",
        "mintCloseAuthority",
        "pausable",
        "pausableAccount",
        "scaledUiAmount",
        "confidentialMintBurn",
        "confidentialTransferFeeConfig",
        "confidentialTransferExtension",
        "transferHookAccount",
        "transferFeeConfigAccount",
    }
)

FLAGGED_TOKEN_2022_EXTENSIONS = frozenset(
    {
        "transferFeeConfig",
        "transferHook",
        "permanentDelegate",
        "nonTransferable",
        "defaultAccountState",
        "mintCloseAuthority",
        "pausable",
        "pausableAccount",
        "confidentialMintBurn",
        "confidentialTransferMint",
        "confidentialTransferAccount",
        "confidentialTransferFeeConfig",
        "confidentialTransferExtension",
    }
)

_INTEGER_RE = re.compile(r"^[0-9]+$")
_SEVERITIES = frozenset({"INFO", "WARNING", "HIGH", "CRITICAL"})


# The return value is deliberately a plain dict so callers need only the
# Python standard library.
def _finding(
    code: str,
    severity: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity if severity in _SEVERITIES else "CRITICAL",
        "message": message,
        "evidence": evidence or {},
    }


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _parse_nonnegative_integer(value: Any) -> int | None:
    """Parse only a decimal string containing a nonnegative integer."""
    if not isinstance(value, str) or _INTEGER_RE.fullmatch(value) is None:
        return None
    try:
        return int(value, 10)
    except (TypeError, ValueError, OverflowError):
        return None


def _decimal_string(raw: int, decimals: int) -> str:
    # Decimal is used even though raw is already an int: the conversion from a
    # raw integer to UI units must not pass through binary floating point.
    with localcontext() as context:
        context.prec = max(50, len(str(raw)) + decimals + 4)
        value = Decimal(raw).scaleb(-decimals)
        rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _safe_snapshot(snapshot: Any) -> dict[str, Any]:
    return snapshot if isinstance(snapshot, dict) else {}


def _policy_values(policy: Any) -> tuple[dict[str, float], list[dict[str, Any]]]:
    values = dict(DEFAULT_POLICY)
    findings: list[dict[str, Any]] = []
    if policy is None:
        return values, findings
    if not isinstance(policy, dict):
        findings.append(
            _finding(
                "MALFORMED_POLICY",
                "CRITICAL",
                "A política fornecida não é um objeto válido; os limites não são confiáveis.",
                {"tipo": type(policy).__name__},
            )
        )
        return values, findings

    for key in DEFAULT_POLICY:
        if key not in policy:
            continue
        candidate = policy[key]
        if not _is_finite_number(candidate) or float(candidate) < 0:
            findings.append(
                _finding(
                    "MALFORMED_POLICY",
                    "CRITICAL",
                    f"O limite {key} é inválido; a análise foi interrompida de forma conservadora.",
                    {"campo": key, "valor": candidate},
                )
            )
            continue
        values[key] = float(candidate)
    return values, findings


def _base_output(snapshot: dict[str, Any]) -> dict[str, Any]:
    mint = snapshot.get("mint")
    observed_at = snapshot.get("observed_at")
    if not isinstance(mint, str):
        mint = ""
    if not _is_finite_number(observed_at):
        observed_at = None
    else:
        observed_at = float(observed_at)
    return {
        "mint": mint,
        "observed_at": observed_at,
        "heuristic_score": 0,
        "posture": "PAUSE",
        "pause_new_actions": True,
        "findings": [],
        "metrics": {
            "largest_account_pct": None,
            "top10_accounts_pct": None,
            "wallet_balance_ui": None,
            "wallet_delta_raw": None,
        },
        "limitations": [
            "A pontuação é heurística, não tem validade estatística e não prevê o comportamento futuro do ativo.",
            "Timestamps futuros têm tolerância de apenas 5 segundos; a idade local é derivada de observed_at e não é substituída pela idade informada pelo RPC.",
            "Contas maiores não equivalem a proprietários beneficiários; pools e custódias não são identificados automaticamente.",
            "As exclusões configuradas não são removidas do denominador da concentração.",
            "A análise é somente leitura; não simula venda, execução, liquidez, slippage ou alterações de estado.",
            "Uma lista de achados vazia não constitui garantia de segurança.",
        ],
    }


def analyze_snapshot(snapshot: dict, policy: dict | None = None) -> dict:
    """Analisa um snapshot local e retorna um sinal advisory fail-closed.

    A função nunca envia transações ou acessa serviços externos. Snapshots
    incompletos, inválidos, futuros, antigos ou de programa/extensão não
    reconhecidos resultam em ``PAUSE`` e ``pause_new_actions=True``.
    """
    source = _safe_snapshot(snapshot)
    result = _base_output(source)
    findings: list[dict[str, Any]] = []
    policy_values, policy_findings = _policy_values(policy)
    findings.extend(policy_findings)

    required_fields = (
        "mint",
        "observed_at",
        "complete",
        "errors",
        "program",
        "mint_authority",
        "freeze_authority",
        "extensions",
        "unknown_extensions",
        "supply_raw",
        "decimals",
        "largest_accounts",
        "excluded_accounts",
        "wallet_balance_raw",
        "slots",
    )
    missing = [field for field in required_fields if field not in source]
    if missing:
        findings.append(
            _finding(
                "MALFORMED_SNAPSHOT",
                "CRITICAL",
                "O snapshot não contém todos os campos obrigatórios; novas ações devem permanecer pausadas.",
                {"campos_ausentes": missing},
            )
        )

    # Basic scalar validation.
    mint = source.get("mint")
    if not isinstance(mint, str) or not mint:
        findings.append(
            _finding(
                "MALFORMED_MINT",
                "CRITICAL",
                "O identificador mint está ausente ou malformado.",
                {"tipo": type(mint).__name__},
            )
        )

    observed_at = source.get("observed_at")
    observed_at_valid = _is_finite_number(observed_at)
    observed_at_float = float(observed_at) if observed_at_valid else None
    now = time.time()
    observed_age: float | None = None
    if not observed_at_valid:
        findings.append(
            _finding(
                "MALFORMED_TIMESTAMP",
                "CRITICAL",
                "O horário de observação não é um número finito.",
                {"valor": observed_at},
            )
        )
    else:
        observed_age = max(0.0, now - observed_at_float)
        if observed_at_float > now + FUTURE_CLOCK_TOLERANCE_SECONDS:
            findings.append(
                _finding(
                    "FUTURE_TIMESTAMP",
                    "CRITICAL",
                    "O horário de observação está além da tolerância do relógio; os dados não podem ser confiados.",
                    {
                        "observed_at": observed_at_float,
                        "agora": now,
                        "tolerancia_segundos": FUTURE_CLOCK_TOLERANCE_SECONDS,
                    },
                )
            )

    complete = source.get("complete")
    if not isinstance(complete, bool):
        findings.append(
            _finding(
                "MALFORMED_COMPLETE",
                "CRITICAL",
                "O indicador de completude do snapshot está malformado.",
                {"valor": complete},
            )
        )
    elif not complete:
        findings.append(
            _finding(
                "INCOMPLETE_SNAPSHOT",
                "CRITICAL",
                "O snapshot foi marcado como incompleto; a análise não autoriza novas ações.",
                {},
            )
        )

    errors = source.get("errors")
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        findings.append(
            _finding(
                "MALFORMED_ERRORS",
                "CRITICAL",
                "A lista de erros do snapshot está malformada.",
                {"tipo": type(errors).__name__},
            )
        )
    elif errors:
        findings.append(
            _finding(
                "SNAPSHOT_ERRORS",
                "CRITICAL",
                "O snapshot reporta erros de coleta; os dados não são suficientes para prosseguir.",
                {"erros": errors},
            )
        )

    program = source.get("program")
    program_known = isinstance(program, str) and program in KNOWN_PROGRAMS
    if not isinstance(program, str) or not program_known:
        findings.append(
            _finding(
                "UNKNOWN_PROGRAM",
                "CRITICAL",
                "O programa do token é ausente ou não reconhecido; a análise foi pausada.",
                {"program": program, "programas_conhecidos": sorted(KNOWN_PROGRAMS)},
            )
        )

    for authority_field, label in (
        ("mint_authority", "mint"),
        ("freeze_authority", "freeze"),
    ):
        authority = source.get(authority_field)
        if authority is not None and (not isinstance(authority, str) or not authority):
            findings.append(
                _finding(
                    "MALFORMED_AUTHORITY",
                    "CRITICAL",
                    f"A autoridade de {label} está malformada.",
                    {"campo": authority_field},
                )
            )
        elif isinstance(authority, str) and authority:
            findings.append(
                _finding(
                    f"{label.upper()}_AUTHORITY_PRESENT",
                    "CRITICAL",
                    f"A autoridade de {label} ainda está definida; ela pode alterar o comportamento do token.",
                    {"campo": authority_field, "authority": authority},
                )
            )

    decimals = source.get("decimals")
    decimals_valid = isinstance(decimals, int) and not isinstance(decimals, bool) and 0 <= decimals <= 255
    if not decimals_valid:
        findings.append(
            _finding(
                "MALFORMED_DECIMALS",
                "CRITICAL",
                "O número de casas decimais está malformado.",
                {"valor": decimals},
            )
        )
        decimals_int = 0
    else:
        decimals_int = decimals

    supply = _parse_nonnegative_integer(source.get("supply_raw"))
    if supply is None:
        findings.append(
            _finding(
                "MALFORMED_SUPPLY",
                "CRITICAL",
                "O supply bruto não é uma string de inteiro não negativo.",
                {"valor": source.get("supply_raw")},
            )
        )
    elif supply == 0:
        findings.append(
            _finding(
                "ZERO_SUPPLY",
                "CRITICAL",
                "O supply bruto é zero; percentuais de concentração são indefinidos.",
                {"supply_raw": source.get("supply_raw")},
            )
        )

    # Optional age is checked independently from observed_at.  If omitted, the
    # observed timestamp supplies the age, which keeps stale data fail-closed.
    data_age_value = source.get("data_age_seconds")
    reported_data_age: float | None
    if data_age_value is not None and not _is_finite_number(data_age_value):
        findings.append(
            _finding(
                "MALFORMED_DATA_AGE",
                "CRITICAL",
                "A idade dos dados está malformada.",
                {"valor": data_age_value},
            )
        )
        reported_data_age = None
    elif data_age_value is not None and float(data_age_value) < 0:
        findings.append(
            _finding(
                "MALFORMED_DATA_AGE",
                "CRITICAL",
                "A idade dos dados não pode ser negativa.",
                {"valor": data_age_value},
            )
        )
        reported_data_age = None
    elif data_age_value is not None:
        reported_data_age = float(data_age_value)
    else:
        reported_data_age = None

    # Never let an RPC-provided age hide an old observed_at.  The larger of the
    # reported and locally-derived ages is the one used for the stale check.
    if observed_age is not None:
        data_age = max(observed_age, reported_data_age or 0.0)
    else:
        data_age = reported_data_age

    if data_age is not None and data_age > policy_values["max_data_age_seconds"]:
        findings.append(
            _finding(
                "STALE_DATA",
                "CRITICAL",
                "Os dados excedem a idade máxima configurada; novas ações devem permanecer pausadas.",
                {
                    "data_age_seconds": data_age,
                    "max_data_age_seconds": policy_values["max_data_age_seconds"],
                },
            )
        )

    extensions = source.get("extensions")
    extensions_valid = isinstance(extensions, list) and all(
        isinstance(extension, str) and bool(extension) for extension in extensions
    )
    if extensions_valid and len(set(extensions)) != len(extensions):
        extensions_valid = False
    if not extensions_valid:
        findings.append(
            _finding(
                "MALFORMED_EXTENSIONS",
                "CRITICAL",
                "A lista de extensões está malformada ou contém nomes duplicados.",
                {"valor": extensions},
            )
        )
        extensions_list: list[str] = []
    else:
        extensions_list = list(extensions)

    unknown_extensions = source.get("unknown_extensions")
    if not isinstance(unknown_extensions, bool):
        findings.append(
            _finding(
                "MALFORMED_UNKNOWN_EXTENSIONS",
                "CRITICAL",
                "O indicador de extensões desconhecidas está malformado.",
                {"valor": unknown_extensions},
            )
        )
    elif unknown_extensions:
        findings.append(
            _finding(
                "UNKNOWN_EXTENSION",
                "CRITICAL",
                "Há extensões desconhecidas; o comportamento de transferência não foi verificado.",
                {"extensions": extensions_list},
            )
        )

    if program == CLASSIC_TOKEN_PROGRAM and extensions_list:
        findings.append(
            _finding(
                "UNSUPPORTED_CLASSIC_EXTENSIONS",
                "CRITICAL",
                "O programa clássico não deveria declarar extensões Token-2022.",
                {"extensions": extensions_list},
            )
        )
    elif program == TOKEN_2022_PROGRAM and extensions_valid:
        unrecognized = [
            extension
            for extension in extensions_list
            if extension not in KNOWN_TOKEN_2022_EXTENSIONS
        ]
        if unrecognized:
            findings.append(
                _finding(
                    "UNKNOWN_EXTENSION",
                    "CRITICAL",
                    "A extensão Token-2022 não está na lista conhecida; a análise foi pausada.",
                    {"extensions": unrecognized},
                )
            )
        elif extensions_list:
            harmless = [
                extension
                for extension in extensions_list
                if extension not in FLAGGED_TOKEN_2022_EXTENSIONS
            ]
            flagged = [
                extension
                for extension in extensions_list
                if extension in FLAGGED_TOKEN_2022_EXTENSIONS
            ]
            if flagged:
                findings.append(
                    _finding(
                        "TOKEN2022_FLAGGED_EXTENSION",
                        "HIGH",
                        "Extensões Token-2022 podem cobrar taxas, bloquear ou redirecionar transferências; a venda não foi simulada.",
                        {"extensions": flagged},
                    )
                )
            if harmless:
                findings.append(
                    _finding(
                        "TOKEN2022_EXTENSION_CAUTION",
                        "WARNING",
                        "Extensões Token-2022 conhecidas ainda exigem cautela porque a venda não foi simulada.",
                        {"extensions": harmless},
                    )
                )

    # Token-2022 should also fail closed if the caller explicitly says it has
    # no known extension inventory.  The boolean above is the authoritative
    # unknown-extension signal; an absent list was already malformed.

    largest_accounts = source.get("largest_accounts")
    accounts_valid = isinstance(largest_accounts, list)
    parsed_accounts: list[tuple[str, int]] = []
    seen_addresses: set[str] = set()
    if accounts_valid:
        for account in largest_accounts:
            if not isinstance(account, dict):
                accounts_valid = False
                break
            address = account.get("address")
            amount = _parse_nonnegative_integer(account.get("amount_raw"))
            if not isinstance(address, str) or not address or amount is None or address in seen_addresses:
                accounts_valid = False
                break
            seen_addresses.add(address)
            parsed_accounts.append((address, amount))
    if not accounts_valid:
        findings.append(
            _finding(
                "MALFORMED_LARGEST_ACCOUNTS",
                "CRITICAL",
                "A lista de maiores contas está malformada.",
                {},
            )
        )
        parsed_accounts = []
    elif not parsed_accounts:
        findings.append(
            _finding(
                "EMPTY_LARGEST_ACCOUNTS",
                "CRITICAL",
                "Não há contas para avaliar a concentração; novas ações permanecem pausadas.",
                {},
            )
        )

    excluded_accounts = source.get("excluded_accounts")
    excluded_valid = isinstance(excluded_accounts, list) and all(
        isinstance(address, str) and bool(address) for address in excluded_accounts
    )
    if excluded_valid and len(set(excluded_accounts)) != len(excluded_accounts):
        excluded_valid = False
    if not excluded_valid:
        findings.append(
            _finding(
                "MALFORMED_EXCLUDED_ACCOUNTS",
                "CRITICAL",
                "A lista de contas explicitamente excluídas está malformada.",
                {},
            )
        )
        excluded_accounts_list: list[str] = []
    else:
        excluded_accounts_list = list(excluded_accounts)

    if excluded_accounts_list:
        findings.append(_finding(
            "EXCLUDED_ACCOUNTS_CAUTION", "WARNING",
            "Contas foram excluídas manualmente dos alertas de concentração; verifique a justificativa. A concentração bruta continua disponível.",
            {"excluded_accounts": excluded_accounts_list},
        ))

    if supply is not None and parsed_accounts:
        total_largest = sum(amount for _, amount in parsed_accounts)
        if total_largest > supply:
            findings.append(
                _finding(
                    "ACCOUNT_AMOUNT_EXCEEDS_SUPPLY",
                    "CRITICAL",
                    "As maiores contas somam mais que o supply bruto; os dados são inconsistentes.",
                    {"soma_largest_accounts_raw": str(total_largest), "supply_raw": str(supply)},
                )
            )
        raw_amounts = sorted((amount for _, amount in parsed_accounts), reverse=True)
        excluded_set = set(excluded_accounts_list)
        sorted_amounts = sorted((amount for address, amount in parsed_accounts
                                 if address not in excluded_set), reverse=True)
        if not sorted_amounts:
            findings.append(_finding(
                "NO_REVIEWED_ACCOUNTS", "CRITICAL",
                "Todas as contas observadas foram excluídas; a concentração restante é desconhecida.",
            ))
        with localcontext() as context:
            context.prec = max(50, len(str(supply)) + 20)
            if supply > 0:
                result["metrics"]["raw_largest_account_pct"] = float(Decimal(raw_amounts[0]) * 100 / Decimal(supply))
                result["metrics"]["raw_top10_accounts_pct"] = float(Decimal(sum(raw_amounts[:10])) * 100 / Decimal(supply))
            if supply > 0 and sorted_amounts:
                largest_pct = (Decimal(sorted_amounts[0]) * Decimal(100)) / Decimal(supply)
                top10_pct = (Decimal(sum(sorted_amounts[:10])) * Decimal(100)) / Decimal(supply)
                result["metrics"]["largest_account_pct"] = float(largest_pct)
                result["metrics"]["top10_accounts_pct"] = float(top10_pct)
                if largest_pct > Decimal(str(policy_values["max_single_account_pct"])):
                    findings.append(
                        _finding(
                            "SINGLE_ACCOUNT_CONCENTRATION",
                            "HIGH",
                            "A maior conta excede o limite configurado de concentração; a métrica não identifica proprietário beneficiário.",
                            {
                                "largest_account_pct": float(largest_pct),
                                "threshold_pct": policy_values["max_single_account_pct"],
                                "excluded_accounts": excluded_accounts_list,
                            },
                        )
                    )
                if top10_pct > Decimal(str(policy_values["max_top10_accounts_pct"])):
                    findings.append(
                        _finding(
                            "TOP10_CONCENTRATION",
                            "HIGH",
                            "As dez maiores contas excedem o limite configurado de concentração; pools não são identificados automaticamente.",
                            {
                                "top10_accounts_pct": float(top10_pct),
                                "threshold_pct": policy_values["max_top10_accounts_pct"],
                                "excluded_accounts": excluded_accounts_list,
                            },
                        )
                    )

    wallet_raw = source.get("wallet_balance_raw")
    wallet = None
    if wallet_raw is not None:
        wallet = _parse_nonnegative_integer(wallet_raw)
        if wallet is None:
            findings.append(
                _finding(
                    "MALFORMED_WALLET_BALANCE",
                    "CRITICAL",
                    "O saldo bruto da carteira está malformado.",
                    {"valor": wallet_raw},
                )
            )
        elif supply is not None and wallet > supply:
            findings.append(
                _finding(
                    "WALLET_BALANCE_EXCEEDS_SUPPLY",
                    "CRITICAL",
                    "O saldo bruto da carteira excede o supply; os dados são inconsistentes.",
                    {"wallet_balance_raw": str(wallet), "supply_raw": str(supply)},
                )
            )
    if wallet is not None:
        result["metrics"]["wallet_balance_ui"] = _decimal_string(wallet, decimals_int)

    # This field is optional because not every RPC snapshot exposes account
    # state. When present, it is a direct high-risk signal, not a scam label.
    frozen_key_present = "wallet_frozen_accounts" in source
    wallet_frozen_accounts = source.get("wallet_frozen_accounts")
    frozen_valid = isinstance(wallet_frozen_accounts, list) and all(
        isinstance(address, str) and bool(address) for address in wallet_frozen_accounts
    )
    if frozen_valid and len(set(wallet_frozen_accounts)) != len(wallet_frozen_accounts):
        frozen_valid = False
    if frozen_key_present and not frozen_valid:
        findings.append(
            _finding(
                "MALFORMED_FROZEN_ACCOUNTS",
                "CRITICAL",
                "A lista opcional de carteiras congeladas está malformada.",
                {},
            )
        )
    elif frozen_valid and wallet_frozen_accounts:
        findings.append(
            _finding(
                "WALLET_FROZEN_ACCOUNTS",
                "HIGH",
                "Há contas da carteira congeladas; isso é um sinal de risco operacional e não identifica, por si só, uma fraude.",
                {"wallet_frozen_accounts": list(wallet_frozen_accounts)},
            )
        )

    previous_raw = source.get("previous_wallet_balance_raw")
    previous_present = "previous_wallet_balance_raw" in source and previous_raw is not None
    previous = None
    if previous_present:
        previous = _parse_nonnegative_integer(previous_raw)
        if previous is None:
            findings.append(
                _finding(
                    "MALFORMED_PREVIOUS_WALLET_BALANCE",
                    "CRITICAL",
                    "O saldo bruto anterior da carteira está malformado.",
                    {"valor": previous_raw},
                )
            )
        elif supply is not None and previous > supply:
            findings.append(
                _finding(
                    "PREVIOUS_BALANCE_EXCEEDS_SUPPLY",
                    "CRITICAL",
                    "O saldo bruto anterior excede o supply; os dados são inconsistentes.",
                    {"previous_wallet_balance_raw": str(previous), "supply_raw": str(supply)},
                )
            )
    if wallet is not None and previous is not None:
        result["metrics"]["wallet_delta_raw"] = str(wallet - previous)
        if wallet < previous:
            findings.append(_finding(
                "WALLET_BALANCE_DECREASE", "WARNING",
                "O saldo caiu desde a última leitura completa. Pode ser sua própria venda/transferência; revise antes de concluir que houve fraude.",
                {"wallet_delta_raw": str(wallet - previous)},
            ))

    slots = source.get("slots")
    slots_valid = isinstance(slots, dict) and bool(slots)
    parsed_slots: dict[str, int] = {}
    if slots_valid:
        for method, slot in slots.items():
            if (
                not isinstance(method, str)
                or not method
                or not isinstance(slot, int)
                or isinstance(slot, bool)
                or slot < 0
            ):
                slots_valid = False
                break
            parsed_slots[method] = slot
    if not slots_valid:
        findings.append(
            _finding(
                "MALFORMED_SLOTS",
                "CRITICAL",
                "A tabela de slots está ausente ou malformada.",
                {"valor": slots},
            )
        )
    else:
        slot_skew = max(parsed_slots.values()) - min(parsed_slots.values())
        if slot_skew > policy_values["max_slot_skew"]:
            findings.append(
                _finding(
                    "SLOT_SKEW",
                    "HIGH",
                    "Os slots das fontes divergem além do limite configurado; a observação pode estar inconsistente.",
                    {
                        "slot_skew": slot_skew,
                        "max_slot_skew": policy_values["max_slot_skew"],
                        "slots": parsed_slots,
                    },
                )
            )

    # A metric is useful even when no skew is detected, but only after the
    # shape of slots has been validated.
    if slots_valid:
        result["metrics"]["slot_skew"] = max(parsed_slots.values()) - min(parsed_slots.values())
    if data_age is not None:
        result["metrics"]["data_age_seconds"] = data_age

    # Deduplicate exact findings only in the unlikely case that a malformed
    # field triggered the same issue through two independent checks.
    deduped: list[dict[str, Any]] = []
    seen_finding_keys: set[tuple[str, str]] = set()
    for item in findings:
        key = (item["code"], item["severity"])
        if key not in seen_finding_keys:
            deduped.append(item)
            seen_finding_keys.add(key)
    findings = deduped
    result["findings"] = findings

    score = 0
    weights = {"INFO": 0, "WARNING": 10, "HIGH": 25, "CRITICAL": 50}
    for item in findings:
        score += weights[item["severity"]]
    result["heuristic_score"] = min(100, max(0, int(score)))

    has_critical = any(item["severity"] == "CRITICAL" for item in findings)
    has_high = any(item["severity"] == "HIGH" for item in findings)
    has_warning = any(item["severity"] == "WARNING" for item in findings)
    if has_critical:
        result["posture"] = "PAUSE"
        result["pause_new_actions"] = True
    elif has_high:
        # High-risk extension/concentration/slot findings are advisory pauses;
        # no action is executed by this module regardless of this field.
        result["posture"] = "PAUSE"
        result["pause_new_actions"] = True
    elif has_warning:
        result["posture"] = "CAUTION"
        result["pause_new_actions"] = False
    else:
        result["posture"] = "OBSERVE"
        result["pause_new_actions"] = False

    # Keep the externally visible mint/timestamp stable and normalized.
    result["mint"] = mint if isinstance(mint, str) else ""
    result["observed_at"] = observed_at_float
    return result


__all__ = ["analyze_snapshot"]
