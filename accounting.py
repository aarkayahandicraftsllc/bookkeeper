"""Reports: balances, ledger statements, trial balance, P&L and balance sheet.

Everything works from one idea: a ledger's **closing balance** is its opening
balance plus every voucher line against it, held debit-positive. A positive
closing is a debit balance, a negative one a credit balance.

Because every voucher balances, the transactions always net to zero, so:

    sum of all closing balances  ==  sum of all opening balances

If that total is not zero, the opening balances themselves disagree. Rather
than hide it, the trial balance and the balance sheet both show the residual as
**Difference in opening balances**, which is what Tally does.
"""

from __future__ import annotations

import pandas as pd

import db

EPS = 0.005

# the primary groups that make up each side of the balance sheet, in the order
# Tally prints them
LIABILITY_SIDE = ["Capital Account", "Loans (Liability)", "Current Liabilities",
                  "Suspense A/c"]
ASSET_SIDE = ["Fixed Assets", "Investments", "Current Assets",
              "Misc. Expenses (Asset)"]


def side_of(amount: float) -> str:
    return "Dr" if amount >= 0 else "Cr"


def fmt_side(amount: float) -> str:
    """'13,744.00 Dr' — how a balance reads in Tally."""
    return f"{abs(amount):,.2f} {side_of(amount)}"


# --------------------------------------------------------------------------- #
# balances
# --------------------------------------------------------------------------- #
def balances(as_at=None, ledgers: pd.DataFrame | None = None,
             lines: pd.DataFrame | None = None) -> pd.DataFrame:
    """Opening, movement and closing per ledger, as at a date."""
    ledgers = db.get_ledgers(include_inactive=True) if ledgers is None else ledgers
    lines = db.get_lines(date_to=as_at) if lines is None else lines

    frame = ledgers[["id", "name", "group_name", "nature", "affects_gross",
                     "group_id", "opening_signed"]].copy()
    frame = frame.rename(columns={"id": "ledger_id", "name": "ledger",
                                  "opening_signed": "opening"})
    if lines.empty:
        frame["debit"] = 0.0
        frame["credit"] = 0.0
    else:
        totals = lines.groupby("ledger_id")[["debit", "credit"]].sum()
        frame = frame.join(totals, on="ledger_id")
        frame[["debit", "credit"]] = frame[["debit", "credit"]].fillna(0.0)
    frame["movement"] = (frame["debit"] - frame["credit"]).round(2)
    frame["closing"] = (frame["opening"] + frame["movement"]).round(2)
    return frame.reset_index(drop=True)


def opening_difference(as_at=None, ledgers: pd.DataFrame | None = None) -> float:
    """How far the opening balances are from agreeing. Zero in healthy books."""
    ledgers = db.get_ledgers(include_inactive=True) if ledgers is None else ledgers
    if ledgers.empty:
        return 0.0
    return round(float(ledgers["opening_signed"].sum()), 2)


# --------------------------------------------------------------------------- #
# ledger statement
# --------------------------------------------------------------------------- #
def ledger_statement(ledger_id: int, date_from=None, date_to=None) -> dict:
    """One account's entries in date order, with a running balance.

    Particulars name the other side of each voucher, prefixed the way Tally
    does it: a debit in this ledger reads 'To …', a credit reads 'By …'.
    """
    ledgers = db.get_ledgers(include_inactive=True).set_index("id")
    if int(ledger_id) not in ledgers.index:
        raise ValueError("No such ledger.")
    row = ledgers.loc[int(ledger_id)]

    everything = db.get_lines(date_to=date_to)
    mine = everything[everything["ledger_id"] == int(ledger_id)]

    before = mine
    if date_from is not None:
        before = mine[mine["voucher_date"] < str(date_from)]
        mine = mine[mine["voucher_date"] >= str(date_from)]
    else:
        before = mine.iloc[0:0]

    opening = round(float(row["opening_signed"])
                    + float(before["signed"].sum() if not before.empty else 0.0), 2)

    # the other ledgers in each of my vouchers, for the particulars column
    contra: dict[int, str] = {}
    if not mine.empty:
        others = everything[everything["voucher_id"].isin(set(mine["voucher_id"]))]
        others = others[others["ledger_id"] != int(ledger_id)]
        for voucher, group in others.groupby("voucher_id"):
            names = list(dict.fromkeys(group["ledger_name"]))
            contra[int(voucher)] = (names[0] if len(names) == 1
                                    else f"{names[0]} and {len(names) - 1} more")

    records, running = [], opening
    for line in mine.itertuples():
        running = round(running + float(line.signed), 2)
        other = contra.get(int(line.voucher_id), "(as per details)")
        records.append({
            "Date": line.voucher_date,
            "Particulars": ("To " if line.debit else "By ") + other,
            "Vch Type": line.voucher_type,
            "Vch No": int(line.number),
            "Debit": round(float(line.debit), 2),
            "Credit": round(float(line.credit), 2),
            "Balance": fmt_side(running),
            "voucher_id": int(line.voucher_id),
        })

    entries = pd.DataFrame(records, columns=[
        "Date", "Particulars", "Vch Type", "Vch No", "Debit", "Credit",
        "Balance", "voucher_id"])
    return {
        "ledger": str(row["name"]),
        "group": str(row["group_name"]),
        "opening": opening,
        "closing": round(running, 2),
        "debit_total": round(float(entries["Debit"].sum()), 2) if not entries.empty else 0.0,
        "credit_total": round(float(entries["Credit"].sum()), 2) if not entries.empty else 0.0,
        "entries": entries,
    }


# --------------------------------------------------------------------------- #
# day book
# --------------------------------------------------------------------------- #
def day_book(date_from=None, date_to=None) -> pd.DataFrame:
    """Every voucher in the period, one row per voucher, Tally's Day Book."""
    lines = db.get_lines(date_from=date_from, date_to=date_to)
    columns = ["Date", "Particulars", "Vch Type", "Vch No", "Debit", "Credit",
               "voucher_id"]
    if lines.empty:
        return pd.DataFrame(columns=columns)

    records = []
    for voucher, group in lines.groupby("voucher_id", sort=False):
        debits = group[group["debit"] > 0]["ledger_name"].tolist()
        credits = group[group["credit"] > 0]["ledger_name"].tolist()
        head = group.iloc[0]
        records.append({
            "Date": head["voucher_date"],
            "Particulars": " / ".join(debits) + "  ←  " + " / ".join(credits),
            "Vch Type": head["voucher_type"],
            "Vch No": int(head["number"]),
            "Debit": round(float(group["debit"].sum()), 2),
            "Credit": round(float(group["credit"].sum()), 2),
            "voucher_id": int(voucher),
        })
    frame = pd.DataFrame(records, columns=columns)
    return frame.sort_values(["Date", "Vch No"], ascending=[False, False]) \
                .reset_index(drop=True)


# --------------------------------------------------------------------------- #
# trial balance
# --------------------------------------------------------------------------- #
def trial_balance(as_at=None, by_group: bool = False) -> dict:
    """Closing balances with debit and credit columns that must agree."""
    frame = balances(as_at)
    frame = frame[frame["closing"].abs() > EPS]

    if by_group:
        grouped = frame.groupby("group_name", as_index=False)["closing"].sum()
        grouped["closing"] = grouped["closing"].round(2)
        rows = grouped.rename(columns={"group_name": "Particulars"})
    else:
        rows = frame[["ledger", "group_name", "closing"]].rename(
            columns={"ledger": "Particulars", "group_name": "Under"})

    rows = rows[rows["closing"].abs() > EPS].copy()
    rows["Debit"] = rows["closing"].map(lambda v: round(v, 2) if v > 0 else 0.0)
    rows["Credit"] = rows["closing"].map(lambda v: round(-v, 2) if v < 0 else 0.0)
    rows = rows.drop(columns=["closing"]).reset_index(drop=True)

    debit = round(float(rows["Debit"].sum()), 2) if not rows.empty else 0.0
    credit = round(float(rows["Credit"].sum()), 2) if not rows.empty else 0.0
    difference = round(debit - credit, 2)
    return {"rows": rows, "debit": debit, "credit": credit,
            "difference": difference}


# --------------------------------------------------------------------------- #
# profit & loss
# --------------------------------------------------------------------------- #
def profit_and_loss(date_from=None, date_to=None) -> dict:
    """Trading account then the indirect accounts, as Tally lays it out.

    With ``date_from`` unset the report runs from the start of the books and
    includes any opening balances sitting on nominal ledgers. Given a start
    date it reports only that period's movement, which is what you want for a
    month or a quarter.
    """
    ledgers = db.get_ledgers(include_inactive=True)
    lines = db.get_lines(date_from=date_from, date_to=date_to)

    frame = ledgers[["id", "name", "group_name", "nature", "affects_gross",
                     "opening_signed"]].copy()
    if lines.empty:
        frame["movement"] = 0.0
    else:
        movement = lines.groupby("ledger_id")["signed"].sum()
        frame["movement"] = frame["id"].map(movement).fillna(0.0)
    include_opening = date_from is None
    frame["amount"] = (
        frame["movement"] + (frame["opening_signed"] if include_opening else 0.0)
    ).round(2)

    nominal = frame[frame["nature"].isin(["income", "expense"])]

    def section(nature: str, gross: bool) -> pd.DataFrame:
        part = nominal[(nominal["nature"] == nature)
                       & (nominal["affects_gross"].astype(bool) == gross)]
        # income sits credit-side, so flip it to read as a positive figure
        sign = -1.0 if nature == "income" else 1.0
        out = pd.DataFrame({
            "Particulars": part["name"],
            "Under": part["group_name"],
            "Amount": (part["amount"] * sign).round(2),
        })
        out = out[out["Amount"].abs() > EPS]
        return out.sort_values("Amount", ascending=False).reset_index(drop=True)

    trading_income = section("income", True)
    trading_expense = section("expense", True)
    indirect_income = section("income", False)
    indirect_expense = section("expense", False)

    def total(part: pd.DataFrame) -> float:
        return round(float(part["Amount"].sum()), 2) if not part.empty else 0.0

    gross = round(total(trading_income) - total(trading_expense), 2)
    net = round(gross + total(indirect_income) - total(indirect_expense), 2)

    return {
        "trading_income": trading_income,
        "trading_expense": trading_expense,
        "indirect_income": indirect_income,
        "indirect_expense": indirect_expense,
        "totals": {
            "trading_income": total(trading_income),
            "trading_expense": total(trading_expense),
            "gross_profit": gross,
            "indirect_income": total(indirect_income),
            "indirect_expense": total(indirect_expense),
            "net_profit": net,
        },
    }


def net_profit(as_at=None) -> float:
    """Profit from the start of the books to a date — what the balance sheet needs."""
    return profit_and_loss(None, as_at)["totals"]["net_profit"]


# --------------------------------------------------------------------------- #
# balance sheet
# --------------------------------------------------------------------------- #
def balance_sheet(as_at=None) -> dict:
    """Both sides as at a date, balanced, with the residual named honestly."""
    frame = balances(as_at)
    groups = db.get_groups()
    lineage = db.group_lineage(groups)

    primary_of = {}
    for row in groups.itertuples():
        chain = lineage.get(int(row.id), [str(row.name)])
        primary_of[str(row.name)] = chain[0] if chain else str(row.name)
    frame["primary"] = frame["group_name"].map(primary_of).fillna(frame["group_name"])

    # nominal accounts are closed into Profit & Loss A/c, not listed here
    real = frame[~frame["nature"].isin(["income", "expense"])]
    by_primary = real.groupby("primary")["closing"].sum().round(2).to_dict()

    liabilities = [[name, round(-by_primary.get(name, 0.0), 2)]
                   for name in LIABILITY_SIDE if abs(by_primary.get(name, 0.0)) > EPS]
    assets = [[name, round(by_primary.get(name, 0.0), 2)]
              for name in ASSET_SIDE if abs(by_primary.get(name, 0.0)) > EPS]

    # anything under a group outside the two standard lists
    for name, amount in by_primary.items():
        if name in LIABILITY_SIDE or name in ASSET_SIDE or abs(amount) <= EPS:
            continue
        if amount < 0:
            liabilities.append([name, round(-amount, 2)])
        else:
            assets.append([name, round(amount, 2)])

    profit = net_profit(as_at)
    if abs(profit) > EPS:
        liabilities.append(["Profit & Loss A/c", profit])

    liability_total = round(sum(amount for _, amount in liabilities), 2)
    asset_total = round(sum(amount for _, amount in assets), 2)

    # the residual is the opening-balance disagreement; show it, do not bury it
    residual = round(asset_total - liability_total, 2)
    if abs(residual) > EPS:
        if residual > 0:
            liabilities.append(["Difference in opening balances", residual])
            liability_total = round(liability_total + residual, 2)
        else:
            assets.append(["Difference in opening balances", round(-residual, 2)])
            asset_total = round(asset_total - residual, 2)

    return {
        "liabilities": pd.DataFrame(liabilities, columns=["Particulars", "Amount"]),
        "assets": pd.DataFrame(assets, columns=["Particulars", "Amount"]),
        "totals": {
            "liabilities": liability_total,
            "assets": asset_total,
            "difference": round(asset_total - liability_total, 2),
            "net_profit": profit,
        },
    }
