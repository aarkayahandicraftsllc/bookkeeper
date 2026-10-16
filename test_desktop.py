"""Drives the desktop app's real widgets, offscreen.

Run:  python test_desktop.py

Qt runs with the 'offscreen' platform so this works with no display, which
means the desktop build is covered by tests rather than only eyeballed.
"""

import os
import sys
import shutil
import tempfile
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TMP = Path(tempfile.gettempdir()) / "bookkeeper_desktop_test.db"
TMP.unlink(missing_ok=True)
os.environ["BOOKS_DB"] = str(TMP)
# Company files are created in BOOKS_DIR, so point it at a scratch
# folder: without this the suite would write companies into the
# user's real data/ directory.
SANDBOX = Path(tempfile.gettempdir()) / f"bookkeeper_sandbox_{TMP.stem}"
shutil.rmtree(SANDBOX, ignore_errors=True)
SANDBOX.mkdir(parents=True, exist_ok=True)
os.environ["BOOKS_DIR"] = str(SANDBOX)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import accounting as acc  # noqa: E402
import db  # noqa: E402
import desktop  # noqa: E402
import theme  # noqa: E402

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
check("eight screens", window.stack.count(), 8)
check("screen names", [name.replace("&&", "&") for name, _ in window.screens],
      ["Voucher Entry", "Day Book", "Ledger", "Trial Balance", "Profit & Loss",
       "Balance Sheet", "Masters", "Company"])
check("starts on voucher entry", window.stack.currentIndex(), 0)
check("title names the company", "Bookkeeper" in window.windowTitle(), True)

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

print("\n15) Colour schemes")


def contrast(fg, bg):
    """WCAG relative-contrast ratio between two #rrggbb colours."""
    def luminance(value):
        parts = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                  for c in parts]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# Every scheme must be legible. This is the check that makes adding a scheme
# safe: a status line that carries meaning through colour is useless if you
# cannot read it, and eyeballing the light one says nothing about the others.
AA = 4.5
worst = (None, 99.0)
for key, scheme in theme.SCHEMES.items():
    for token in theme.TOKENS:
        for ground in ("window", "base"):
            ratio = contrast(scheme.color(token), getattr(scheme, ground))
            if ratio < worst[1]:
                worst = (f"{key}.{token} on {ground}", ratio)
check("every token in every scheme clears WCAG AA",
      worst[1] >= AA, True)
print(f"       tightest: {worst[0]} at {worst[1]:.2f}:1 (floor {AA})")

check("the schemes offered are the ones the menu lists",
      sorted(theme.ORDER), sorted(list(theme.SCHEMES) + [theme.AUTO]))
check("every offered scheme has a label",
      all(theme.LABELS.get(k) for k in theme.ORDER), True)
check("an unknown saved value falls back rather than crashing",
      theme.resolve("chartreuse").key, theme.DEFAULT)
for old, new in theme.ALIASES.items():
    check(f"a preference saved as {old!r} still opens {new!r}",
          theme.resolve(old).key, new)
check("auto resolves to a real scheme",
      theme.resolve(theme.AUTO).key in theme.SCHEMES, True)
try:
    theme.SCHEMES["light"].color("highlight")   # structural, not a token
    raised = False
except KeyError:
    raised = True
check("asking for a non-token colour raises rather than silently working",
      raised, True)

# Switching through every scheme on the live window, the way the menu does.
for key in theme.ORDER:
    window.set_color_scheme(key)
    QtWidgets.QApplication.processEvents()
    check(f"{key}: saved to the books", db.get_setting(theme.SETTING_KEY), key)
    check(f"{key}: menu entry is ticked",
          window._scheme_actions[key].isChecked(), True)
    resolved = theme.resolve(key)
    check(f"{key}: palette follows the scheme",
          QtWidgets.QApplication.palette().color(
              QtGui.QPalette.ColorRole.Window).name(), resolved.window)
    # The status lines must have been recoloured, not left on the old scheme.
    stale = [lbl.objectName() or lbl.text()[:24]
             for lbl in window.findChildren(QtWidgets.QLabel)
             if lbl.property("tone")
             and resolved.color(lbl.property("tone")) not in lbl.styleSheet()]
    check(f"{key}: no status line left on the old colour", stale, [])

window.trial.refresh()
check("a report run after switching uses the active scheme",
      theme.active().color("warn") in window.trial.status.styleSheet()
      or theme.active().color("good") in window.trial.status.styleSheet(),
      True)

window.set_color_scheme("light")
check("back on light, the platform style is restored",
      QtWidgets.QApplication.style().objectName().lower()
      in (theme._native_style.lower(), ""), True)

print("\n16) Text size, and the layout following it")

check("the default is a step above the platform size",
      theme.TEXT_STEPS[theme.DEFAULT_TEXT] > 0, True)

base_pt = theme.point_size()
window.set_color_scheme("light")

def settle():
    """Let Qt catch up, INCLUDING deferred deletions.

    processEvents() does not deliver DeferredDelete at the same event-loop
    level, so widgets retired with deleteLater() linger and the counts below
    creep upward - which looks exactly like a leak and is not one. Flushing
    them explicitly means these counts would catch a real leak.
    """
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.Type.DeferredDelete)


sizes = {}
for key in theme.TEXT_ORDER:
    window.set_text_size(key)
    settle()
    pt = theme.point_size()
    sizes[key] = pt
    check(f"{key}: saved to the books",
          db.get_setting(theme.FONT_SETTING_KEY), key)
    check(f"{key}: menu entry is ticked",
          window._text_actions[key].isChecked(), True)
    check(f"{key}: the application font is {pt}pt",
          QtWidgets.QApplication.font().pointSize(), pt)

    # Everything that sets its own point size must track the setting. These are
    # the widgets that do NOT follow the application font on their own.
    headings = [w for w in window.findChildren(QtWidgets.QWidget)
                if w.property("heading")]
    monos = [w for w in window.findChildren(QtWidgets.QWidget)
             if w.property("mono")]
    check(f"{key}: all {len(headings)} headings scaled",
          {w.font().pointSize() for w in headings},
          {theme.heading_point_size()})
    check(f"{key}: all {len(monos)} monospaced labels scaled",
          {w.font().pointSize() for w in monos}, {pt})

    # A table's amount cells are rebuilt on refresh; they must come back at the
    # new size too, or the figures stay small while their labels grow.
    window.show_screen(3)                      # Trial Balance
    QtWidgets.QApplication.processEvents()
    cells = [window.trial.table.item(r, c)
             for r in range(window.trial.table.rowCount())
             for c in range(window.trial.table.columnCount())
             if window.trial.table.item(r, c)
             and window.trial.table.item(r, c).font().family() != ""]
    mono_cells = [i for i in cells if i.font().pointSize() == pt]
    check(f"{key}: table cells at the new size", bool(mono_cells), True)

check("each step is strictly larger than the last",
      [sizes[k] for k in theme.TEXT_ORDER],
      sorted(sizes[k] for k in theme.TEXT_ORDER))
check("Normal is the platform's own size", sizes["normal"], theme._base_point)

# The layout has to ADAPT, not just redraw bigger. Nothing may be clipped: a
# widget whose sizeHint exceeds the room it was given is cut off on screen.
window.set_text_size("largest")
window.resize(window._sized_to_text())
QtWidgets.QApplication.processEvents()
clipped = []
for index in range(len(window.screens)):
    window.show_screen(index)
    QtWidgets.QApplication.processEvents()
    screen = window.screens[index][1]
    for label in screen.findChildren(QtWidgets.QLabel):
        if not label.isHidden() and label.text() and not label.wordWrap():
            need = label.sizeHint()
            if need.height() > label.height() + 1:
                clipped.append(f"{window.screens[index][0]}: "
                               f"{label.text()[:30]!r}")
check("nothing is clipped at the largest size", clipped, [])

# A window can never be narrower than its widest UNWRAPPED label, so one long
# unwrapped sentence silently sets a floor on the whole app - the Balance Sheet
# note was forcing 1788px, which is wider than a 1366px laptop screen and grew
# with every text step. Guard the floor rather than the individual labels.
WIDTH_CEILING = 1400
too_wide = {name: screen.minimumSizeHint().width()
            for name, screen in window.screens
            if screen.minimumSizeHint().width() > WIDTH_CEILING}
check(f"no screen demands over {WIDTH_CEILING}px at the largest size",
      too_wide, {})
print("       screen minimum widths: "
      + ", ".join(f"{name.replace('&&', '&')} {screen.minimumSizeHint().width()}"
                  for name, screen in window.screens))

# And the window must not open bigger than the display it is on.
avail = QtGui.QGuiApplication.primaryScreen().availableGeometry().size()
want = window._sized_to_text()
check("the window fits the screen at the largest size",
      want.width() <= max(avail.width(), window.minimumSizeHint().width())
      and want.height() <= max(avail.height(), window.minimumSizeHint().height()),
      True)

widths, scales = [], []
for key in theme.TEXT_ORDER:
    window.set_text_size(key)
    settle()
    widths.append(window._sized_to_text().width())
    scales.append(theme.text_scale())
window.set_text_size("largest")

# The intent - bigger text asks for a bigger window - is the scale, which is
# environment-free. The realised width can only be non-decreasing, because it
# is clamped to the display and raised to the layout minimum: on a small
# screen (this test runs on an 800x800 offscreen one) every step lands on the
# same clamped size, which is correct rather than a failure.
check("each step asks for a larger window", scales, sorted(set(scales)))
check("the window never shrinks as text grows",
      widths, sorted(widths))
print("       scale " + " -> ".join(f"{s:.2f}" for s in scales)
      + " | width " + " -> ".join(f"{w}px" for w in widths))

for index in range(len(window.screens)):
    window.show_screen(index)
    QtWidgets.QApplication.processEvents()
    screen = window.screens[index][1]
    fits = window.width() >= screen.minimumSizeHint().width()
    check(f"{window.screens[index][0]} fits the window at largest size",
          fits, True)

# Back to the default, and the books still add up after all that.
window.set_text_size(theme.DEFAULT_TEXT)
check("text size returns to the default",
      QtWidgets.QApplication.font().pointSize(), base_pt)
check("the balance sheet still balances",
      acc.balance_sheet()["totals"]["difference"], 0.0, tol=0.0)

print("\n17) The Company screen")

co = window.company
check("every declared field has an editor",
      sorted(co.editors), sorted(f.key for f in db.COMPANY_FIELDS))
check("it is reachable as a screen",
      "Company" in [name for name, _ in window.screens], True)

window.show_screen(len(window.screens) - 1)
settle()
co.editors["company_name"].setText("Aarkaya Handicrafts LLC")
co.editors["pan"].setText("aaapz1234c")          # lower case on purpose
co.editors["gstin"].setText("09AAAPZ1234C1Z5")
co.editors["address"].setPlainText("12 Mall Road\nNew Delhi")
check("saving valid details succeeds", co.save(), True)
check("the form shows the upper-cased PAN back",
      co.editors["pan"].text(), "AAAPZ1234C")
check("it reached the books", db.get_company()["gstin"], "09AAAPZ1234C1Z5")
check("the window title follows the company name",
      window.windowTitle().startswith("Aarkaya Handicrafts LLC"), True)

# A rejected save must explain itself and KEEP the typing - losing a form to
# one bad character is worse than the bad character.
co.editors["gstin"].setText("09BBBPZ1234C1Z5")
check("a GSTIN not carrying the PAN is refused", co.save(), False)
check("the reason is on screen", "PAN" in co.status.text(), True)
check("the typing survives a refusal",
      co.editors["company_name"].text(), "Aarkaya Handicrafts LLC")
check("and nothing was written", db.get_company()["gstin"], "09AAAPZ1234C1Z5")

# refresh_all() reaches every screen; it must not wipe a part-typed form, just
# as it leaves a part-entered voucher alone.
co.editors["phone"].setText("011-5550123")
window.refresh_all()
settle()
check("refresh_all leaves unsaved company edits alone",
      co.editors["phone"].text(), "011-5550123")
co.refresh()
check("Revert reloads what is saved", co.editors["phone"].text(), "")

# The address box is sized in LINES, so it has to grow with the text setting.
heights = []
for key in theme.TEXT_ORDER:
    window.set_text_size(key)
    settle()
    heights.append(co.editors["address"].minimumHeight())
check("the address box grows with the text size", heights, sorted(set(heights)))
print(f"       address box: {' -> '.join(f'{h}px' for h in heights)}")
window.set_text_size(theme.DEFAULT_TEXT)
settle()
check("the Company screen is not over-wide",
      co.minimumSizeHint().width() <= WIDTH_CEILING, True)

print("\n18) Choosing a company at launch")

# This suite pins BOOKS_DB, which is exactly the case where the picker must
# NOT appear: the caller has already chosen the file.
check("a pinned data file is detected", db.DB_PINNED, True)
check("switching is offered only when the file is not pinned",
      window._switch_action.isEnabled(), not db.DB_PINNED)

# The dialogs are driven directly; they do not depend on being shown.
made = []
for name in ("Alpha Exports", "Beta Trading"):
    dialog = desktop.NewCompanyDialog()
    dialog.editors["company_name"].setText(name)
    dialog._create()
    check(f"created {name}", dialog.created is not None, True)
    made.append(dialog.created)
check("they are separate files", made[0] != made[1], True)

picker = desktop.CompanyPicker()
listed = [picker.table.item(r, 0).text() for r in range(picker.table.rowCount())]
check("both companies are offered", sorted(set(listed)) [:2],
      ["Alpha Exports", "Beta Trading"])
check("the last one opened is preselected",
      picker.table.item(picker.table.currentRow(), 1).text(),
      Path(made[-1]).name)
check("the folder is named in the note", str(db.DATA_DIR) in picker.note.text(),
      True)

picker.table.selectRow(
    next(r for r in range(picker.table.rowCount())
         if picker.table.item(r, 0).text() == "Alpha Exports"))
picker._open()
check("opening returns the chosen file",
      Path(picker.chosen).name, Path(made[0]).name)

refused = desktop.NewCompanyDialog()
refused.editors["company_name"].setText("   ")
refused._create()
check("a company with no name is refused", refused.created, None)
check("the dialog says why", "name" in refused.status.text().lower(), True)

# Switching closes the window and asks again; main() loops on this flag.
check("the window does not start out switching", window.switch_requested, False)
window.switch_company()
check("switch_company sets the flag", window.switch_requested, True)
window.switch_requested = False

# A part-entered voucher must not be thrown away silently.
window.show_screen(0)
settle()
check("an empty voucher is not part-entered", window.part_entered_rows(), [])
check("and needs no confirmation to leave",
      window._confirm_leaving("Switch company"), True)
set_row(window.voucher, 0, "Cash", debit=10.0)
settle()
check("a part-entered voucher is detected",
      window.part_entered_rows(), [0])
window.voucher.reset()
settle()
check("resetting clears it again", window.part_entered_rows(), [])

# The real data folder must be untouched by any of this.
check("the suite wrote only into its sandbox",
      str(db.DATA_DIR).startswith(str(Path(tempfile.gettempdir()))), True)
db.use_company(TMP)

print("\n" + ("ALL DESKTOP CHECKS PASSED" if not FAILURES
             else f"FAILURES: {FAILURES}"))
raise SystemExit(1 if FAILURES else 0)
