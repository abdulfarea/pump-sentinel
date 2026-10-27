"""CLI sem assinatura, sem venda automática e sem conectividade na demonstração."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from .config import ConfigError, load_config
from .donations import donation_instructions
from .engine import analyze_snapshot
from .rpc import RpcError, SolanaReader
from .state import StateStore


DEMO_MINT = "So11111111111111111111111111111111111111112"


def _print(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, allow_nan=False), flush=True)


def _demo() -> int:
    snapshot = {
        "mint": DEMO_MINT, "observed_at": time.time(), "complete": True, "errors": [],
        "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "mint_authority": None, "freeze_authority": None, "extensions": [],
        "unknown_extensions": False, "supply_raw": "1000000000000000", "decimals": 6,
        "largest_accounts": [{"address": "CONTA_FICTICIA_A", "amount_raw": "350000000000000"},
                             {"address": "CONTA_FICTICIA_B", "amount_raw": "300000000000000"}],
        "excluded_accounts": [], "wallet_balance_raw": "2500000000",
        "previous_wallet_balance_raw": "3000000000", "wallet_frozen_accounts": [],
        "slots": {"mint": 100, "largest": 100, "wallet": 100},
    }
    report = analyze_snapshot(snapshot)
    report["simulated"] = True
    report["simulation_notice"] = (
        "Todos os saldos e a concentração são fictícios. Não são dados reais deste mint."
    )
    _print(report)
    return 0


def _analyze(file: str) -> int:
    path = Path(file)
    if path.stat().st_size > 2_000_000:
        raise ConfigError("Snapshot excede 2 MB.")
    with path.open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    if not isinstance(snapshot, dict):
        raise ConfigError("O snapshot deve ser um objeto JSON.")
    report = analyze_snapshot(snapshot)
    _print(report)
    return 2 if report["pause_new_actions"] else 0


def _monitor(config_path: str, once: bool, cycles_override: int | None) -> int:
    config = load_config(config_path)
    if cycles_override is not None:
        if not 1 <= cycles_override <= 1000000:
            raise ConfigError("--cycles deve estar entre 1 e 1000000.")
        config["max_cycles"] = cycles_override
    # Nenhuma chave/carteira de assinatura é carregada, e este URL nunca é exibido.
    reader = SolanaReader(os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"))
    store = StateStore(config["state_path"], config["max_history"])
    cycles = 0
    try:
        while True:
            if Path(config["kill_switch_path"]).exists():
                _print({"event": "kill_switch", "posture": "PAUSE", "pause_new_actions": True,
                        "message": "Monitor interrompido antes da próxima consulta. Nenhuma transação é executada."})
                return 2
            started = time.monotonic()
            paused = incomplete = 0
            for mint in config["mints"]:
                if Path(config["kill_switch_path"]).exists():
                    _print({"event": "kill_switch", "posture": "PAUSE", "pause_new_actions": True})
                    return 2
                snapshot = reader.snapshot(mint, config["wallet"] or None,
                                           config["excluded_accounts"])
                previous = store.previous_balance(config["wallet"], mint)
                if previous is not None:
                    snapshot["previous_wallet_balance_raw"] = previous
                snapshot["data_age_seconds"] = max(0.0, time.time() - snapshot["observed_at"])
                report = analyze_snapshot(snapshot, config["policy"])
                report["mode"] = "READ_ONLY"
                changed = store.save(config["wallet"], snapshot, report)
                if once or changed:
                    _print(report)
                paused += int(report["pause_new_actions"])
                incomplete += int(not snapshot["complete"])
            cycles += 1
            _print({"event": "heartbeat", "cycle": cycles, "mints": len(config["mints"]),
                    "advisory_paused": paused, "incomplete": incomplete,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "observed_at": time.time(), "mode": "READ_ONLY"})
            if once or (config["max_cycles"] and cycles >= config["max_cycles"]):
                return 2 if once and paused else 0
            delay = max(0.0, config["interval_seconds"] - (time.monotonic() - started))
            # Verifica PAUSE pelo menos uma vez por segundo durante a espera.
            end = time.monotonic() + delay
            while time.monotonic() < end:
                if Path(config["kill_switch_path"]).exists():
                    break
                time.sleep(min(1.0, max(0.0, end - time.monotonic())))
    finally:
        reader.close()
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Defesa Solana/Pump.fun somente leitura; não garante segurança.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Demonstração fictícia offline, sem chamadas de rede")
    support = sub.add_parser("support", help="Mostrar instruções de apoio voluntário; não faz pagamentos")
    support.add_argument("--config", default="donations.example.toml")
    analyze = sub.add_parser("analyze", help="Analisar snapshot JSON local; não verifica autenticidade")
    analyze.add_argument("snapshot")
    for command in ("once", "watch"):
        item = sub.add_parser(command, help="Consultar RPC público (somente leitura)")
        item.add_argument("--config", default="config.toml")
        if command == "watch":
            item.add_argument("--cycles", type=int, default=None, help="Limitar ciclos para um teste finito")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            return _demo()
        if args.command == "analyze":
            return _analyze(args.snapshot)
        if args.command == "support":
            _print(donation_instructions(args.config))
            return 0
        return _monitor(args.config, args.command == "once", getattr(args, "cycles", None))
    except KeyboardInterrupt:
        print("Monitor encerrado pelo usuário; nenhuma transação executada.", file=sys.stderr)
        return 130
    except (ConfigError, RpcError, ValueError, OSError) as exc:
        # Erros de rede, arquivo e parse podem conter segredos de um URL ou payload.
        # Mostramos somente os tipos, nunca exception/repr ou traceback por padrão.
        label = "Configuração ou dados inválidos" if isinstance(exc, ValueError) else "Falha de leitura local/RPC"
        _print({"event": "startup_or_runtime_error", "posture": "PAUSE", "pause_new_actions": True,
                "message": f"{label}; revise a configuração e tente novamente. Nenhuma transação executada."})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
