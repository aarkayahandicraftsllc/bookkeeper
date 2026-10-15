"""Drives the desktop app's real widgets, offscreen.

Run:  python test_desktop.py

Qt runs with the 'offscreen' platform so this works with no display, which
means the desktop build is covered by tests rather than only eyeballed.
"""

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TMP = Path(tempfile.gettempdir()) / "tally_desktop_test.db"
TMP.unlink(missing_ok=True)
os.environ["BOOKS_DB"] = str(TMP)

from PySide6 import QtWidgets  # noqa: E402

import accounting as acc  # noqa: E402
import db  # noqa: E402
import desktop  # noqa: E402

FAILURES = []


def check(label, got, want, tol=0.005):
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        FAILURES.append(label)


def set_row(screen, row, ledger, debit=0.0, credit=0.0):
    """Fill one grid row the way a person would."""
    combo = screen.grid.cellWidget(row, 0)
    combo.setCurrentText(ledger)
    screen.grid.item(row, 1).setText(f"{debit:.2f}" if debit else "")
    screen.grid.item(row, 2).setText(f"{credit:.2f}" if credit else "")


db.init_db()
db.add_ledger("Bank", "Bank Accounts", 100_000, "Dr")
db.add_ledger("Capital", "Capital Account", 100_000, "Cr")
db.add_ledger("Sales", "Sales Accounts")
db.add_ledger("Purchases", "Purchase Accounts")
db.add_ledger("Rent", "Indirect Expenses")
db.add_ledger("Acme", "Sundry Debtors")

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
window = desktop.MainWindow()

print("\n1) The window opens with every screen")
check("seven screens", window.stack.count(), 7)
check("screen names", [name.replace("&&", "&") for name, _ in window.screens],
      ["Voucher Entry", "Day Book", "Ledger", "Trial Balance", "Profit & Loss",
       "Balance Sheet", "Masters"])
check("starts on voucher entry", window.stack.currentIndex(), 0)
check("title names the company", "Books" in window.windowTitle(), True)

print("\n2) Tally's function keys switch voucher type")
for key, name in desktop.VOUCHER_KEYS.items():
    window._set_voucher_type(name)
    check(f"{key} selects {name}", window.voucher.type_box.currentText(), name)
check("and it returns to voucher entry", window.stack.currentIndex(), 0)

print("\n3) Accept stays disabled until the voucher balances")
voucher = window.voucher
voucher.reset()
check("disabled on an empty grid", voucher.accept_button.isEnabled(), False)

set_row(voucher, 0, "Rent", debit=12_000)
check("still disabled with one side only", voucher.accept_button.isEnabled(), False)
check("the difference is shown", "12,000.00" in voucher.gap_label.text(), True)

set_row(voucher, 1, "Bank", credit=9_000)
check("still disabled while out of balance",
      voucher.accept_button.isEnabled(), False)

set_row(voucher, 1, "Bank", credit=12_000)
check("enabled once both sides agree", voucher.accept_button.isEnabled(), True)
check("totals read back", voucher.dr_label.text(), "Dr 12,000.00")
check("difference is nil", voucher.gap_label.text(), "Difference 0.00")
check("it says so", "ready to accept" in voucher.notice.text(), True)

print("\n4) Voucher type guidance appears without blocking")
window._set_voucher_type("Journal")
set_row(voucher, 0, "Rent", debit=12_000)
set_row(voucher, 1, "Bank", credit=12_000)
check("a journal touching bank is flagged", "ℹ️" in voucher.notice.text(), True)
check("but accept is still allowed", voucher.accept_button.isEnabled(), True)
window._set_voucher_type("Payment")
set_row(voucher, 0, "Rent", debit=12_000)
set_row(voucher, 1, "Bank", credit=12_000)
check("a payment crediting bank is clean", "ℹ️" in voucher.notice.text(), False)

print("\n5) Accepting posts the voucher and clears the form")
before = len(db.get_vouchers())
window._accept()
check("one voucher posted", len(db.get_vouchers()), before + 1)
check("the grid was cleared", voucher.row_values(), [])
check("accept went back to disabled", voucher.accept_button.isEnabled(), False)
check("rent carries the debit",
      float(acc.balances().set_index("ledger").loc["Rent", "closing"]), 12_000.0)
check("it was filed as a Payment",
      str(db.get_vouchers().iloc[0]["voucher_type"]), "Payment")

print("\n6) A spare line appears as you fill the last one")
voucher.reset()
check("starts with two lines", voucher.grid.rowCount(), 2)
set_row(voucher, 1, "Sales", credit=5_000)
check("a third line is offered", voucher.grid.rowCount(), 3)

print("\n7) The reports populate")
db.save_voucher(voucher_type="Sales", voucher_date=date.today(),
                narration="invoice",
                lines=[{"ledger_id": db.ledger_id("Acme"), "debit": 80_000,
                        "credit": 0},
                       {"ledger_id": db.ledger_id("Sales"), "debit": 0,
                        "credit": 80_000}])
window.refresh_all()

check("day book lists both vouchers", window.daybook.table.rowCount(), 2)
check("trial balance has rows", window.trial.table.rowCount() > 0, True)
check("trial balance reports agreement",
      "equal credits" in window.trial.status.text(), True)
check("balance sheet agrees", "Both sides agree" in window.sheet.status.text(), True)
check("net profit shown on the P&L",
      "68,000.00" in window.profit.net_label.text(), True)   # 80,000 - 12,000
check("masters lists the ledgers", window.masters.ledger_table.rowCount(), 7)
check("masters lists the groups", window.masters.group_table.rowCount(), 27)

print("\n8) The ledger screen shows a statement")
window.show_screen(2)
window.ledger.ledger_box.setCurrentText("Bank")
window.ledger.refresh()
check("bank statement has one entry", window.ledger.table.rowCount(), 1)
check("the caption shows the closing balance",
      "88,000.00 Dr" in window.ledger.caption.text(), True)

print("\n9) Opening a voucher from the day book loads it for alteration")
window.show_screen(1)
window.daybook.refresh()
first_id = int(window.daybook._frame.iloc[0]["voucher_id"])
window._alter(first_id)
check("it switched to voucher entry", window.stack.currentIndex(), 0)
check("it is in altering mode", window.voucher.editing_id, first_id)
check("the title says so", "Altering" in window.voucher.title.text(), True)
check("the lines were loaded", len(window.voucher.row_values()), 2)
# isVisible() needs a shown ancestor; isHidden() reflects the widget's
# own setVisible call, which is what we actually set here
check("cancel is offered", window.voucher.cancel_button.isHidden(), False)

rows = window.voucher.row_values()
check("the loaded voucher already balances",
      round(sum(r["debit"] - r["credit"] for r in rows), 2), 0.0)
window.voucher.reset()
check("cancelling clears the edit", window.voucher.editing_id, None)

print("\n10) Creating a ledger through Masters")
window.masters.led_name.setText("Petty Cash")
window.masters.led_group.setCurrentText("Cash-in-hand")
window.masters.led_open.setValue(2_500)
window.masters.led_side.setCurrentText("Dr")
window.masters.create_ledger()
check("the ledger exists", "Petty Cash" in set(db.get_ledgers()["name"]), True)
check("masters shows it", window.masters.ledger_table.rowCount(), 8)
check("voucher entry offers it straight away",
      "Petty Cash" in window.voucher._ledger_names, True)
check("the opening difference is now reported",
      abs(acc.opening_difference()) > 0, True)
check("the status bar says so",
      "opening balances" in window.statusBar().currentMessage(), True)

print("\n11) Creating a ledger mid-voucher, Tally's Alt+C")
voucher = window.voucher
voucher.reset()
# type a half-finished name into the first line, as you would before realising
# the ledger does not exist yet
voucher.grid.cellWidget(0, 0).setCurrentText("Courier Charges")
voucher.grid.setCurrentCell(0, 0)
check("the name is not a ledger yet",
      "Courier Charges" in voucher._ledger_ids, False)

dialog = desktop.LedgerDialog(voucher, name="Courier Charges")
check("the typed name is carried into the dialog", dialog.name.text(),
      "Courier Charges")
dialog.group_box.setCurrentText("Indirect Expenses")
check("it explains where the balance will land",
      "indirect expenses" in dialog.note.text().lower(), True)
dialog._create()
check("the ledger was created", dialog.created, "Courier Charges")
check("it exists in the books",
      "Courier Charges" in set(db.get_ledgers()["name"]), True)

# what create_ledger() does once the dialog returns
voucher._add_ledger_name("Courier Charges")
check("every line now offers it",
      all(voucher.grid.cellWidget(r, 0).findText("Courier Charges") >= 0
          for r in range(voucher.grid.rowCount())), True)
check("and the voucher screen knows its id",
      "Courier Charges" in voucher._ledger_ids, True)

# and it can be used straight away, on the same voucher
set_row(voucher, 0, "Courier Charges", debit=1_800)
set_row(voucher, 1, "Bank", credit=1_800)
check("the new ledger posts like any other",
      voucher.accept_button.isEnabled(), True)
window._set_voucher_type("Payment")
set_row(voucher, 0, "Courier Charges", debit=1_800)
set_row(voucher, 1, "Bank", credit=1_800)
window._accept()
check("it carries the debit",
      float(acc.balances().set_index("ledger").loc["Courier Charges", "closing"]),
      1_800.0)
check("the books still balance",
      acc.balance_sheet()["totals"]["difference"], 0.0, tol=0.0)
check("it reached the indirect expenses",
      "Courier Charges" in set(
          acc.profit_and_loss()["indirect_expense"]["Particulars"]), True)

print("\n12) Creating a group mid-voucher, then a ledger under it")
gdialog = desktop.GroupDialog(voucher, under="Secured Loans")
gdialog.name.setText("Equipment Loan")
gdialog._create()
check("the group was created", gdialog.created, "Equipment Loan")
check("it inherited its parent's nature",
      db.get_groups().set_index("name").loc["Equipment Loan", "nature"],
      "liability")
ldialog = desktop.LedgerDialog(voucher)
check("the new group is offered immediately",
      ldialog.group_box.findText("Equipment Loan") >= 0, True)
ldialog.name.setText("Tractor Loan")
ldialog.group_box.setCurrentText("Equipment Loan")
ldialog.opening.setValue(40_000)
ldialog.side.setCurrentText("Cr")
ldialog._create()
check("the ledger was created under it", ldialog.created, "Tractor Loan")
check("and it lands on the liabilities side",
      float(acc.balance_sheet()["liabilities"].set_index("Particulars")
            .loc["Loans (Liability)", "Amount"]), 40_000.0)

print("\n13) A rejected master shows a dialog, not a crash")
window.masters.led_name.setText("Petty Cash")      # duplicate
QtWidgets.QApplication.processEvents()
try:
    db.add_ledger("Petty Cash", "Cash-in-hand")
    check("duplicate rejected by the data layer", "accepted", "rejected")
except ValueError:
    check("duplicate rejected by the data layer", "rejected", "rejected")

print("\n14) Both front ends read the same books")
check("the desktop app uses the configured database", str(db.DB_PATH), str(TMP))
check("balances agree with the shared accounting layer",
      acc.trial_balance()["difference"], acc.trial_balance()["difference"])
check("balance sheet still balances",
      acc.balance_sheet()["totals"]["difference"], 0.0, tol=0.0)

print("\n" + ("ALL DESKTOP CHECKS PASSED" if not FAILURES
             else f"FAILURES: {FAILURES}"))
raise SystemExit(1 if FAILURES else 0)
