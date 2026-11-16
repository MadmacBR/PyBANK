from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("PYBANK_DB", BASE_DIR / "pybank.db"))
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="PyBank Digital & Analytics", version="1.0.0")
security = HTTPBasic()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_number TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out')),
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                description TEXT NOT NULL,
                related_account TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_account_created
                ON transactions(account_id, created_at DESC);
            """
        )


@app.on_event("startup")
def startup() -> None:
    init_db()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def parse_amount(value: Decimal) -> int:
    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="Valor inválido")
    if not amount.is_finite() or amount <= 0:
        raise HTTPException(status_code=422, detail="O valor deve ser maior que zero")
    return int(amount * 100)


def money(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


class AccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class AmountInput(BaseModel):
    amount: Decimal


class TransferInput(AmountInput):
    destination_account: str = Field(min_length=1, max_length=32)


def authenticated_account(credentials: HTTPBasicCredentials = Depends(security)) -> sqlite3.Row:
    with connect() as conn:
        account = conn.execute(
            "SELECT * FROM accounts WHERE account_number = ?", (credentials.username,)
        ).fetchone()
    valid = account is not None and verify_password(credentials.password, account["password_hash"])
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Conta ou senha inválida",
            headers={"WWW-Authenticate": "Basic"},
        )
    return account


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate) -> dict[str, str]:
    account_number = secrets.token_hex(5).upper()
    with connect() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO accounts (account_number, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (account_number, payload.name.strip(), hash_password(payload.password), now_iso()),
            )
            account_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=503, detail="Não foi possível criar a conta; tente novamente")
    return {"account_number": account_number, "name": payload.name.strip(), "id": str(account_id)}


@app.get("/accounts/me")
def get_account(account: sqlite3.Row = Depends(authenticated_account)) -> dict[str, str]:
    return {
        "account_number": account["account_number"],
        "name": account["name"],
        "balance": money(account["balance_cents"]),
    }


@app.post("/transactions/deposit")
def deposit(payload: AmountInput, account: sqlite3.Row = Depends(authenticated_account)) -> dict[str, str]:
    cents = parse_amount(payload.amount)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE accounts SET balance_cents = balance_cents + ? WHERE id = ?", (cents, account["id"]))
        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount_cents, description, created_at) VALUES (?, 'deposit', ?, 'Depósito', ?)",
            (account["id"], cents, now_iso()),
        )
        row = conn.execute("SELECT balance_cents FROM accounts WHERE id = ?", (account["id"],)).fetchone()
        conn.commit()
    return {"message": "Depósito realizado", "balance": money(row["balance_cents"])}


@app.post("/transactions/withdraw")
def withdraw(payload: AmountInput, account: sqlite3.Row = Depends(authenticated_account)) -> dict[str, str]:
    cents = parse_amount(payload.amount)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT balance_cents FROM accounts WHERE id = ?", (account["id"],)).fetchone()
        if row["balance_cents"] < cents:
            conn.rollback()
            raise HTTPException(status_code=400, detail="Saldo insuficiente")
        conn.execute("UPDATE accounts SET balance_cents = balance_cents - ? WHERE id = ?", (cents, account["id"]))
        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount_cents, description, created_at) VALUES (?, 'withdrawal', ?, 'Saque', ?)",
            (account["id"], cents, now_iso()),
        )
        balance = conn.execute("SELECT balance_cents FROM accounts WHERE id = ?", (account["id"],)).fetchone()[0]
        conn.commit()
    return {"message": "Saque realizado", "balance": money(balance)}


@app.post("/transactions/transfer")
def transfer(payload: TransferInput, account: sqlite3.Row = Depends(authenticated_account)) -> dict[str, str]:
    cents = parse_amount(payload.amount)
    if payload.destination_account == account["account_number"]:
        raise HTTPException(status_code=400, detail="A conta de destino deve ser diferente")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        destination = conn.execute(
            "SELECT id, account_number FROM accounts WHERE account_number = ?", (payload.destination_account,)
        ).fetchone()
        source = conn.execute("SELECT balance_cents FROM accounts WHERE id = ?", (account["id"],)).fetchone()
        if destination is None:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Conta de destino não encontrada")
        if source["balance_cents"] < cents:
            conn.rollback()
            raise HTTPException(status_code=400, detail="Saldo insuficiente")
        timestamp = now_iso()
        conn.execute("UPDATE accounts SET balance_cents = balance_cents - ? WHERE id = ?", (cents, account["id"]))
        conn.execute("UPDATE accounts SET balance_cents = balance_cents + ? WHERE id = ?", (cents, destination["id"]))
        conn.executemany(
            "INSERT INTO transactions (account_id, transaction_type, amount_cents, description, related_account, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (account["id"], "transfer_out", cents, "Transferência enviada", destination["account_number"], timestamp),
                (destination["id"], "transfer_in", cents, "Transferência recebida", account["account_number"], timestamp),
            ],
        )
        balance = conn.execute("SELECT balance_cents FROM accounts WHERE id = ?", (account["id"],)).fetchone()[0]
        conn.commit()
    return {"message": "Transferência realizada", "balance": money(balance)}


@app.get("/transactions")
def statement(limit: int = 100, account: sqlite3.Row = Depends(authenticated_account)) -> list[dict[str, str]]:
    limit = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT transaction_type, amount_cents, description, related_account, created_at FROM transactions WHERE account_id = ? ORDER BY id DESC LIMIT ?",
            (account["id"], limit),
        ).fetchall()
    return [
        {
            "type": row["transaction_type"],
            "amount": money(row["amount_cents"]),
            "description": row["description"],
            "related_account": row["related_account"] or "",
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/transactions/evolution")
def evolution(account: sqlite3.Row = Depends(authenticated_account)) -> list[dict[str, str]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT transaction_type, amount_cents, created_at FROM transactions WHERE account_id = ? ORDER BY id ASC",
            (account["id"],),
        ).fetchall()
    balance = 0
    points = [{"date": "Início", "balance": "0.00"}]
    for row in rows:
        if row["transaction_type"] in ("deposit", "transfer_in"):
            balance += row["amount_cents"]
        else:
            balance -= row["amount_cents"]
        points.append({"date": row["created_at"], "balance": money(balance)})
    return points
