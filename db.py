"""Storage for a Tally-style set of books: groups, ledgers and vouchers.

The structure follows Tally's, because the reports fall out of it:

    Group  ->  Ledger  ->  Voucher line

* **Groups** form a tree with 28 reserved groups at the top, mirroring Tally's.
  A group's ``nature`` (asset / liability / income / expense) decides which
  statement a balance lands on, and ``affects_gross`` separates the trading
  accounts (which produce gross profit) from the indirect ones.
* **Ledgers** are the accounts you actually post to. Each sits under exactly
  one group and may carry an opening balance.
* **Vouchers** are the transactions. Every voucher holds two or more lines
  whose debits and credits must agree exactly, which is enforced here rather
  than only in the form.

Everything is stored debit-positive internally: a signed balance of +500 means
500 Dr, -500 means 500 Cr. Presentation flips it back per convention.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("BOOKS_DB", APP_DIR / "data" / "books.db"))

NATURES = ("asset", "liability", "income", "expense")
SIDES = ("Dr", "Cr")

# Tally's voucher types, with the rule each one exists to express.
VOUCHER_TYPES = {
    "Payment": "Money going out of cash or bank.",
    "Receipt": "Money coming into cash or bank.",
    "Contra": "Money moving between your own cash and bank accounts.",
    "Journal": "Adjustments that touch neither cash nor bank.",
    "Sales": "An invoice raised on a customer.",
    "Purchase": "A bill received from a supplier.",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    parent_id     INTEGER REFERENCES groups(id),
    nature        TEXT    NOT NULL CHECK (nature IN ('asset', 'liability',
                                                     'income', 'expense')),
    affects_gross INTEGER NOT NULL DEFAULT 0,
    is_reserved   INTEGER NOT NULL DEFAULT 0,
    sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ledgers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    group_id     INTEGER NOT NULL REFERENCES groups(id),
    opening      REAL    NOT NULL DEFAULT 0 CHECK (opening >= 0),
    opening_side TEXT    NOT NULL DEFAULT 'Dr' CHECK (opening_side IN ('Dr', 'Cr')),
    notes        TEXT    NOT NULL DEFAULT '',
    is_reserved  INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS vouchers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_type TEXT    NOT NULL,
    number       INTEGER NOT NULL,
    voucher_date TEXT    NOT NULL,
    narration    TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL,
    UNIQUE (voucher_type, number)
);

CREATE TABLE IF NOT EXISTS voucher_lines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    ledger_id  INTEGER NOT NULL REFERENCES ledgers(id),
    debit      REAL    NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit     REAL    NOT NULL DEFAULT 0 CHECK (credit >= 0),
    line_order INTEGER NOT NULL DEFAULT 0,
    CHECK ((debit = 0 OR credit = 0) AND debit + credit > 0)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lines_voucher ON voucher_lines(voucher_id);
CREATE INDEX IF NOT EXISTS idx_lines_ledger ON voucher_lines(ledger_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_date ON vouchers(voucher_date);
"""

# Tally's reserved groups: (name, parent, nature, affects_gross)
# `affects_gross` marks the trading accounts that produce gross profit.
RESERVED_GROUPS = [
    ("Capital Account", None, "liability", 0),
    ("Reserves & Surplus", "Capital Account", "liability", 0),
    ("Loans (Liability)", None, "liability", 0),
    ("Bank OD A/c", "Loans (Liability)", "liability", 0),
    ("Secured Loans", "Loans (Liability)", "liability", 0),
    ("Unsecured Loans", "Loans (Liability)", "liability", 0),
    ("Current Liabilities", None, "liability", 0),
    ("Duties & Taxes", "Current Liabilities", "liability", 0),
    ("Provisions", "Current Liabilities", "liability", 0),
    ("Sundry Creditors", "Current Liabilities", "liability", 0),
    ("Fixed Assets", None, "asset", 0),
    ("Investments", None, "asset", 0),
    ("Current Assets", None, "asset", 0),
    ("Bank Accounts", "Current Assets", "asset", 0),
    ("Cash-in-hand", "Current Assets", "asset", 0),
    ("Deposits (Asset)", "Current Assets", "asset", 0),
    ("Loans & Advances (Asset)", "Current Assets", "asset", 0),
    ("Stock-in-hand", "Current Assets", "asset", 0),
    ("Sundry Debtors", "Current Assets", "asset", 0),
    ("Misc. Expenses (Asset)", None, "asset", 0),
    ("Suspense A/c", None, "liability", 0),
    ("Sales Accounts", None, "income", 1),
    ("Purchase Accounts", None, "expense", 1),
    ("Direct Expenses", None, "expense", 1),
    ("Direct Incomes", None, "income", 1),
    ("Indirect Expenses", None, "expense", 0),
    ("Indirect Incomes", None, "income", 0),
]

# the groups whose balances belong to cash or bank, used by the voucher rules
CASH_GROUPS = ("Cash-in-hand", "Bank Accounts", "Bank OD A/c")

# Tally creates these two ledgers with every new company
RESERVED_LEDGERS = [("Cash", "Cash-in-hand"), ("Profit & Loss A/c", "Primary")]

DEFAULT_SETTINGS = {
    "company_name": "My Company",
    "fy_start_month": "4",          # April, the Indian financial year
    "books_begin": "",              # filled in on first run
    "currency": "₹",
    "country": "India",
}


# --------------------------------------------------------------------------- #
# company master
# --------------------------------------------------------------------------- #
# Tally's Company Creation screen, trimmed to the fields that earn their place
# in a book-keeping-only build: who the company is, where it is, what it is
# registered as, and which year the books cover. Declared once, here in the data
# layer, because BOTH front ends render and save it - a field added to this
# tuple appears in the Qt screen and the Streamlit form with no further work,
# and both get the same validation.
@dataclass(frozen=True)
class CompanyField:
    key: str
    label: str
    kind: str = "text"          # text | multiline | month | date | choice
    hint: str = ""
    choices: tuple[str, ...] = ()
    required: bool = False


CURRENCY_SYMBOLS = ("₹", "$", "€", "£", "¥")

COMPANY_FIELDS: tuple[CompanyField, ...] = (
    CompanyField("company_name", "Company name", required=True),
    CompanyField("mailing_name", "Mailing name",
                 hint="How the name should print on statements. "
                      "Blank uses the company name."),
    CompanyField("address", "Address", kind="multiline"),
    CompanyField("state", "State"),
    CompanyField("pincode", "PIN code", hint="Six digits."),
    CompanyField("country", "Country"),
    CompanyField("phone", "Phone"),
    CompanyField("email", "E-mail"),
    CompanyField("pan", "PAN", hint="Ten characters, e.g. AAAPZ1234C."),
    CompanyField("gstin", "GSTIN",
                 hint="Fifteen characters. Must carry the same PAN."),
    CompanyField("tan", "TAN", hint="Ten characters, e.g. DELA12345B."),
    CompanyField("cin", "CIN", hint="Twenty-one characters."),
    CompanyField("fy_start_month", "Financial year begins", kind="month"),
    CompanyField("books_begin", "Books begin on", kind="date"),
    CompanyField("currency", "Currency symbol", kind="choice",
                 choices=CURRENCY_SYMBOLS),
)

# Identifiers are stored upper case, because that is how they are issued and
# how they must be quoted - and because a lower-case PAN would otherwise fail
# the GSTIN cross-check for no reason the user can see.
UPPER_FIELDS = ("pan", "gstin", "tan", "cin")

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# 2-digit state code, the holder's PAN, entity number, 'Z', then a check digit.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
CIN_RE = re.compile(r"^[LUu][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
PINCODE_RE = re.compile(r"^[0-9]{6}$")


def get_company() -> dict[str, str]:
    """Every company field, with the defaults filled in."""
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    stored = {row["key"]: row["value"] for row in rows}
    return {field.key: str(stored.get(field.key,
                                      DEFAULT_SETTINGS.get(field.key, "")) or "")
            for field in COMPANY_FIELDS}


def validate_company(values: dict[str, str]) -> dict[str, str]:
    """Clean and check the company details. Returns what should be stored.

    Blank is always acceptable - these are details you fill in as you learn
    them, and refusing to save a half-known address would be worse than useless.
    A value that IS given has to be well formed, because a malformed GSTIN is
    worse than an absent one: it reaches a filing looking legitimate.
    """
    cleaned: dict[str, str] = {}
    for field in COMPANY_FIELDS:
        raw = values.get(field.key, "")
        text = str("" if raw is None else raw).strip()
        if field.key in UPPER_FIELDS:
            text = text.upper()
        cleaned[field.key] = text

    if not cleaned["company_name"]:
        raise ValueError("The company needs a name.")

    for key, pattern, label, shape in (
        ("pan", PAN_RE, "PAN", "five letters, four digits, one letter"),
        ("gstin", GSTIN_RE, "GSTIN",
         "two-digit state code, a PAN, entity number, Z, check digit"),
        ("tan", TAN_RE, "TAN", "four letters, five digits, one letter"),
        ("cin", CIN_RE, "CIN", "21 characters, starting L or U"),
        ("pincode", PINCODE_RE, "PIN code", "six digits"),
    ):
        if cleaned[key] and not pattern.match(cleaned[key]):
            raise ValueError(
                f"{label} {cleaned[key]!r} is not the right shape "
                f"({shape}). Leave it blank if you do not have it yet.")

    # A GSTIN contains its holder's PAN at characters 3 to 12. If both are given
    # and they disagree, one of the two is wrong, and this is the only place it
    # will ever be caught.
    if cleaned["pan"] and cleaned["gstin"]:
        inside = cleaned["gstin"][2:12]
        if inside != cleaned["pan"]:
            raise ValueError(
                f"The GSTIN carries PAN {inside}, but the PAN field says "
                f"{cleaned['pan']}. A GSTIN always contains the holder's PAN, "
                f"so one of the two is wrong.")

    if cleaned["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                                         cleaned["email"]):
        raise ValueError(f"{cleaned['email']!r} does not look like an e-mail "
                         f"address.")

    try:
        month = int(cleaned["fy_start_month"] or 4)
    except ValueError:
        raise ValueError("The financial year must begin in a month.") from None
    if not 1 <= month <= 12:
        raise ValueError("The financial year must begin in a month, 1 to 12.")
    cleaned["fy_start_month"] = str(month)

    if cleaned["books_begin"]:
        try:
            date.fromisoformat(cleaned["books_begin"])
        except ValueError:
            raise ValueError(
                f"{cleaned['books_begin']!r} is not a date (expected "
                f"YYYY-MM-DD).") from None

    if not cleaned["currency"]:
        cleaned["currency"] = DEFAULT_SETTINGS["currency"]
    return cleaned


def save_company(values: dict[str, str]) -> dict[str, str]:
    """Validate, then store. Nothing is written if anything is wrong."""
    cleaned = validate_company(values)
    with connect() as conn:
        for key, value in cleaned.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    return cleaned


def company_display_name() -> str:
    """The name to print: the mailing name if one is set, else the company."""
    company = get_company()
    return company["mailing_name"] or company["company_name"]


# --------------------------------------------------------------------------- #
# connection
# --------------------------------------------------------------------------- #
@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db() -> None:
    """Create the schema and the reserved masters. Safe to call repeatedly."""
    with connect() as conn:
        conn.executescript(SCHEMA)

        if conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 0:
            ids: dict[str, int] = {}
            for order, (name, parent, nature, gross) in enumerate(RESERVED_GROUPS):
                cur = conn.execute(
                    "INSERT INTO groups (name, parent_id, nature, affects_gross,"
                    " is_reserved, sort_order) VALUES (?, ?, ?, ?, 1, ?)",
                    (name, ids.get(parent), nature, gross, order),
                )
                ids[name] = int(cur.lastrowid)

        if conn.execute("SELECT COUNT(*) FROM ledgers").fetchone()[0] == 0:
            cash_group = conn.execute(
                "SELECT id FROM groups WHERE name = 'Cash-in-hand'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO ledgers (name, group_id, is_reserved) VALUES (?, ?, 1)",
                ("Cash", cash_group),
            )

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT DO NOTHING",
                (key, value),
            )
        if not conn.execute(
            "SELECT value FROM settings WHERE key = 'books_begin'"
        ).fetchone()["value"]:
            today = datetime.now().date()
            start = today.replace(month=4, day=1)
            if today.month < 4:
                start = start.replace(year=today.year - 1)
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = 'books_begin'",
                (start.isoformat(),),
            )


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


# --------------------------------------------------------------------------- #
# groups
# --------------------------------------------------------------------------- #
def get_groups() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT g.*, p.name AS parent_name FROM groups g"
            " LEFT JOIN groups p ON p.id = g.parent_id"
            " ORDER BY g.sort_order, g.name", conn
        )


def group_id(name: str) -> int:
    with connect() as conn:
        row = conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"There is no group called {name!r}.")
    return int(row["id"])


def add_group(name: str, parent: str, nature: str | None = None) -> int:
    """Create a sub-group. Nature is inherited from the parent unless given."""
    name = name.strip()
    if not name:
        raise ValueError("A group needs a name.")
    groups = get_groups().set_index("name")
    if name in groups.index:
        raise ValueError(f"There is already a group called {name!r}.")
    if parent not in groups.index:
        raise ValueError(f"There is no group called {parent!r}.")
    parent_row = groups.loc[parent]
    nature = nature or str(parent_row["nature"])
    if nature not in NATURES:
        raise ValueError(f"Unknown nature {nature!r}")
    with connect() as conn:
        nxt = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM groups"
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO groups (name, parent_id, nature, affects_gross,"
            " is_reserved, sort_order) VALUES (?, ?, ?, ?, 0, ?)",
            (name, int(parent_row["id"]), nature,
             int(parent_row["affects_gross"]), nxt),
        )
        return int(cur.lastrowid)


def delete_group(name: str) -> None:
    groups = get_groups().set_index("name")
    if name not in groups.index:
        raise ValueError(f"There is no group called {name!r}.")
    if int(groups.loc[name, "is_reserved"]):
        raise ValueError(f"{name!r} is one of the reserved groups.")
    gid = int(groups.loc[name, "id"])
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM ledgers WHERE group_id = ?",
                        (gid,)).fetchone()[0]:
            raise ValueError(f"{name!r} still has ledgers under it.")
        if conn.execute("SELECT COUNT(*) FROM groups WHERE parent_id = ?",
                        (gid,)).fetchone()[0]:
            raise ValueError(f"{name!r} still has sub-groups under it.")
        conn.execute("DELETE FROM groups WHERE id = ?", (gid,))


def group_lineage(groups: pd.DataFrame | None = None) -> dict[int, list[str]]:
    """Each group's ancestry, root first — used to roll report subtotals up."""
    groups = get_groups() if groups is None else groups
    by_id = {int(r.id): r for r in groups.itertuples()}
    lineage: dict[int, list[str]] = {}
    for gid in by_id:
        chain, cursor = [], gid
        seen = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            row = by_id.get(cursor)
            if row is None:
                break
            chain.append(str(row.name))
            cursor = int(row.parent_id) if not pd.isna(row.parent_id) else None
        lineage[gid] = list(reversed(chain))
    return lineage


def primary_group(group_name: str, lineage: dict[int, list[str]] | None = None,
                  groups: pd.DataFrame | None = None) -> str:
    """The reserved top-level group a given group ultimately sits under."""
    groups = get_groups() if groups is None else groups
    lineage = group_lineage(groups) if lineage is None else lineage
    match = groups[groups["name"] == group_name]
    if match.empty:
        return group_name
    return lineage[int(match.iloc[0]["id"])][0]


# --------------------------------------------------------------------------- #
# ledgers
# --------------------------------------------------------------------------- #
def get_ledgers(include_inactive: bool = False) -> pd.DataFrame:
    sql = (
        "SELECT l.*, g.name AS group_name, g.nature, g.affects_gross"
        " FROM ledgers l JOIN groups g ON g.id = l.group_id"
    )
    if not include_inactive:
        sql += " WHERE l.active = 1"
    sql += " ORDER BY l.name"
    with connect() as conn:
        frame = pd.read_sql_query(sql, conn)
    if not frame.empty:
        frame["opening_signed"] = frame.apply(
            lambda r: float(r["opening"]) * (1 if r["opening_side"] == "Dr" else -1),
            axis=1,
        ).round(2)
    return frame


def ledger_id(name: str) -> int:
    with connect() as conn:
        row = conn.execute("SELECT id FROM ledgers WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"There is no ledger called {name!r}.")
    return int(row["id"])


def add_ledger(name: str, group: str, opening: float = 0.0,
               opening_side: str = "Dr", notes: str = "") -> int:
    name = name.strip()
    if not name:
        raise ValueError("A ledger needs a name.")
    if opening_side not in SIDES:
        raise ValueError("Opening side must be 'Dr' or 'Cr'.")
    if float(opening) < 0:
        raise ValueError("Enter the opening balance as a positive amount and "
                         "choose Dr or Cr.")
    gid = group_id(group)
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM ledgers WHERE name = ?",
                        (name,)).fetchone()[0]:
            raise ValueError(f"There is already a ledger called {name!r}.")
        cur = conn.execute(
            "INSERT INTO ledgers (name, group_id, opening, opening_side, notes)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, gid, round(float(opening), 2), opening_side, notes.strip()),
        )
        return int(cur.lastrowid)


def update_ledger(ledger: int, name: str, group: str, opening: float,
                  opening_side: str, notes: str = "", active: bool = True) -> None:
    if opening_side not in SIDES:
        raise ValueError("Opening side must be 'Dr' or 'Cr'.")
    if float(opening) < 0:
        raise ValueError("Enter the opening balance as a positive amount.")
    with connect() as conn:
        conn.execute(
            "UPDATE ledgers SET name = ?, group_id = ?, opening = ?,"
            " opening_side = ?, notes = ?, active = ? WHERE id = ?",
            (name.strip(), group_id(group), round(float(opening), 2), opening_side,
             notes.strip(), 1 if active else 0, int(ledger)),
        )


def ledger_usage(ledger: int) -> int:
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM voucher_lines WHERE ledger_id = ?", (int(ledger),)
        ).fetchone()[0]


def delete_ledger(ledger: int) -> None:
    if ledger_usage(ledger):
        raise ValueError("That ledger appears in vouchers — it cannot be deleted.")
    with connect() as conn:
        row = conn.execute("SELECT is_reserved, name FROM ledgers WHERE id = ?",
                           (int(ledger),)).fetchone()
        if row and int(row["is_reserved"]):
            raise ValueError(f"{row['name']} is a reserved ledger.")
        conn.execute("DELETE FROM ledgers WHERE id = ?", (int(ledger),))


# --------------------------------------------------------------------------- #
# vouchers
# --------------------------------------------------------------------------- #
def next_voucher_number(voucher_type: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(number), 0) + 1 FROM vouchers WHERE voucher_type = ?",
            (voucher_type,),
        ).fetchone()
    return int(row[0])


def _validate_lines(lines: list[dict], ledgers: pd.DataFrame) -> list[dict]:
    known = set(ledgers["id"].astype(int))
    cleaned = []
    for order, line in enumerate(lines):
        if line.get("ledger_id") in (None, "") and not (
                line.get("debit") or line.get("credit")):
            continue  # a blank row in the grid
        try:
            lid = int(line["ledger_id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Every line needs a ledger.") from None
        if lid not in known:
            raise ValueError("A line points at a ledger that does not exist.")
        debit = round(float(line.get("debit") or 0), 2)
        credit = round(float(line.get("credit") or 0), 2)
        if debit < 0 or credit < 0:
            raise ValueError("Use the other column instead of a negative amount.")
        if debit and credit:
            raise ValueError("A line is either a debit or a credit, not both.")
        if not debit and not credit:
            raise ValueError("Every line needs an amount.")
        cleaned.append({"ledger_id": lid, "debit": debit, "credit": credit,
                        "line_order": order})

    if len(cleaned) < 2:
        raise ValueError("A voucher needs at least two lines.")
    if len({line["ledger_id"] for line in cleaned}) < 2:
        raise ValueError("A voucher needs at least two different ledgers.")
    debits = round(sum(line["debit"] for line in cleaned), 2)
    credits = round(sum(line["credit"] for line in cleaned), 2)
    if abs(debits - credits) > 0.005:
        raise ValueError(
            f"Debit {debits:,.2f} and credit {credits:,.2f} must agree — "
            f"the difference is {abs(debits - credits):,.2f}."
        )
    return cleaned


def voucher_type_warnings(voucher_type: str, lines: list[dict],
                          ledgers: pd.DataFrame) -> list[str]:
    """Tally-style guidance: which side a voucher type expects cash or bank on.

    Returned as warnings rather than enforced, because real books occasionally
    need the exception — but you should see it before you accept the voucher.
    """
    if not lines:
        return []
    by_id = ledgers.set_index("id")
    groups = get_groups()
    lineage = group_lineage(groups)

    def is_cash(ledger_id_value: int) -> bool:
        if int(ledger_id_value) not in by_id.index:
            return False
        chain = lineage.get(int(by_id.loc[int(ledger_id_value), "group_id"]), [])
        own = str(by_id.loc[int(ledger_id_value), "group_name"])
        return any(name in CASH_GROUPS for name in chain + [own])

    cash_debits = [l for l in lines if l["debit"] and is_cash(l["ledger_id"])]
    cash_credits = [l for l in lines if l["credit"] and is_cash(l["ledger_id"])]
    any_cash = cash_debits or cash_credits
    notes = []

    if voucher_type == "Payment" and not cash_credits:
        notes.append("A payment normally credits a cash or bank ledger — the "
                     "money has to leave something.")
    if voucher_type == "Receipt" and not cash_debits:
        notes.append("A receipt normally debits a cash or bank ledger — the "
                     "money has to arrive somewhere.")
    if voucher_type == "Contra" and not (cash_debits and cash_credits):
        notes.append("A contra moves money between your own cash and bank "
                     "accounts, so both sides should be cash or bank.")
    if voucher_type == "Journal" and any_cash:
        notes.append("A journal is for adjustments that touch neither cash nor "
                     "bank. Use Payment, Receipt or Contra for money movements.")
    return notes


def save_voucher(*, voucher_type: str, voucher_date, narration: str,
                 lines: list[dict], voucher_id: int | None = None,
                 number: int | None = None) -> int:
    """Post a voucher. Refuses anything that does not balance."""
    if voucher_type not in VOUCHER_TYPES:
        raise ValueError(f"Unknown voucher type {voucher_type!r}")
    cleaned = _validate_lines(lines, get_ledgers(include_inactive=True))
    date_str = (voucher_date.isoformat() if hasattr(voucher_date, "isoformat")
                else str(voucher_date))

    with connect() as conn:
        if voucher_id is None:
            assigned = number or next_voucher_number(voucher_type)
            cur = conn.execute(
                "INSERT INTO vouchers (voucher_type, number, voucher_date,"
                " narration, created_at) VALUES (?, ?, ?, ?, ?)",
                (voucher_type, int(assigned), date_str, narration.strip(), _now()),
            )
            voucher_id = int(cur.lastrowid)
        else:
            conn.execute(
                "UPDATE vouchers SET voucher_type = ?, voucher_date = ?,"
                " narration = ? WHERE id = ?",
                (voucher_type, date_str, narration.strip(), int(voucher_id)),
            )
            conn.execute("DELETE FROM voucher_lines WHERE voucher_id = ?",
                         (int(voucher_id),))
        conn.executemany(
            "INSERT INTO voucher_lines (voucher_id, ledger_id, debit, credit,"
            " line_order) VALUES (?, ?, ?, ?, ?)",
            [(voucher_id, l["ledger_id"], l["debit"], l["credit"], l["line_order"])
             for l in cleaned],
        )
    return int(voucher_id)


def get_vouchers(date_from=None, date_to=None,
                 voucher_type: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM vouchers WHERE 1 = 1"
    params: list = []
    if date_from is not None:
        sql += " AND voucher_date >= ?"
        params.append(str(date_from))
    if date_to is not None:
        sql += " AND voucher_date <= ?"
        params.append(str(date_to))
    if voucher_type:
        sql += " AND voucher_type = ?"
        params.append(voucher_type)
    sql += " ORDER BY voucher_date DESC, id DESC"
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_lines(date_from=None, date_to=None) -> pd.DataFrame:
    """Every voucher line in the period, joined to its voucher and ledger."""
    sql = (
        "SELECT vl.id, vl.voucher_id, vl.ledger_id, vl.debit, vl.credit,"
        " vl.line_order, v.voucher_type, v.number, v.voucher_date, v.narration,"
        " l.name AS ledger_name, g.name AS group_name, g.nature, g.affects_gross,"
        " l.group_id"
        " FROM voucher_lines vl"
        " JOIN vouchers v ON v.id = vl.voucher_id"
        " JOIN ledgers l ON l.id = vl.ledger_id"
        " JOIN groups g ON g.id = l.group_id WHERE 1 = 1"
    )
    params: list = []
    if date_from is not None:
        sql += " AND v.voucher_date >= ?"
        params.append(str(date_from))
    if date_to is not None:
        sql += " AND v.voucher_date <= ?"
        params.append(str(date_to))
    sql += " ORDER BY v.voucher_date, v.id, vl.line_order"
    with connect() as conn:
        frame = pd.read_sql_query(sql, conn, params=params)
    if not frame.empty:
        frame["signed"] = (frame["debit"] - frame["credit"]).round(2)
    return frame


def get_voucher(voucher_id: int) -> tuple[dict, list[dict]] | None:
    with connect() as conn:
        head = conn.execute("SELECT * FROM vouchers WHERE id = ?",
                            (int(voucher_id),)).fetchone()
        if head is None:
            return None
        lines = conn.execute(
            "SELECT vl.ledger_id, vl.debit, vl.credit, l.name AS ledger_name"
            " FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id"
            " WHERE vl.voucher_id = ? ORDER BY vl.line_order",
            (int(voucher_id),),
        ).fetchall()
    return dict(head), [dict(line) for line in lines]


def delete_voucher(voucher_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM voucher_lines WHERE voucher_id = ?",
                     (int(voucher_id),))
        conn.execute("DELETE FROM vouchers WHERE id = ?", (int(voucher_id),))
