"""Tally-style bookkeeping — Streamlit front end.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import accounting as acc
import db

st.set_page_config(page_title="Books", page_icon="📗", layout="wide")
db.init_db()

COMPANY = db.get_setting("company_name", "My Company")
CURRENCY = db.get_setting("currency", "₹")
FY_START_MONTH = int(db.get_setting("fy_start_month", "4"))
BOOKS_BEGIN = db.get_setting("books_begin", "")

ROW_PX = 35


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{CURRENCY}{abs(value):,.2f}"


def amount_col(label: str) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label, format="%.2f")


def table_height(rows: int, visible: int | None = None) -> int:
    shown = rows if visible is None else min(rows, visible)
    return ROW_PX * (max(shown, 1) + 1) + 3


def flash(message: str, kind: str = "success") -> None:
    """A message that survives the rerun which follows an action."""
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    queued = st.session_state.pop("flash", None)
    if queued:
        kind, message = queued
        getattr(st, kind)(message)


def nonce(name: str) -> int:
    return st.session_state.setdefault(f"nonce_{name}", 0)


def bump(name: str) -> None:
    st.session_state[f"nonce_{name}"] = nonce(name) + 1


def fy_bounds(today: date, start_month: int) -> tuple[date, date]:
    start_year = today.year if today.month >= start_month else today.year - 1
    start = date(start_year, start_month, 1)
    end_month = 12 if start_month == 1 else start_month - 1
    end_year = start_year if start_month == 1 else start_year + 1
    end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    return start, end


FY_START, FY_END = fy_bounds(date.today(), FY_START_MONTH)


def period_picker(key: str, allow_all: bool = True) -> tuple[date | None, date]:
    """From / to selector shared by the reports."""
    month_start = date.today().replace(day=1)
    month_end = date.today().replace(
        day=calendar.monthrange(date.today().year, date.today().month)[1])
    options = {
        "This financial year": (FY_START, min(FY_END, date.today())),
        "This month": (month_start, min(month_end, date.today())),
        "Custom": None,
    }
    if allow_all:
        options = {"Since books began": (None, date.today()), **options}

    left, right = st.columns([2, 3])
    with left:
        choice = st.selectbox("Period", list(options), key=f"{key}_period")
    if choice == "Custom":
        with right:
            picked = st.date_input(
                "From / to", value=(FY_START, date.today()),
                format="DD/MM/YYYY", key=f"{key}_range")
        if isinstance(picked, tuple) and len(picked) == 2:
            return picked[0], picked[1]
        return FY_START, date.today()
    return options[choice]


# --------------------------------------------------------------------------- #
# voucher entry
# --------------------------------------------------------------------------- #
def voucher_editor(prefix: str = "vch", existing: dict | None = None,
                   existing_lines: list[dict] | None = None) -> None:
    """Tally's voucher screen: type, date, number, then a Dr/Cr grid."""
    n = nonce(prefix)
    k = lambda name: f"{prefix}_{name}_{n}"  # noqa: E731

    ledgers = db.get_ledgers()
    if len(ledgers) < 2:
        st.warning(
            "You need at least two ledgers before you can post anything. "
            "Create them under **Masters**."
        )
        return
    names = list(ledgers["name"])
    id_for = dict(zip(ledgers["name"], ledgers["id"].astype(int)))
    name_for = {int(v): k2 for k2, v in id_for.items()}

    types = list(db.VOUCHER_TYPES)
    head1, head2, head3 = st.columns([2, 2, 2])
    with head1:
        default_type = (existing or {}).get("voucher_type", "Payment")
        voucher_type = st.radio(
            "Voucher type", types,
            index=types.index(default_type) if default_type in types else 0,
            key=k("type"),
        )
        st.caption(db.VOUCHER_TYPES[voucher_type])
    with head2:
        voucher_date = st.date_input(
            "Date",
            value=(date.fromisoformat(existing["voucher_date"]) if existing
                   else date.today()),
            format="DD/MM/YYYY", key=k("date"))
        number = (int(existing["number"]) if existing
                  else db.next_voucher_number(voucher_type))
        st.caption(f"Voucher No. **{number}**")
    with head3:
        narration = st.text_input(
            "Narration", value=(existing or {}).get("narration", ""),
            key=k("narration"), placeholder="what this entry is for")

    with st.expander("➕ Create a ledger or group without leaving this voucher"):
        st.caption(
            "The same idea as Tally's Alt+C. Anything already typed into the "
            "grid is kept — creating a master only reloads the ledger list."
        )
        make = st.radio("Create", ["Ledger", "Group"], horizontal=True,
                        key=k("make"))
        group_names = list(db.get_groups()["name"])
        if make == "Ledger":
            q1, q2 = st.columns(2)
            with q1:
                quick_name = st.text_input("Ledger name", key=k("qname"),
                                           placeholder="e.g. Bank of India")
                quick_group = st.selectbox("Under group", group_names,
                                           key=k("qgroup"))
            with q2:
                quick_open = st.number_input("Opening balance", min_value=0.0,
                                             step=1000.0, format="%.2f",
                                             key=k("qopen"))
                quick_side = st.radio("Dr / Cr", db.SIDES, horizontal=True,
                                      key=k("qside"))
            chosen = db.get_groups().set_index("name")
            if quick_group in chosen.index:
                nature = str(chosen.loc[quick_group, "nature"])
                trading = bool(chosen.loc[quick_group, "affects_gross"])
                where = {
                    "asset": "the assets side of the Balance Sheet",
                    "liability": "the liabilities side of the Balance Sheet",
                    "income": "the trading account" if trading else "indirect incomes",
                    "expense": "the trading account" if trading else "indirect expenses",
                }[nature]
                st.caption(f"A {nature} account — its balance will appear in {where}.")
            if st.button("Create ledger", key=k("qcreate")):
                try:
                    db.add_ledger(quick_name, quick_group, quick_open, quick_side)
                    flash(f"Ledger {quick_name.strip()!r} created — pick it on "
                          "any line below.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        else:
            g1, g2 = st.columns(2)
            with g1:
                quick_grp = st.text_input("Group name", key=k("qgname"),
                                          placeholder="e.g. Vehicle Loan")
            with g2:
                quick_parent = st.selectbox("Under", group_names, key=k("qparent"))
            st.caption("A sub-group inherits its parent's nature, so it lands on "
                       "the same statement.")
            if st.button("Create group", key=k("qgcreate")):
                try:
                    db.add_group(quick_grp, quick_parent)
                    flash(f"Group {quick_grp.strip()!r} created under "
                          f"{quick_parent}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.markdown("**Particulars**")
    if existing_lines:
        start = pd.DataFrame([
            {"Ledger": name_for.get(int(l["ledger_id"]), ""),
             "Debit": round(float(l["debit"]), 2),
             "Credit": round(float(l["credit"]), 2)}
            for l in existing_lines
        ])
    else:
        rows = st.number_input(
            "Lines", min_value=2, max_value=30, value=2, step=1, key=k("rows"),
            help="Two lines is the usual case. Raise it for a compound voucher.")
        start = pd.DataFrame({"Ledger": [None] * int(rows),
                              "Debit": [0.0] * int(rows),
                              "Credit": [0.0] * int(rows)})

    grid = st.data_editor(
        start, hide_index=True, width="stretch", num_rows="fixed", key=k("grid"),
        column_config={
            "Ledger": st.column_config.SelectboxColumn(
                "Ledger", options=names, width="large",
                help="Which account this side of the voucher hits."),
            "Debit": st.column_config.NumberColumn("Debit", min_value=0.0,
                                                   step=100.0, format="%.2f"),
            "Credit": st.column_config.NumberColumn("Credit", min_value=0.0,
                                                    step=100.0, format="%.2f"),
        },
    )

    filled = grid[grid["Ledger"].notna()
                  & ((grid["Debit"].fillna(0) > 0) | (grid["Credit"].fillna(0) > 0))]
    debit = round(float(filled["Debit"].fillna(0).sum()), 2) if not filled.empty else 0.0
    credit = round(float(filled["Credit"].fillna(0).sum()), 2) if not filled.empty else 0.0
    gap = round(debit - credit, 2)

    t1, t2, t3 = st.columns(3)
    t1.metric("Total debit", money(debit))
    t2.metric("Total credit", money(credit))
    t3.metric("Difference", money(gap))

    payload = [{"ledger_id": id_for[row.Ledger],
                "debit": float(row.Debit or 0), "credit": float(row.Credit or 0)}
               for row in filled.itertuples()]
    balanced = abs(gap) <= 0.005 and debit > 0 and len(payload) >= 2

    if filled.empty:
        st.caption("Pick a ledger on each line, then enter the amount under "
                   "**Debit** or **Credit** — never both on one line.")
    elif balanced:
        st.success("✅ Debit equals credit.")
    else:
        st.warning(f"Debit and credit must agree. Out by {money(abs(gap))}.")

    for note in db.voucher_type_warnings(voucher_type, payload, ledgers):
        st.info(f"ℹ️ {note}")

    label = "💾 Save changes" if existing else "📗 Accept voucher"
    if st.button(label, type="primary", key=k("save"), disabled=not balanced):
        try:
            db.save_voucher(
                voucher_type=voucher_type, voucher_date=voucher_date,
                narration=narration, lines=payload,
                voucher_id=int(existing["id"]) if existing else None)
            flash(f"{voucher_type} voucher saved — {money(debit)} each side.")
            bump(prefix)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #
st.title(f"📗 {COMPANY}")
st.caption(
    f"Financial year {FY_START.strftime('%d/%m/%Y')} to {FY_END.strftime('%d/%m/%Y')}"
    + (f" · books began {date.fromisoformat(BOOKS_BEGIN).strftime('%d/%m/%Y')}"
       if BOOKS_BEGIN else "")
)
show_flash()

gap = acc.opening_difference()
if abs(gap) > acc.EPS:
    st.warning(
        f"**Difference in opening balances: {money(abs(gap))} "
        f"{'Dr' if gap > 0 else 'Cr'}.** The opening balances on your ledgers do "
        "not agree, so the trial balance will not either. It is shown as its own "
        "line on the Balance Sheet until you fix it."
    )

(tab_voucher, tab_daybook, tab_ledger, tab_trial, tab_pl, tab_bs,
 tab_masters) = st.tabs(
    ["📝 Voucher Entry", "📘 Day Book", "📑 Ledger", "⚖️ Trial Balance",
     "📈 Profit & Loss", "🏦 Balance Sheet", "⚙️ Masters"])

# --------------------------------------------------------------------------- #
with tab_voucher:
    voucher_editor()

# --------------------------------------------------------------------------- #
with tab_daybook:
    st.subheader("Day Book")
    db_from, db_to = period_picker("daybook")
    kind = st.selectbox("Voucher type", ["All"] + list(db.VOUCHER_TYPES),
                        key="daybook_type")
    book = acc.day_book(db_from, db_to)
    if kind != "All" and not book.empty:
        book = book[book["Vch Type"] == kind]

    if book.empty:
        st.info("No vouchers in this period.")
    else:
        st.caption(f"{len(book)} voucher(s)")
        st.download_button(
            "⬇️ Day Book CSV",
            data=book.drop(columns=["voucher_id"]).to_csv(index=False)
                     .encode("utf-8-sig"),
            file_name=f"daybook_{date.today().isoformat()}.csv", mime="text/csv")
        chosen = st.dataframe(
            book.drop(columns=["voucher_id"]), hide_index=True, width="stretch",
            height=table_height(len(book), 20),
            on_select="rerun", selection_mode="single-row",
            column_config={
                "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                "Particulars": st.column_config.TextColumn("Particulars",
                                                           width="large"),
                "Debit": amount_col("Debit"), "Credit": amount_col("Credit"),
            })
        st.caption("`Debit ← Credit` shows which ledgers each voucher moved "
                   "value between. Select a row to open it.")

        picked = list((chosen or {}).get("selection", {}).get("rows", []))
        if picked:
            voucher_id = int(book.iloc[picked[0]]["voucher_id"])
            record = db.get_voucher(voucher_id)
            if record:
                head, lines = record
                st.divider()
                st.subheader(f"{head['voucher_type']} voucher no. {head['number']}")
                voucher_editor(f"edit{voucher_id}", head, lines)
                if st.checkbox("I want to delete this voucher",
                               key=f"delchk_{voucher_id}"):
                    if st.button("🗑️ Delete voucher", key=f"del_{voucher_id}"):
                        db.delete_voucher(voucher_id)
                        flash(f"Voucher {head['voucher_type']} no. "
                              f"{head['number']} deleted.")
                        st.rerun()

# --------------------------------------------------------------------------- #
with tab_ledger:
    st.subheader("Ledger")
    ledgers = db.get_ledgers(include_inactive=True)
    if ledgers.empty:
        st.info("No ledgers yet.")
    else:
        pick1, pick2 = st.columns([2, 3])
        with pick1:
            chosen_ledger = st.selectbox("Ledger", list(ledgers["name"]),
                                         key="ledger_pick")
        with pick2:
            lg_from, lg_to = period_picker("ledger")

        statement = acc.ledger_statement(
            int(ledgers.set_index("name").loc[chosen_ledger, "id"]), lg_from, lg_to)

        st.caption(f"**{statement['ledger']}** · under {statement['group']}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Opening", acc.fmt_side(statement["opening"]))
        m2.metric("Debit", money(statement["debit_total"]))
        m3.metric("Credit", money(statement["credit_total"]))
        m4.metric("Closing", acc.fmt_side(statement["closing"]))

        entries = statement["entries"]
        if entries.empty:
            st.info("No entries against this ledger in the period.")
        else:
            st.download_button(
                "⬇️ Ledger CSV",
                data=entries.drop(columns=["voucher_id"]).to_csv(index=False)
                         .encode("utf-8-sig"),
                file_name=f"ledger_{chosen_ledger}_{date.today().isoformat()}.csv",
                mime="text/csv")
            st.dataframe(
                entries.drop(columns=["voucher_id"]), hide_index=True,
                width="stretch", height=table_height(len(entries), 20),
                column_config={
                    "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                    "Particulars": st.column_config.TextColumn("Particulars",
                                                               width="large"),
                    "Debit": amount_col("Debit"), "Credit": amount_col("Credit"),
                })
            st.caption("**To** is a debit in this ledger, **By** a credit — the "
                       "name is the other side of the voucher.")

# --------------------------------------------------------------------------- #
with tab_trial:
    st.subheader("Trial Balance")
    tb1, tb2 = st.columns([2, 2])
    with tb1:
        as_at = st.date_input("As at", value=date.today(), format="DD/MM/YYYY",
                              key="tb_asat")
    with tb2:
        grouped = st.toggle("Summarise by group", key="tb_group")
    trial = acc.trial_balance(as_at, by_group=grouped)

    k1, k2, k3 = st.columns(3)
    k1.metric("Total debit", money(trial["debit"]))
    k2.metric("Total credit", money(trial["credit"]))
    k3.metric("Difference", money(trial["difference"]))

    if abs(trial["difference"]) <= acc.EPS:
        st.success("✅ Debits equal credits.")
    else:
        st.warning(
            f"Out by {money(abs(trial['difference']))} — this is the difference "
            "in opening balances, not a problem with your vouchers. Every "
            "voucher is forced to balance when it is saved."
        )

    if trial["rows"].empty:
        st.info("Nothing posted up to this date.")
    else:
        total_row = pd.DataFrame([{
            "Particulars": "Total", "Under": "",
            "Debit": trial["debit"], "Credit": trial["credit"]}])
        shown = pd.concat([trial["rows"], total_row], ignore_index=True)
        if "Under" not in trial["rows"].columns:
            shown = shown.drop(columns=["Under"])
        st.dataframe(shown, hide_index=True, width="stretch",
                     height=table_height(len(shown), None),
                     column_config={
                         "Particulars": st.column_config.TextColumn(
                             "Particulars", width="large"),
                         "Debit": amount_col("Debit"),
                         "Credit": amount_col("Credit")})
        st.download_button(
            "⬇️ Trial Balance CSV",
            data=shown.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"trial_balance_{as_at}.csv", mime="text/csv")

# --------------------------------------------------------------------------- #
with tab_pl:
    st.subheader("Profit & Loss")
    pl_from, pl_to = period_picker("pl")
    report = acc.profit_and_loss(pl_from, pl_to)
    totals = report["totals"]

    st.caption(
        ("Since the books began" if pl_from is None
         else f"{pl_from.strftime('%d/%m/%Y')} to {pl_to.strftime('%d/%m/%Y')}")
        + ". The trading accounts give gross profit; the indirect accounts "
          "take it to net profit."
    )

    g1, g2, g3 = st.columns(3)
    g1.metric("Gross profit" if totals["gross_profit"] >= 0 else "Gross loss",
              money(abs(totals["gross_profit"])))
    g2.metric("Indirect expenses", money(totals["indirect_expense"]))
    g3.metric("Net profit" if totals["net_profit"] >= 0 else "Net loss",
              money(abs(totals["net_profit"])))

    def section(title: str, frame: pd.DataFrame, total: float) -> None:
        st.markdown(f"**{title}** — {money(total)}")
        if frame.empty:
            st.caption("Nothing here.")
        else:
            st.dataframe(frame, hide_index=True, width="stretch",
                         height=table_height(len(frame), None),
                         column_config={"Amount": amount_col("Amount")})

    st.markdown("### Trading account")
    left, right = st.columns(2)
    with left:
        section("Purchases and direct expenses", report["trading_expense"],
                totals["trading_expense"])
    with right:
        section("Sales and direct incomes", report["trading_income"],
                totals["trading_income"])
    st.markdown(
        f"#### {'Gross profit' if totals['gross_profit'] >= 0 else 'Gross loss'}: "
        f"{money(abs(totals['gross_profit']))}")

    st.divider()
    st.markdown("### Profit & loss account")
    left, right = st.columns(2)
    with left:
        section("Indirect expenses", report["indirect_expense"],
                totals["indirect_expense"])
    with right:
        section("Indirect incomes", report["indirect_income"],
                totals["indirect_income"])
    st.markdown(
        f"#### {'Net profit' if totals['net_profit'] >= 0 else 'Net loss'}: "
        f"{money(abs(totals['net_profit']))}")

# --------------------------------------------------------------------------- #
with tab_bs:
    st.subheader("Balance Sheet")
    bs_as_at = st.date_input("As at", value=date.today(), format="DD/MM/YYYY",
                             key="bs_asat")
    sheet = acc.balance_sheet(bs_as_at)

    b1, b2, b3 = st.columns(3)
    b1.metric("Liabilities", money(sheet["totals"]["liabilities"]))
    b2.metric("Assets", money(sheet["totals"]["assets"]))
    b3.metric("Difference", money(sheet["totals"]["difference"]))

    if abs(sheet["totals"]["difference"]) <= acc.EPS:
        st.success("✅ Both sides agree.")
    else:
        st.error("The two sides do not agree — that should be impossible, "
                 "please report it.")

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Liabilities** — {money(sheet['totals']['liabilities'])}")
        st.dataframe(sheet["liabilities"], hide_index=True, width="stretch",
                     height=table_height(len(sheet["liabilities"]), None),
                     column_config={"Amount": amount_col("Amount")})
    with right:
        st.markdown(f"**Assets** — {money(sheet['totals']['assets'])}")
        st.dataframe(sheet["assets"], hide_index=True, width="stretch",
                     height=table_height(len(sheet["assets"]), None),
                     column_config={"Amount": amount_col("Amount")})
    st.caption(
        "Profit & Loss A/c carries the net profit from the start of the books to "
        "this date. Nominal ledgers are closed into it rather than listed here."
    )

# --------------------------------------------------------------------------- #
with tab_masters:
    st.subheader("Company")
    c1, c2, c3 = st.columns(3)
    with c1:
        new_name = st.text_input("Company name", value=COMPANY)
    with c2:
        new_fy = st.selectbox("Financial year starts", list(range(1, 13)),
                              index=FY_START_MONTH - 1,
                              format_func=lambda m: calendar.month_name[m])
    with c3:
        symbols = ["₹", "$", "€", "£"]
        new_cur = st.selectbox(
            "Currency", symbols,
            index=symbols.index(CURRENCY) if CURRENCY in symbols else 0)
    begin = st.date_input(
        "Books begin on",
        value=date.fromisoformat(BOOKS_BEGIN) if BOOKS_BEGIN else FY_START,
        format="DD/MM/YYYY")
    if st.button("Save company details"):
        db.set_setting("company_name", new_name.strip() or "My Company")
        db.set_setting("fy_start_month", new_fy)
        db.set_setting("currency", new_cur)
        db.set_setting("books_begin", begin.isoformat())
        flash("Company details saved.")
        st.rerun()

    st.divider()
    st.subheader("Ledgers")
    st.caption(
        "Every ledger sits under one group, and the group decides which report "
        "the balance lands on. Enter opening balances as a positive amount and "
        "pick Dr or Cr."
    )
    all_ledgers = db.get_ledgers(include_inactive=True)
    groups = db.get_groups()
    group_names = list(groups["name"])

    balances_now = acc.balances().set_index("ledger_id")
    view = all_ledgers[["id", "name", "group_name", "opening", "opening_side",
                        "is_reserved", "active"]].copy()
    view["closing"] = view["id"].map(balances_now["closing"]).fillna(0.0)
    view["Closing"] = view["closing"].map(acc.fmt_side)
    st.dataframe(
        view.drop(columns=["closing", "is_reserved"]).rename(columns={
            "id": "ID", "name": "Ledger", "group_name": "Under",
            "opening": "Opening", "opening_side": "Dr/Cr", "active": "Active"}),
        hide_index=True, width="stretch", height=table_height(len(view), 15),
        column_config={"Opening": amount_col("Opening")})

    with st.expander("➕ Create a ledger"):
        n1, n2 = st.columns(2)
        with n1:
            led_name = st.text_input("Name", key="new_led_name",
                                     placeholder="e.g. Bank of India")
            led_group = st.selectbox("Under group", group_names, key="new_led_group")
        with n2:
            led_open = st.number_input("Opening balance", min_value=0.0, step=1000.0,
                                       format="%.2f", key="new_led_open")
            led_side = st.radio("Dr / Cr", db.SIDES, horizontal=True,
                                key="new_led_side")
        if st.button("Create ledger", type="primary"):
            try:
                db.add_ledger(led_name, led_group, led_open, led_side)
                flash(f"Ledger {led_name.strip()!r} created under {led_group}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with st.expander("✏️ Alter or remove a ledger"):
        if all_ledgers.empty:
            st.caption("No ledgers yet.")
        else:
            target = st.selectbox("Ledger", list(all_ledgers["name"]),
                                  key="alter_led")
            row = all_ledgers.set_index("name").loc[target]
            a1, a2 = st.columns(2)
            with a1:
                alt_name = st.text_input("Name", value=target, key="alt_name")
                alt_group = st.selectbox(
                    "Under group", group_names,
                    index=group_names.index(str(row["group_name"])),
                    key="alt_group")
            with a2:
                alt_open = st.number_input(
                    "Opening balance", min_value=0.0, step=1000.0, format="%.2f",
                    value=float(row["opening"]), key="alt_open")
                alt_side = st.radio(
                    "Dr / Cr", db.SIDES,
                    index=db.SIDES.index(str(row["opening_side"])),
                    horizontal=True, key="alt_side")
            alt_active = st.checkbox("Active", value=bool(row["active"]),
                                     key="alt_active")
            if st.button("Save ledger"):
                try:
                    db.update_ledger(int(row["id"]), alt_name, alt_group, alt_open,
                                     alt_side, str(row["notes"]), alt_active)
                    flash(f"Ledger {alt_name.strip()!r} updated.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

            used = db.ledger_usage(int(row["id"]))
            if used:
                st.info(f"{target} appears in {used} voucher line(s), so it "
                        "cannot be deleted. Untick **Active** to hide it.")
            elif int(row["is_reserved"]):
                st.info(f"{target} is a reserved ledger.")
            elif st.button("🗑️ Delete ledger"):
                try:
                    db.delete_ledger(int(row["id"]))
                    flash(f"Ledger {target!r} deleted.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.divider()
    st.subheader("Groups")
    st.caption(
        "The 27 reserved groups come from Tally and cannot be removed. Add your "
        "own sub-groups under them when you want finer subtotals — a sub-group "
        "inherits its parent's nature."
    )
    st.dataframe(
        groups[["name", "parent_name", "nature", "affects_gross", "is_reserved"]]
        .rename(columns={"name": "Group", "parent_name": "Under",
                         "nature": "Nature", "affects_gross": "Trading",
                         "is_reserved": "Reserved"}),
        hide_index=True, width="stretch", height=table_height(len(groups), 12))

    with st.expander("➕ Create a sub-group"):
        g1, g2 = st.columns(2)
        with g1:
            grp_name = st.text_input("Name", key="new_grp_name",
                                     placeholder="e.g. Vehicle Loan")
        with g2:
            grp_parent = st.selectbox("Under", group_names, key="new_grp_parent")
        if st.button("Create group", type="primary"):
            try:
                db.add_group(grp_name, grp_parent)
                flash(f"Group {grp_name.strip()!r} created under {grp_parent}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        custom = groups[groups["is_reserved"] == 0]
        if not custom.empty:
            kill = st.selectbox("Remove group", [None] + list(custom["name"]),
                                key="rm_grp")
            if kill and st.button("🗑️ Remove group"):
                try:
                    db.delete_group(kill)
                    flash(f"Group {kill!r} removed.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.divider()
    st.caption(f"Data file: `{db.DB_PATH}`")
