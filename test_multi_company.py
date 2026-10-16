"""Covers the UNPINNED path: more than one company, and choosing between them.

Run:  python test_multi_company.py

The other three suites set BOOKS_DB, which pins the data file and deliberately
switches the company picker off - so they exercise everything except the way
the app actually starts for a user. This one runs with BOOKS_DB unset and
BOOKS_DIR pointed at a scratch folder, which is the real launch path.

Both front ends are driven: the Qt picker and create dialog, and the Streamlit
sidebar selector, including that switching really does change which books are
being read rather than only the label at the top.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Unset, so db.DB_PINNED is False and the pickers are live. BOOKS_DIR keeps
# every company file inside a scratch folder - without it this suite would
# create companies in the user's real data/ directory.
os.environ.pop("BOOKS_DB", None)
SANDBOX = Path(tempfile.gettempdir()) / "bookkeeper_multi_company"
shutil.rmtree(SANDBOX, ignore_errors=True)
SANDBOX.mkdir(parents=True)
os.environ["BOOKS_DIR"] = str(SANDBOX)

from PySide6 import QtWidgets  # noqa: E402

import db  # noqa: E402
import desktop  # noqa: E402

FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        FAILURES.append(label)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

print("\n1) Nothing to open yet")
check("the data file is not pinned", db.DB_PINNED, False)
check("no companies to begin with", db.company_files(), [])
picker = desktop.CompanyPicker()
check("the picker says the folder is empty",
      "No companies yet" in picker.note.text(), True)
check("Open is disabled with nothing to open",
      picker.open_button.isEnabled(), False)

print("\n2) Creating two companies")
made = {}
for name in ("Alpha Exports", "Beta Trading"):
    dialog = desktop.NewCompanyDialog()
    dialog.editors["company_name"].setText(name)
    dialog.editors["currency"].setCurrentText("₹")
    dialog._create()
    check(f"{name} created", dialog.created is not None, True)
    made[name] = Path(dialog.created)
    # A ledger that exists ONLY here, to prove the books are separate.
    db.add_ledger(f"{name.split()[0]} Only", "Indirect Expenses")
check("each has its own file",
      len({p.name for p in made.values()}), 2)
check("the file name follows the company name",
      made["Alpha Exports"].name, "alpha-exports.db")

print("\n3) The books really are separate")
db.use_company(made["Alpha Exports"])
alpha = list(db.get_ledgers()["name"])
db.use_company(made["Beta Trading"])
beta = list(db.get_ledgers()["name"])
check("Alpha has its own ledger", "Alpha Only" in alpha, True)
check("and not Beta's", "Beta Only" in alpha, False)
check("Beta has its own ledger", "Beta Only" in beta, True)
check("and not Alpha's", "Alpha Only" in beta, False)

print("\n4) The picker lists and preselects")
db.remember_last_company(made["Alpha Exports"])
picker = desktop.CompanyPicker()
rows = {picker.table.item(r, 0).text(): picker.table.item(r, 1).text()
        for r in range(picker.table.rowCount())}
check("both are listed", sorted(rows), ["Alpha Exports", "Beta Trading"])
check("the one opened last is preselected",
      picker.table.item(picker.table.currentRow(), 0).text(), "Alpha Exports")
picker.table.selectRow(
    next(r for r in range(picker.table.rowCount())
         if picker.table.item(r, 0).text() == "Beta Trading"))
picker._open()
check("opening returns that company's file",
      Path(picker.chosen).name, made["Beta Trading"].name)

print("\n5) The picker wears the look of the company opened last")
db.use_company(made["Alpha Exports"])
window = desktop.MainWindow()
window.set_color_scheme("classic")
window.set_text_size("largest")
db.remember_last_company(made["Alpha Exports"])
window.close()
import theme  # noqa: E402
theme.apply(app, "light")
theme.apply_font(app, "normal")
chosen_look = db.peek_settings(
    made["Alpha Exports"], (theme.SETTING_KEY, theme.FONT_SETTING_KEY))
check("the scheme was stored in that company's file",
      chosen_look.get(theme.SETTING_KEY), "classic")
check("and so was the text size",
      chosen_look.get(theme.FONT_SETTING_KEY), "largest")
theme.apply(app, chosen_look[theme.SETTING_KEY])
theme.apply_font(app, chosen_look[theme.FONT_SETTING_KEY])
check("so the picker can open in it",
      QtWidgets.QApplication.palette().color(
          QtWidgets.QApplication.palette().ColorRole.Window).name(),
      theme.SCHEMES["classic"].window)

print("\n6) Switching company from inside the window")
db.use_company(made["Beta Trading"])
window = desktop.MainWindow()
check("switching is offered when the file is not pinned",
      window._switch_action.isEnabled(), True)
check("not switching to begin with", window.switch_requested, False)
window.switch_company()
check("switch sets the flag main() loops on", window.switch_requested, True)
window.close()

print("\n7) A backup in the data folder is not a company")
shutil.copyfile(made["Alpha Exports"],
                SANDBOX / "alpha-exports.backup-20261016-120000.db")
listed = [c["file"] for c in db.list_companies()]
check("the backup is not offered", any("backup" in f for f in listed), False)
check("the two real companies still are", len(listed), 2)

print("\n8) The Streamlit sidebar switches books too")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).with_name("app.py")
at = AppTest.from_file(str(APP), default_timeout=180).run()
assert not at.exception, at.exception
selector = next((s for s in at.selectbox if s.key == "company_file"), None)
check("a company selector is rendered", selector is not None, True)
check("it offers both companies", len(list(selector.options)), 2)


def shown(app_test):
    """Everything the page prints, to see WHICH company is on screen."""
    parts = [m.value for m in app_test.markdown if isinstance(m.value, str)]
    parts += [t.value for t in app_test.title if isinstance(t.value, str)]
    parts += [h.value for h in app_test.header if isinstance(h.value, str)]
    return " ".join(parts)


at = selector.set_value(made["Alpha Exports"].name).run()
assert not at.exception, at.exception
page = shown(at)
check("picking Alpha shows Alpha", "Alpha Exports" in page, True)
check("and not Beta", "Beta Trading" in page, False)

selector = next(s for s in at.selectbox if s.key == "company_file")
at = selector.set_value(made["Beta Trading"].name).run()
assert not at.exception, at.exception
page = shown(at)
check("picking Beta shows Beta", "Beta Trading" in page, True)
check("and not Alpha", "Alpha Exports" in page, False)

print("\n9) Nothing escaped the sandbox")
check("every company file is in the scratch folder",
      all(str(p).startswith(str(SANDBOX)) for p in db.company_files()), True)

print("\n" + ("ALL MULTI-COMPANY CHECKS PASSED" if not FAILURES
             else f"FAILURES: {FAILURES}"))
raise SystemExit(1 if FAILURES else 0)
