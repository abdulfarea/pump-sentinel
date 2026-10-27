"""Auditoria local; nunca armazena chave privada, RPC URL ou instruções de transação."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3


def fingerprint(report: dict) -> str:
    content = {key: report.get(key) for key in ("mint", "posture", "findings")}
    content["wallet_balance_ui"] = report.get("metrics", {}).get("wallet_balance_ui")
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class StateStore:
    def __init__(self, path: str, max_history: int = 10000):
        location = Path(path)
        location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if location.is_symlink():
            raise ValueError("O banco de auditoria não pode ser um link simbólico.")
        self.db = sqlite3.connect(location, timeout=10)
        os.chmod(location, 0o600)
        self.max_history = max_history
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY, wallet TEXT NOT NULL, mint TEXT NOT NULL,
                observed_at REAL NOT NULL, report TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS baselines (
                wallet TEXT NOT NULL, mint TEXT NOT NULL, amount_raw TEXT NOT NULL,
                observed_at REAL NOT NULL, PRIMARY KEY(wallet, mint)
            );
            CREATE TABLE IF NOT EXISTS alerts (
                wallet TEXT NOT NULL, mint TEXT NOT NULL, fingerprint TEXT NOT NULL,
                PRIMARY KEY(wallet, mint)
            );
        """)

    def previous_balance(self, wallet: str, mint: str) -> str | None:
        row = self.db.execute("SELECT amount_raw FROM baselines WHERE wallet=? AND mint=?",
                              (wallet, mint)).fetchone()
        return row[0] if row else None

    def save(self, wallet: str, snapshot: dict, report: dict) -> bool:
        mint = snapshot["mint"]
        signature = fingerprint(report)
        row = self.db.execute("SELECT fingerprint FROM alerts WHERE wallet=? AND mint=?",
                              (wallet, mint)).fetchone()
        changed = row is None or row[0] != signature
        with self.db:
            self.db.execute("INSERT INTO assessments(wallet,mint,observed_at,report) VALUES(?,?,?,?)",
                            (wallet, mint, report["observed_at"],
                             json.dumps(report, ensure_ascii=False, allow_nan=False)))
            amount = snapshot.get("wallet_balance_raw")
            if (wallet and snapshot.get("complete") is True and isinstance(amount, str)
                    and amount.isascii() and amount.isdigit()):
                self.db.execute("""INSERT INTO baselines VALUES(?,?,?,?)
                    ON CONFLICT(wallet,mint) DO UPDATE SET
                    amount_raw=excluded.amount_raw, observed_at=excluded.observed_at""",
                                (wallet, mint, amount, snapshot["observed_at"]))
            self.db.execute("""INSERT INTO alerts VALUES(?,?,?)
                ON CONFLICT(wallet,mint) DO UPDATE SET fingerprint=excluded.fingerprint""",
                            (wallet, mint, signature))
            self.db.execute("""DELETE FROM assessments WHERE id IN (
                SELECT id FROM assessments ORDER BY id DESC LIMIT -1 OFFSET ?
            )""", (self.max_history,))
        return changed

    def close(self) -> None:
        self.db.close()
