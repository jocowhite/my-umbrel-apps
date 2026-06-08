#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import sqlite3
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


PORT = int(os.getenv("PORT", "8080"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "money-map.sqlite3"
STATIC_DIR = Path(__file__).parent / "static"

CATEGORIES = [
    ("Wohnen", "#7768ff"),
    ("Lebensmittel", "#25b986"),
    ("Restaurants & Cafes", "#ff9f43"),
    ("Mobilitaet", "#2d98da"),
    ("Versicherungen", "#5f6caf"),
    ("Gesundheit", "#eb4d4b"),
    ("Sport", "#20bf6b"),
    ("Freizeit & Entertainment", "#a55eea"),
    ("Reisen & Festivals", "#fd79a8"),
    ("Shopping", "#f7b731"),
    ("Abos & Mitgliedschaften", "#4b7bec"),
    ("Haushalt", "#778ca3"),
    ("Bildung", "#45aaf2"),
    ("Steuern & Gebuehren", "#8854d0"),
    ("Gehalt & Einkommen", "#0fb9b1"),
    ("Sonstige Einnahmen", "#26de81"),
    ("Bargeld", "#64748b"),
    ("Auslagen", "#e11d48"),
    ("Investieren", "#3448c5"),
    ("Investieren · MSCI World", "#5267e8"),
    ("Investieren · Bitcoin", "#f7931a"),
    ("Investieren · Aktien", "#3b82f6"),
    ("Investieren · Langzeitkonto", "#14b8a6"),
    ("Sonstiges", "#a5b1c2"),
    ("Interner Transfer", "#c7cbd6"),
]

DEFAULT_RULES = [
    ("Miete", "keyword", "miete|dinkelacker", "Wohnen", "fixed", 100),
    ("Supermaerkte", "regex", r"\b(rewe|edeka|lidl|aldi|netto|kaufland|penny|tegut)\b", "Lebensmittel", "variable", 80),
    ("Drogerie", "regex", r"\b(dm drogerie|rossmann|mueller drogerie)\b", "Haushalt", "variable", 80),
    ("Kino", "regex", r"\b(cinemax|cinemaxx|kino|ufa palast)\b", "Freizeit & Entertainment", "variable", 80),
    ("Streaming", "regex", r"\b(netflix|spotify|disney\+|prime video|apple\.com/bill)\b", "Abos & Mitgliedschaften", "fixed", 75),
    ("OePNV", "regex", r"\b(vvs|deutsche bahn|db vertrieb|flixbus)\b", "Mobilitaet", "variable", 70),
    ("Tanken", "regex", r"\b(aral|shell|esso|totalenergies|jet tankstelle)\b", "Mobilitaet", "variable", 70),
    ("Gehalt", "regex", r"\b(gehalt|lohn|salary)\b", "Gehalt & Einkommen", "income", 90),
]

FIELD_ALIASES = {
    "date": ["buchungstag", "datum", "date", "transaction date", "completed date"],
    "value_date": ["valutadatum", "wertstellung", "value date"],
    "amount": ["betrag", "amount (eur)", "amount", "netto", "net"],
    "currency": ["waehrung", "wahrung", "currency"],
    "payee": [
        "beguenstigter/zahlungspflichtiger",
        "begunstigter/zahlungspflichtiger",
        "zahlungspflichtiger",
        "beguenstigter",
        "payee",
        "partner name",
        "name",
    ],
    "description": [
        "verwendungszweck",
        "zahlungsreferenz",
        "payment reference",
        "reference",
        "beschreibung",
        "description",
        "artikelbezeichnung",
    ],
    "type": ["buchungstext", "transaction type", "typ", "type"],
    "status": ["status"],
    "iban": ["kontonummer/iban", "iban", "account number"],
    "transaction_id": ["transaktionscode", "transaction id", "id"],
}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                name TEXT PRIMARY KEY,
                color TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                match_type TEXT NOT NULL CHECK(match_type IN ('keyword', 'regex')),
                pattern TEXT NOT NULL,
                category TEXT NOT NULL REFERENCES categories(name),
                expense_type TEXT NOT NULL CHECK(expense_type IN ('fixed', 'variable', 'income')),
                priority INTEGER NOT NULL DEFAULT 50,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                filename TEXT NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                row_count INTEGER NOT NULL,
                new_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                account TEXT NOT NULL DEFAULT '',
                booked_on TEXT NOT NULL,
                value_on TEXT,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'EUR',
                payee TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                booking_type TEXT NOT NULL DEFAULT '',
                iban TEXT NOT NULL DEFAULT '',
                external_id TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Sonstiges' REFERENCES categories(name),
                expense_type TEXT NOT NULL DEFAULT 'variable' CHECK(expense_type IN ('fixed', 'variable', 'income')),
                matched_rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL,
                is_transfer INTEGER NOT NULL DEFAULT 0,
                transfer_group TEXT,
                is_manual INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(booked_on);
            CREATE INDEX IF NOT EXISTS idx_transactions_transfer ON transactions(is_transfer, amount_cents, booked_on);
            """
        )
        category_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(categories)").fetchall()
        }
        if "enabled" not in category_columns:
            conn.execute("ALTER TABLE categories ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        conn.executemany("INSERT OR IGNORE INTO categories(name, color) VALUES (?, ?)", CATEGORIES)
        if conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO rules(name, match_type, pattern, category, expense_type, priority) VALUES (?, ?, ?, ?, ?, ?)",
                DEFAULT_RULES,
            )


def text_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).strip().lower()


def decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def detect_dialect(text: str) -> csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        class Semicolon(csv.excel):
            delimiter = ";"
        return Semicolon()


def find_header(lines: list[str], dialect: csv.Dialect) -> int:
    aliases = {alias for values in FIELD_ALIASES.values() for alias in values}
    for index, line in enumerate(lines[:25]):
        try:
            cells = next(csv.reader([line], dialect))
        except csv.Error:
            continue
        normalized = {text_key(cell) for cell in cells}
        if len(normalized & aliases) >= 2:
            return index
    return 0


def parse_amount(value: str) -> int:
    raw = (value or "").strip().replace("\u00a0", "").replace("€", "").replace("'", "")
    if not raw:
        raise ValueError("Betrag fehlt")
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    raw = raw.strip("()+- ")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        cents = int((Decimal(raw) * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ValueError(f"Ungueltiger Betrag: {value}") from exc
    return -abs(cents) if negative else cents


def parse_date(value: str) -> str:
    raw = (value or "").strip()
    formats = (
        "%d.%m.%Y",
        "%d.%m.%y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    )
    raw_date = raw.split(" ")[0]
    for fmt in formats:
        try:
            return datetime.strptime(raw_date, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Ungueltiges Datum: {value}") from exc


def row_value(row: dict[str, str], field: str) -> str:
    normalized = {text_key(key): (value or "").strip() for key, value in row.items() if key}
    for alias in FIELD_ALIASES[field]:
        if alias in normalized and normalized[alias]:
            return normalized[alias]
    return ""


def infer_source(headers: list[str], requested: str) -> str:
    if requested in {"sparkasse", "n26", "paypal"}:
        return requested
    keys = {text_key(header) for header in headers}
    if "transaktionscode" in keys or {"brutto", "gebuhr", "netto"} <= keys:
        return "paypal"
    if "amount (eur)" in keys or "transaction type" in keys:
        return "n26"
    if "buchungstag" in keys or "verwendungszweck" in keys:
        return "sparkasse"
    return "generic"


def parse_transactions(raw: bytes, requested_source: str) -> tuple[str, list[dict]]:
    text = decode_csv(raw).replace("\x00", "")
    lines = text.splitlines()
    if not lines:
        raise ValueError("Die CSV-Datei ist leer.")
    dialect = detect_dialect(text)
    header_index = find_header(lines, dialect)
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), dialect=dialect)
    headers = reader.fieldnames or []
    source = infer_source(headers, requested_source)
    transactions = []
    for row_number, row in enumerate(reader, start=header_index + 2):
        if not any((value or "").strip() for value in row.values()):
            continue
        status = text_key(row_value(row, "status"))
        if source == "paypal" and status and status not in {"abgeschlossen", "completed", "cleared"}:
            continue
        try:
            booked_on = parse_date(row_value(row, "date"))
            amount_cents = parse_amount(row_value(row, "amount"))
        except ValueError as exc:
            raise ValueError(f"Zeile {row_number}: {exc}") from exc
        payee = row_value(row, "payee")
        description = row_value(row, "description")
        booking_type = row_value(row, "type")
        external_id = row_value(row, "transaction_id")
        account = ""
        if source == "sparkasse":
            normalized = {text_key(key): (value or "").strip() for key, value in row.items() if key}
            account = normalized.get("auftragskonto", "")
        fingerprint_data = "|".join(
            [source, booked_on, str(amount_cents), text_key(payee), text_key(description), external_id]
        )
        transactions.append(
            {
                "fingerprint": hashlib.sha256(fingerprint_data.encode()).hexdigest(),
                "source": source,
                "account": account,
                "booked_on": booked_on,
                "value_on": parse_date(row_value(row, "value_date")) if row_value(row, "value_date") else None,
                "amount_cents": amount_cents,
                "currency": row_value(row, "currency") or "EUR",
                "payee": payee,
                "description": description,
                "booking_type": booking_type,
                "iban": row_value(row, "iban"),
                "external_id": external_id,
            }
        )
    if not transactions:
        raise ValueError("Keine abgeschlossenen Buchungen mit Datum und Betrag gefunden.")
    return source, transactions


def rule_matches(rule: sqlite3.Row, haystack: str) -> bool:
    try:
        if rule["match_type"] == "regex":
            return re.search(rule["pattern"], haystack, flags=re.IGNORECASE) is not None
        return any(text_key(keyword) in haystack for keyword in rule["pattern"].split("|") if keyword.strip())
    except re.error:
        return False


def category_for(conn: sqlite3.Connection, transaction: dict) -> tuple[str, str, int | None]:
    if transaction["amount_cents"] > 0:
        fallback = ("Sonstige Einnahmen", "income", None)
    else:
        fallback = ("Sonstiges", "variable", None)
    haystack = text_key(
        " ".join(
            [
                transaction.get("payee", ""),
                transaction.get("description", ""),
                transaction.get("booking_type", ""),
                transaction.get("iban", ""),
            ]
        )
    )
    rules = conn.execute(
        "SELECT * FROM rules WHERE enabled = 1 ORDER BY priority DESC, id ASC"
    ).fetchall()
    for rule in rules:
        if rule_matches(rule, haystack):
            return rule["category"], rule["expense_type"], rule["id"]
    return fallback


def recategorize(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT * FROM transactions WHERE is_manual = 0 AND is_transfer = 0").fetchall()
    changed = 0
    for row in rows:
        category, expense_type, rule_id = category_for(conn, dict(row))
        conn.execute(
            "UPDATE transactions SET category=?, expense_type=?, matched_rule_id=? WHERE id=?",
            (category, expense_type, rule_id, row["id"]),
        )
        changed += 1
    return changed


def reconcile_transfers(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        UPDATE transactions
        SET is_transfer=0, transfer_group=NULL,
            category=CASE WHEN is_manual=0 THEN CASE WHEN amount_cents > 0 THEN 'Sonstige Einnahmen' ELSE 'Sonstiges' END ELSE category END,
            expense_type=CASE WHEN is_manual=0 THEN CASE WHEN amount_cents > 0 THEN 'income' ELSE 'variable' END ELSE expense_type END,
            matched_rule_id=CASE WHEN is_manual=0 THEN NULL ELSE matched_rule_id END
        WHERE is_transfer=1
        """
    )
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY booked_on, id"
    ).fetchall()
    used: set[int] = set()
    matched = 0
    for left in rows:
        if left["id"] in used:
            continue
        left_date = date.fromisoformat(left["booked_on"])
        candidates = []
        for right in rows:
            if right["id"] == left["id"] or right["id"] in used:
                continue
            if left["source"] == right["source"] and left["account"] == right["account"]:
                continue
            if left["amount_cents"] != -right["amount_cents"]:
                continue
            days = abs((left_date - date.fromisoformat(right["booked_on"])).days)
            if days <= 3:
                candidates.append((days, right["id"], right))
        if not candidates:
            continue
        _, _, right = min(candidates, key=lambda item: (item[0], item[1]))
        group = uuid.uuid4().hex
        for transaction_id in (left["id"], right["id"]):
            conn.execute(
                """
                UPDATE transactions
                SET is_transfer=1, transfer_group=?, category='Interner Transfer',
                    expense_type='variable', matched_rule_id=NULL
                WHERE id=?
                """,
                (group, transaction_id),
            )
            used.add(transaction_id)
        matched += 1
    recategorize(conn)
    return matched


def import_csv(raw: bytes, source: str, filename: str) -> dict:
    detected_source, transactions = parse_transactions(raw, source)
    new_count = 0
    duplicate_count = 0
    with connect() as conn:
        for transaction in transactions:
            category, expense_type, rule_id = category_for(conn, transaction)
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO transactions(
                    fingerprint, source, account, booked_on, value_on, amount_cents, currency,
                    payee, description, booking_type, iban, external_id, category,
                    expense_type, matched_rule_id
                ) VALUES (
                    :fingerprint, :source, :account, :booked_on, :value_on, :amount_cents, :currency,
                    :payee, :description, :booking_type, :iban, :external_id, :category,
                    :expense_type, :matched_rule_id
                )
                """,
                {**transaction, "category": category, "expense_type": expense_type, "matched_rule_id": rule_id},
            )
            if cursor.rowcount:
                new_count += 1
            else:
                duplicate_count += 1
        transfer_pairs = reconcile_transfers(conn)
        conn.execute(
            """
            INSERT INTO imports(source, filename, row_count, new_count, duplicate_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (detected_source, filename, len(transactions), new_count, duplicate_count),
        )
    return {
        "source": detected_source,
        "rows": len(transactions),
        "new": new_count,
        "duplicates": duplicate_count,
        "transfer_pairs": transfer_pairs,
    }


def row_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    if "amount_cents" in result:
        result["amount"] = result["amount_cents"] / 100
    return result


def month_range(month: str | None) -> tuple[str, str]:
    if not month or not re.fullmatch(r"\d{4}-\d{2}", month):
        month = date.today().strftime("%Y-%m")
    start = date.fromisoformat(month + "-01")
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start.isoformat(), end.isoformat()


def is_investment_sql(alias: str = "") -> str:
    column = f"{alias}.category" if alias else "category"
    return f"({column} = 'Investieren' OR {column} LIKE 'Investieren · %')"


def is_special_flow_sql(alias: str = "") -> str:
    column = f"{alias}.category" if alias else "category"
    return f"({is_investment_sql(alias)} OR {column} = 'Auslagen')"


def source_clause(source: str | None, alias: str = "") -> tuple[str, list[str]]:
    if source not in {"sparkasse", "n26", "paypal"}:
        return "", []
    column = f"{alias}.source" if alias else "source"
    return f" AND {column} = ?", [source]


def dashboard(month: str | None, source: str | None = None) -> dict:
    start, end = month_range(month)
    special_filter = is_special_flow_sql()
    special_filter_t = is_special_flow_sql("t")
    source_sql, source_params = source_clause(source)
    source_sql_t, source_params_t = source_clause(source, "t")
    with connect() as conn:
        totals = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN amount_cents > 0 AND is_transfer=0 AND NOT {special_filter} THEN amount_cents ELSE 0 END), 0) income,
                COALESCE(-SUM(CASE WHEN amount_cents < 0 AND is_transfer=0 AND NOT {special_filter} THEN amount_cents ELSE 0 END), 0) expenses,
                COALESCE(-SUM(CASE WHEN amount_cents < 0 AND is_transfer=0 AND NOT {special_filter} AND expense_type='fixed' THEN amount_cents ELSE 0 END), 0) fixed,
                COALESCE(-SUM(CASE WHEN amount_cents < 0 AND is_transfer=0 AND NOT {special_filter} AND expense_type='variable' THEN amount_cents ELSE 0 END), 0) variable,
                COUNT(*) count
            FROM transactions WHERE booked_on >= ? AND booked_on < ? {source_sql}
            """,
            (start, end, *source_params),
        ).fetchone()
        categories = conn.execute(
            f"""
            SELECT t.category, c.color, -SUM(t.amount_cents) amount_cents, COUNT(*) count
            FROM transactions t JOIN categories c ON c.name=t.category
            WHERE t.booked_on >= ? AND t.booked_on < ? AND t.amount_cents < 0
                AND t.is_transfer=0 AND NOT {special_filter_t} {source_sql_t}
            GROUP BY t.category, c.color ORDER BY amount_cents DESC
            """,
            (start, end, *source_params_t),
        ).fetchall()
        months = conn.execute(
            f"""
            SELECT substr(booked_on, 1, 7) month,
                SUM(CASE WHEN amount_cents > 0 AND is_transfer=0 AND NOT {special_filter} THEN amount_cents ELSE 0 END) income,
                -SUM(CASE WHEN amount_cents < 0 AND is_transfer=0 AND NOT {special_filter} THEN amount_cents ELSE 0 END) expenses
            FROM transactions WHERE 1=1 {source_sql}
            GROUP BY substr(booked_on, 1, 7) ORDER BY month DESC LIMIT 12
            """,
            source_params,
        ).fetchall()
        uncategorized = conn.execute(
            f"""
            SELECT COUNT(*) FROM transactions
            WHERE category='Sonstiges' AND is_transfer=0
                AND booked_on >= ? AND booked_on < ? {source_sql}
            """,
            (start, end, *source_params),
        ).fetchone()[0]
    return {
        "month": start[:7],
        "totals": {key: totals[key] / 100 if key != "count" else totals[key] for key in totals.keys()},
        "balance": (totals["income"] - totals["expenses"]) / 100,
        "categories": [
            {**dict(row), "amount": row["amount_cents"] / 100} for row in categories
        ],
        "months": [
            {
                "month": row["month"],
                "income": (row["income"] or 0) / 100,
                "expenses": (row["expenses"] or 0) / 100,
            }
            for row in reversed(months)
        ],
        "uncategorized": uncategorized,
        "source": source if source in {"sparkasse", "n26", "paypal"} else "",
    }


def investments() -> dict:
    investment_filter = is_investment_sql("t")
    with connect() as conn:
        categories = conn.execute(
            f"""
            SELECT t.category, c.color,
                COALESCE(-SUM(CASE WHEN t.amount_cents < 0 THEN t.amount_cents ELSE 0 END), 0) invested_cents,
                COALESCE(SUM(CASE WHEN t.amount_cents > 0 THEN t.amount_cents ELSE 0 END), 0) returned_cents,
                COUNT(*) count
            FROM transactions t JOIN categories c ON c.name=t.category
            WHERE {investment_filter} AND t.is_transfer=0
            GROUP BY t.category, c.color ORDER BY invested_cents DESC
            """
        ).fetchall()
        months = conn.execute(
            f"""
            SELECT substr(t.booked_on, 1, 7) month,
                COALESCE(-SUM(CASE WHEN t.amount_cents < 0 THEN t.amount_cents ELSE 0 END), 0) invested_cents
            FROM transactions t
            WHERE {investment_filter} AND t.is_transfer=0
            GROUP BY substr(t.booked_on, 1, 7) ORDER BY month
            """
        ).fetchall()
        transactions = conn.execute(
            f"""
            SELECT t.* FROM transactions t
            WHERE {investment_filter} AND t.is_transfer=0
            ORDER BY t.booked_on DESC, t.id DESC LIMIT 100
            """
        ).fetchall()
    invested_cents = sum(row["invested_cents"] for row in categories)
    returned_cents = sum(row["returned_cents"] for row in categories)
    return {
        "invested": invested_cents / 100,
        "returned": returned_cents / 100,
        "net": (invested_cents - returned_cents) / 100,
        "categories": [
            {
                **dict(row),
                "label": row["category"].removeprefix("Investieren · "),
                "invested": row["invested_cents"] / 100,
                "returned": row["returned_cents"] / 100,
            }
            for row in categories
        ],
        "months": [
            {"month": row["month"], "invested": row["invested_cents"] / 100}
            for row in months
        ],
        "transactions": [row_dict(row) for row in transactions],
    }


def outlays() -> dict:
    with connect() as conn:
        totals = conn.execute(
            """
            SELECT
                COALESCE(-SUM(CASE WHEN amount_cents < 0 THEN amount_cents ELSE 0 END), 0) paid_cents,
                COALESCE(SUM(CASE WHEN amount_cents > 0 THEN amount_cents ELSE 0 END), 0) reimbursed_cents
            FROM transactions WHERE category='Auslagen' AND is_transfer=0
            """
        ).fetchone()
        transaction_rows = conn.execute(
            """
            SELECT * FROM transactions
            WHERE category='Auslagen' AND is_transfer=0
            ORDER BY booked_on ASC, id ASC LIMIT 1000
            """
        ).fetchall()
    transactions = [row_dict(row) for row in transaction_rows]
    unmatched: list[dict] = []
    for transaction in transactions:
        transaction["outlay_status"] = "open"
        if transaction["amount_cents"] < 0:
            unmatched.append(transaction)
            continue
        candidates = [
            item
            for item in unmatched
            if -item["amount_cents"] == transaction["amount_cents"]
            and item["booked_on"] <= transaction["booked_on"]
        ]
        if not candidates:
            transaction["outlay_status"] = "unassigned"
            continue
        matched = max(candidates, key=lambda item: (item["booked_on"], item["id"]))
        matched["outlay_status"] = "settled"
        transaction["outlay_status"] = "settled"
        unmatched.remove(matched)
    return {
        "paid": totals["paid_cents"] / 100,
        "reimbursed": totals["reimbursed_cents"] / 100,
        "open": (totals["paid_cents"] - totals["reimbursed_cents"]) / 100,
        "transactions": list(reversed(transactions[-200:])),
    }


def category_usage() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.name, c.color, c.enabled,
                COUNT(t.id) usage_count,
                COALESCE(SUM(CASE WHEN t.amount_cents < 0 THEN -t.amount_cents ELSE 0 END), 0) spent_cents
            FROM categories c
            LEFT JOIN transactions t ON t.category=c.name
            WHERE c.enabled=1
            GROUP BY c.name, c.color, c.enabled
            ORDER BY usage_count ASC, c.name ASC
            """
        ).fetchall()
    protected = {"Sonstiges", "Sonstige Einnahmen", "Interner Transfer"}
    return [
        {
            **dict(row),
            "spent": row["spent_cents"] / 100,
            "removable": row["name"] not in protected,
        }
        for row in rows
    ]


def disable_category(category: str) -> None:
    if category in {"Sonstiges", "Sonstige Einnahmen", "Interner Transfer"}:
        raise ValueError("Diese Systemkategorie kann nicht entfernt werden.")
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM categories WHERE name=? AND enabled=1", (category,)
        ).fetchone()
        if not exists:
            raise ValueError("Kategorie nicht gefunden.")
        conn.execute("DELETE FROM rules WHERE category=?", (category,))
        conn.execute(
            """
            UPDATE transactions
            SET category=CASE WHEN amount_cents > 0 THEN 'Sonstige Einnahmen' ELSE 'Sonstiges' END,
                expense_type=CASE WHEN amount_cents > 0 THEN 'income' ELSE 'variable' END,
                matched_rule_id=NULL, is_manual=0
            WHERE category=?
            """,
            (category,),
        )
        conn.execute("UPDATE categories SET enabled=0 WHERE name=?", (category,))
        recategorize(conn)


class Handler(BaseHTTPRequestHandler):
    server_version = "MoneyMap/0.3"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Anfrage ist zu gross.")
        return json.loads(self.rfile.read(length) or b"{}")

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self.send_error(404)
            return
        if not target.is_file():
            target = STATIC_DIR / "index.html"
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self.send_json({"ok": True})
            elif parsed.path == "/api/dashboard":
                self.send_json(
                    dashboard(
                        query.get("month", [None])[0],
                        query.get("source", [""])[0],
                    )
                )
            elif parsed.path == "/api/investments":
                self.send_json(investments())
            elif parsed.path == "/api/outlays":
                self.send_json(outlays())
            elif parsed.path == "/api/transactions":
                month = query.get("month", [None])[0]
                start, end = month_range(month) if month else ("0000-01-01", "9999-12-31")
                category = query.get("category", [""])[0]
                source = query.get("source", [""])[0]
                search = query.get("q", [""])[0].strip()
                clauses = ["booked_on >= ?", "booked_on < ?"]
                params: list = [start, end]
                if category:
                    clauses.append("category = ?")
                    params.append(category)
                if source in {"sparkasse", "n26", "paypal"}:
                    clauses.append("source = ?")
                    params.append(source)
                if search:
                    clauses.append("(payee LIKE ? OR description LIKE ? OR booking_type LIKE ?)")
                    params.extend([f"%{search}%"] * 3)
                with connect() as conn:
                    rows = conn.execute(
                        f"SELECT * FROM transactions WHERE {' AND '.join(clauses)} ORDER BY booked_on DESC, id DESC LIMIT 1000",
                        params,
                    ).fetchall()
                self.send_json([row_dict(row) for row in rows])
            elif parsed.path == "/api/rules":
                with connect() as conn:
                    rows = conn.execute("SELECT * FROM rules ORDER BY priority DESC, id").fetchall()
                self.send_json([dict(row) for row in rows])
            elif parsed.path == "/api/categories":
                self.send_json(category_usage())
            elif parsed.path == "/api/imports":
                with connect() as conn:
                    rows = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 30").fetchall()
                self.send_json([dict(row) for row in rows])
            else:
                self.serve_static(parsed.path)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/import":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 25_000_000:
                    raise ValueError("CSV fehlt oder ist groesser als 25 MB.")
                raw = self.rfile.read(length)
                result = import_csv(
                    raw,
                    self.headers.get("X-Source", "auto").lower(),
                    self.headers.get("X-Filename", "upload.csv"),
                )
                self.send_json(result, 201)
            elif parsed.path == "/api/rules":
                data = self.read_json()
                match_type = data.get("match_type", "keyword")
                if match_type not in {"keyword", "regex"}:
                    raise ValueError("Unbekannter Regeltyp.")
                pattern = str(data.get("pattern", "")).strip()
                if not pattern:
                    raise ValueError("Ein Suchbegriff oder RegEx ist erforderlich.")
                if match_type == "regex":
                    re.compile(pattern)
                with connect() as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO rules(name, match_type, pattern, category, expense_type, priority, enabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(data.get("name") or pattern)[:120],
                            match_type,
                            pattern,
                            data["category"],
                            data.get("expense_type", "variable"),
                            int(data.get("priority", 50)),
                            1 if data.get("enabled", True) else 0,
                        ),
                    )
                    changed = recategorize(conn)
                self.send_json({"id": cursor.lastrowid, "recategorized": changed}, 201)
            elif parsed.path == "/api/reconcile":
                with connect() as conn:
                    pairs = reconcile_transfers(conn)
                self.send_json({"transfer_pairs": pairs})
            else:
                self.send_error(404)
        except (ValueError, KeyError, json.JSONDecodeError, re.error) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            match = re.fullmatch(r"/api/transactions/(\d+)", parsed.path)
            if not match:
                self.send_error(404)
                return
            data = self.read_json()
            fields = []
            params = []
            for key in ("category", "expense_type", "is_transfer"):
                if key in data:
                    fields.append(f"{key}=?")
                    params.append(data[key])
            if not fields:
                raise ValueError("Keine Aenderung angegeben.")
            fields.append("is_manual=1")
            params.append(int(match.group(1)))
            with connect() as conn:
                conn.execute(f"UPDATE transactions SET {', '.join(fields)} WHERE id=?", params)
            self.send_json({"ok": True})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            rule_match = re.fullmatch(r"/api/rules/(\d+)", parsed.path)
            category_match = re.fullmatch(r"/api/categories/(.+)", parsed.path)
            if rule_match:
                with connect() as conn:
                    conn.execute("DELETE FROM rules WHERE id=?", (int(rule_match.group(1)),))
                    changed = recategorize(conn)
                self.send_json({"ok": True, "recategorized": changed})
                return
            if category_match:
                category = unquote(category_match.group(1))
                disable_category(category)
                self.send_json({"ok": True})
                return
            self.send_error(404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"MoneyMap listening on http://0.0.0.0:{PORT}")
    server.serve_forever()
