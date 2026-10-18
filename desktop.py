"""Tally-style bookkeeping — native desktop app (PySide6/Qt).

    python desktop.py

This is a second front end over the same books. ``db.py`` and ``accounting.py``
are shared with the Streamlit version untouched, and both read the same
``data/books.db``, so you can use whichever suits the moment.

Why a desktop build exists at all: voucher entry wants a grid that responds to
every keystroke without a round trip, and function keys that switch voucher
type the way Tally's do. Keyboard map follows Tally where it sensibly can:

    F4 Contra   F5 Payment   F6 Receipt   F7 Journal   F8 Sales   F9 Purchase
    Ctrl+A            accept the voucher
    Ctrl+1..8         jump between screens (8 = Company details)
    Ctrl+S            save the company details, on that screen
    F2                set the voucher date
    Esc               back to voucher entry
    Ctrl+Shift+1..5   colour scheme (also under Settings > Colour scheme)
    Ctrl+= / Ctrl+-   text bigger / smaller (Settings > Text size)

Colours and text sizes live in ``theme.py``, never inline here: both are
switchable at runtime, so a hardcoded ``#666`` would be unreadable the moment
someone picks a dark scheme, and a hardcoded point size would ignore the text
setting. Build fonts with ``mono_font()`` / ``heading()``, not ``QFont(...)``.
"""

from __future__ import annotations

import calendar
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

import accounting as acc
import db
import theme

MONO = "Consolas, 'Courier New', monospace"

# Tally's function keys for voucher types
VOUCHER_KEYS = {
    "F4": "Contra", "F5": "Payment", "F6": "Receipt",
    "F7": "Journal", "F8": "Sales", "F9": "Purchase",
}


def money(value: float) -> str:
    symbol = db.get_setting("currency", "₹")
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"


def to_qdate(value) -> QtCore.QDate:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return QtCore.QDate(value.year, value.month, value.day)


def from_qdate(value: QtCore.QDate) -> date:
    return date(value.year(), value.month(), value.day())


def parse_amount(text: str) -> float:
    """Read an amount typed with or without separators. Blank means zero."""
    cleaned = (text or "").strip().replace(",", "")
    if not cleaned:
        return 0.0
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# a read-only table built from a DataFrame
# --------------------------------------------------------------------------- #
class FrameTable(QtWidgets.QTableWidget):
    """Displays a DataFrame. Numeric columns are right-aligned and formatted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(False)

    def load(self, frame: pd.DataFrame, numeric: tuple[str, ...] = (),
             bold_last: bool = False) -> None:
        frame = frame.reset_index(drop=True)
        self.clear()
        self.setRowCount(len(frame))
        self.setColumnCount(len(frame.columns))
        self.setHorizontalHeaderLabels([str(c) for c in frame.columns])

        for row in range(len(frame)):
            for col, column in enumerate(frame.columns):
                raw = frame.iloc[row, col]
                if column in numeric:
                    number = 0.0 if pd.isna(raw) else float(raw)
                    text = "" if abs(number) < 0.005 else f"{number:,.2f}"
                    item = QtWidgets.QTableWidgetItem(text)
                    item.setTextAlignment(QtCore.Qt.AlignRight
                                          | QtCore.Qt.AlignVCenter)
                    item.setFont(mono_font())
                else:
                    item = QtWidgets.QTableWidgetItem(
                        "" if pd.isna(raw) else str(raw))
                if bold_last and row == len(frame) - 1:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.setItem(row, col, item)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        if len(frame.columns):
            widest = max(range(len(frame.columns)),
                         key=lambda i: 1 if frame.columns[i] in numeric else 2)
            header.setSectionResizeMode(widest, QtWidgets.QHeaderView.Stretch)


def mono_font() -> QtGui.QFont:
    """A monospaced font AT THE CURRENT TEXT SIZE.

    ``QFont(MONO)`` does not inherit the application font's size - it comes
    back at a system default of 12pt - so building one without passing a size
    leaves the amount columns ignoring the text-size setting, and looking
    smaller than their surroundings once the body text grows.
    """
    return QtGui.QFont(MONO, theme.point_size())


def apply_mono(widget) -> None:
    """Give a widget the monospaced font and mark it, so a later text-size
    change can find it again."""
    widget.setFont(mono_font())
    widget.setProperty("mono", True)


def fit_lines(widget) -> None:
    """Size a multi-line box in LINES of the current font, not pixels.

    Marked with a ``lines`` property so a text-size change can re-measure it;
    a pixel height would clip the text at the larger sizes.

    Measured against ``theme.point_size()`` rather than ``widget.font()``:
    ``app.setFont()`` propagates through a POSTED event, so a widget asked
    straight afterwards still reports its old font and the box would be
    measured with stale metrics - which is exactly what left it unchanged.
    """
    rows = int(widget.property("lines") or 3)
    font = widget.font()
    font.setPointSize(theme.point_size())
    metrics = QtGui.QFontMetrics(font)
    widget.setMinimumHeight(metrics.lineSpacing() * rows + 12)


def editor_for(field) -> QtWidgets.QWidget:
    """The right editor for a ``db.CompanyField``.

    Shared by the Company screen and the create-company dialog, so the two
    present the same field the same way.
    """
    if field.kind == "multiline":
        editor = QtWidgets.QPlainTextEdit()
        editor.setPlaceholderText(field.hint)
        editor.setProperty("lines", 3)
        fit_lines(editor)
        return editor
    if field.kind == "month":
        editor = QtWidgets.QComboBox()
        for month in range(1, 13):
            editor.addItem(calendar.month_name[month], month)
        return editor
    if field.kind == "date":
        editor = QtWidgets.QDateEdit()
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("dd/MM/yyyy")
        return editor
    if field.kind == "choice":
        editor = QtWidgets.QComboBox()
        editor.setEditable(True)            # so an unlisted symbol still works
        editor.addItems(list(field.choices))
        return editor
    editor = QtWidgets.QLineEdit()
    editor.setPlaceholderText(field.hint)
    return editor


def flowing(label: QtWidgets.QLabel) -> QtWidgets.QLabel:
    """A label that WRAPS rather than pinning the window open.

    An unwrapped label's minimum width is the width of its entire text, and a
    window can never be narrower than its widest unwrapped label. The report
    captions carry long sentences and formatted figures, so left unwrapped they
    forced the window wider at every step of text size - one of them was
    demanding 1770px on its own. Use this for anything whose text is set at
    refresh and could run long.
    """
    label.setWordWrap(True)
    return label


def heading(text: str, size: int | None = None) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    font = label.font()
    font.setPointSize(size if size else theme.heading_point_size())
    font.setBold(True)
    label.setFont(font)
    # Marked so a text-size change can resize it: the point size is set here,
    # once, which means it would otherwise never follow the application font.
    label.setProperty("heading", True)
    return label


def muted(label: QtWidgets.QLabel) -> QtWidgets.QLabel:
    """Guidance text, coloured by the active scheme.

    Styled by object name rather than inline, because these labels are set up
    once in a constructor and never written to again - the stylesheet repaints
    them when the scheme changes, with nothing to re-run.
    """
    label.setObjectName("muted")
    return label


def tone(label: QtWidgets.QLabel, token: str) -> None:
    """Colour a status label by MEANING - good, bad, warn, muted.

    The token is also stored on the widget, so ``MainWindow._repaint_tones``
    can recolour it after a scheme change without recomputing the report that
    produced the message.
    """
    label.setProperty("tone", token)
    label.setStyleSheet(theme.fg(token))


def totals_bar(*pairs: tuple[str, str]) -> QtWidgets.QWidget:
    """A right-aligned row of label/value pairs, for report footers."""
    box = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.addStretch(1)
    for label, value in pairs:
        cell = QtWidgets.QLabel(f"{label}  <b>{value}</b>")
        apply_mono(cell)
        layout.addWidget(cell)
        layout.addSpacing(18)
    return box


# --------------------------------------------------------------------------- #
# create-master dialogs, reachable mid-voucher the way Tally's Alt+C is
# --------------------------------------------------------------------------- #
class GroupDialog(QtWidgets.QDialog):
    """Create a sub-group without leaving whatever you were doing."""

    def __init__(self, parent=None, under: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Create Group")
        self.created: str | None = None

        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("e.g. Vehicle Loan")
        form.addRow("Name", self.name)

        self.parent_box = QtWidgets.QComboBox()
        self.parent_box.setEditable(True)
        self.parent_box.completer().setFilterMode(QtCore.Qt.MatchContains)
        names = list(db.get_groups()["name"])
        self.parent_box.addItems(names)
        if under in names:
            self.parent_box.setCurrentText(under)
        form.addRow("Under", self.parent_box)

        note = QtWidgets.QLabel(
            "A sub-group inherits its parent's nature, so it lands on the same "
            "statement.")
        note.setWordWrap(True)
        muted(note)
        form.addRow(note)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.name.setFocus()

    def _create(self) -> None:
        try:
            db.add_group(self.name.text(), self.parent_box.currentText())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Cannot create group", str(exc))
            return
        self.created = self.name.text().strip()
        self.accept()


class LedgerDialog(QtWidgets.QDialog):
    """Create a ledger mid-voucher, including its group if that is missing too."""

    def __init__(self, parent=None, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Create Ledger")
        self.created: str | None = None

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(name)
        self.name.setPlaceholderText("e.g. Bank of India")
        form.addRow("Name", self.name)

        # built before _load_groups(), which describes the chosen group into it
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        muted(self.note)

        under_row = QtWidgets.QHBoxLayout()
        self.group_box = QtWidgets.QComboBox()
        self.group_box.setEditable(True)
        self.group_box.completer().setFilterMode(QtCore.Qt.MatchContains)
        self._load_groups()
        under_row.addWidget(self.group_box, 1)
        new_group = QtWidgets.QPushButton("New group…")
        new_group.clicked.connect(self._new_group)
        under_row.addWidget(new_group)
        under_holder = QtWidgets.QWidget()
        under_holder.setLayout(under_row)
        form.addRow("Under", under_holder)

        opening_row = QtWidgets.QHBoxLayout()
        self.opening = QtWidgets.QDoubleSpinBox()
        self.opening.setRange(0, 1e12)
        self.opening.setDecimals(2)
        self.opening.setGroupSeparatorShown(True)
        self.side = QtWidgets.QComboBox()
        self.side.addItems(list(db.SIDES))
        opening_row.addWidget(self.opening, 1)
        opening_row.addWidget(self.side)
        opening_holder = QtWidgets.QWidget()
        opening_holder.setLayout(opening_row)
        form.addRow("Opening balance", opening_holder)
        layout.addLayout(form)

        layout.addWidget(self.note)
        self.group_box.currentTextChanged.connect(self._describe)
        self._describe()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        (self.group_box if name else self.name).setFocus()

    def _load_groups(self, select: str | None = None) -> None:
        current = select or self.group_box.currentText()
        names = list(db.get_groups()["name"])
        self.group_box.blockSignals(True)
        self.group_box.clear()
        self.group_box.addItems(names)
        if current in names:
            self.group_box.setCurrentText(current)
        self.group_box.blockSignals(False)
        self._describe()

    def _new_group(self) -> None:
        dialog = GroupDialog(self, under=self.group_box.currentText())
        if dialog.exec() and dialog.created:
            self._load_groups(select=dialog.created)

    def _describe(self) -> None:
        """Say in plain words where this ledger's balance will show up."""
        groups = db.get_groups().set_index("name")
        chosen = self.group_box.currentText()
        if chosen not in groups.index:
            self.note.setText("")
            return
        nature = str(groups.loc[chosen, "nature"])
        trading = bool(groups.loc[chosen, "affects_gross"])
        where = {
            "asset": "the assets side of the Balance Sheet",
            "liability": "the liabilities side of the Balance Sheet",
            "income": ("the trading account" if trading
                       else "the indirect incomes"),
            "expense": ("the trading account" if trading
                        else "the indirect expenses"),
        }[nature]
        self.note.setText(f"A {nature} account — its balance will appear in {where}.")

    def _create(self) -> None:
        try:
            db.add_ledger(self.name.text(), self.group_box.currentText(),
                          self.opening.value(), self.side.currentText())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Cannot create ledger", str(exc))
            return
        self.created = self.name.text().strip()
        self.accept()


# --------------------------------------------------------------------------- #
# voucher entry
# --------------------------------------------------------------------------- #
class VoucherScreen(QtWidgets.QWidget):
    """The screen you live in: type, date, number, then a Dr/Cr grid."""

    posted = QtCore.Signal()
    masters_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editing_id: int | None = None
        layout = QtWidgets.QVBoxLayout(self)

        self.title = heading("Voucher Entry")
        layout.addWidget(self.title)

        # --- header row ---
        head = QtWidgets.QHBoxLayout()
        self.type_box = QtWidgets.QComboBox()
        self.type_box.addItems(list(db.VOUCHER_TYPES))
        self.type_box.currentTextChanged.connect(self._type_changed)
        head.addWidget(QtWidgets.QLabel("Type"))
        head.addWidget(self.type_box)

        self.date_edit = QtWidgets.QDateEdit(to_qdate(date.today()))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        head.addWidget(QtWidgets.QLabel("Date"))
        head.addWidget(self.date_edit)

        self.number_label = QtWidgets.QLabel()
        apply_mono(self.number_label)
        head.addWidget(self.number_label)
        head.addStretch(1)
        self.hint = flowing(QtWidgets.QLabel())
        muted(self.hint)
        head.addWidget(self.hint)
        layout.addLayout(head)

        narration_row = QtWidgets.QHBoxLayout()
        narration_row.addWidget(QtWidgets.QLabel("Narration"))
        self.narration = QtWidgets.QLineEdit()
        self.narration.setPlaceholderText("what this entry is for")
        narration_row.addWidget(self.narration)
        layout.addLayout(narration_row)

        # --- grid ---
        self.grid = QtWidgets.QTableWidget(0, 3)
        self.grid.setHorizontalHeaderLabels(["Particulars", "Debit", "Credit"])
        self.grid.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        self.grid.verticalHeader().setVisible(False)
        self.grid.itemChanged.connect(self._recalculate)
        layout.addWidget(self.grid, 1)

        buttons = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add line")
        add.clicked.connect(lambda: self._add_row())
        remove = QtWidgets.QPushButton("Remove line")
        remove.clicked.connect(self._remove_row)
        create = QtWidgets.QPushButton("Create ledger  (Alt+C)")
        create.setToolTip("Create a ledger without leaving this voucher, the "
                          "way Tally's Alt+C does")
        create.clicked.connect(self.create_ledger)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addWidget(create)
        buttons.addStretch(1)
        self.dr_label = QtWidgets.QLabel()
        self.cr_label = QtWidgets.QLabel()
        self.gap_label = QtWidgets.QLabel()
        for widget in (self.dr_label, self.cr_label, self.gap_label):
            apply_mono(widget)
            buttons.addWidget(widget)
            buttons.addSpacing(14)
        layout.addLayout(buttons)

        self.notice = QtWidgets.QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        self.accept_button = QtWidgets.QPushButton("Accept  (Ctrl+A)")
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self.accept_voucher)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch(1)
        self.cancel_button = QtWidgets.QPushButton("Cancel edit")
        self.cancel_button.clicked.connect(self.reset)
        self.cancel_button.setVisible(False)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.accept_button)
        layout.addLayout(bottom)

        shortcut = QtGui.QShortcut(QtGui.QKeySequence("Alt+C"), self)
        shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.create_ledger)

        self.reset()

    # --- grid plumbing ------------------------------------------------- #
    def _ledger_combo(self) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setEditable(True)
        combo.addItem("")
        combo.addItems(self._ledger_names)
        combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        completer = combo.completer()
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        combo.currentTextChanged.connect(self._recalculate)
        return combo

    def _add_row(self, ledger: str = "", debit: float = 0.0,
                 credit: float = 0.0) -> None:
        row = self.grid.rowCount()
        self.grid.insertRow(row)
        combo = self._ledger_combo()
        if ledger:
            combo.setCurrentText(ledger)
        self.grid.setCellWidget(row, 0, combo)
        for col, value in ((1, debit), (2, credit)):
            item = QtWidgets.QTableWidgetItem("" if not value else f"{value:,.2f}")
            item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            item.setFont(mono_font())
            self.grid.setItem(row, col, item)
        self._recalculate()

    def _remove_row(self) -> None:
        if self.grid.rowCount() > 2:
            self.grid.removeRow(self.grid.currentRow()
                                if self.grid.currentRow() >= 0
                                else self.grid.rowCount() - 1)
            self._recalculate()

    def row_values(self) -> list[dict]:
        rows = []
        for row in range(self.grid.rowCount()):
            combo = self.grid.cellWidget(row, 0)
            name = combo.currentText().strip() if combo else ""
            debit = parse_amount(self.grid.item(row, 1).text()
                                 if self.grid.item(row, 1) else "")
            credit = parse_amount(self.grid.item(row, 2).text()
                                  if self.grid.item(row, 2) else "")
            if not name or (not debit and not credit):
                continue
            if name not in self._ledger_ids:
                continue
            rows.append({"ledger_id": self._ledger_ids[name],
                         "debit": debit, "credit": credit})
        return rows

    def _recalculate(self, *_args) -> None:
        if getattr(self, "_loading", False):
            return
        rows = self.row_values()
        debit = round(sum(r["debit"] for r in rows), 2)
        credit = round(sum(r["credit"] for r in rows), 2)
        gap = round(debit - credit, 2)

        self.dr_label.setText(f"Dr {debit:,.2f}")
        self.cr_label.setText(f"Cr {credit:,.2f}")
        self.gap_label.setText(f"Difference {gap:,.2f}")
        tone(self.gap_label,
             "good" if abs(gap) <= 0.005 and debit > 0 else "bad")

        balanced = abs(gap) <= 0.005 and debit > 0 and len(rows) >= 2
        distinct = len({r["ledger_id"] for r in rows}) >= 2
        self.accept_button.setEnabled(balanced and distinct)

        notes = db.voucher_type_warnings(
            self.type_box.currentText(), rows, self._ledgers)
        if not rows:
            self.notice.setText(
                "Pick a ledger on each line, then put the amount under Debit or "
                "Credit — never both on one line.")
            tone(self.notice, "muted")
        elif not balanced or not distinct:
            self.notice.setText("Debit and credit must agree, across at least "
                                "two different ledgers.")
            tone(self.notice, "bad")
        elif notes:
            self.notice.setText("ℹ️  " + "  ".join(notes))
            tone(self.notice, "warn")
        else:
            self.notice.setText("Debit equals credit — ready to accept.")
            tone(self.notice, "good")

        # keep a spare blank line at the bottom, the way Tally does
        last = self.grid.rowCount() - 1
        combo = self.grid.cellWidget(last, 0)
        if combo and combo.currentText().strip() and self.grid.rowCount() < 30:
            self._add_row()

    def _type_changed(self, name: str) -> None:
        if self.editing_id is None:
            self.number_label.setText(
                f"No. {db.next_voucher_number(name)}")
        self.hint.setText(db.VOUCHER_TYPES.get(name, ""))
        self._recalculate()

    # --- actions ------------------------------------------------------- #
    def create_ledger(self) -> None:
        """Tally's Alt+C: make the ledger here, then use it on this line.

        Whatever has been typed into the current cell is carried into the
        dialog as the name, so a half-typed account is not wasted.
        """
        row = self.grid.currentRow()
        if row < 0:
            row = self._first_empty_row()
        combo = self.grid.cellWidget(row, 0) if row >= 0 else None
        typed = combo.currentText().strip() if combo else ""
        if typed in self._ledger_ids:
            typed = ""   # already a real ledger, so start the dialog empty

        dialog = LedgerDialog(self, name=typed)
        if not dialog.exec() or not dialog.created:
            return

        self._add_ledger_name(dialog.created)
        if combo is not None:
            self._loading = True
            combo.setCurrentText(dialog.created)
            self._loading = False
        self._recalculate()
        self.masters_changed.emit()
        window = self.window()
        if isinstance(window, QtWidgets.QMainWindow):
            window.statusBar().showMessage(
                f"Ledger '{dialog.created}' created and selected.", 6000)

    def _first_empty_row(self) -> int:
        for row in range(self.grid.rowCount()):
            combo = self.grid.cellWidget(row, 0)
            if combo and not combo.currentText().strip():
                return row
        return self.grid.rowCount() - 1

    def _add_ledger_name(self, name: str) -> None:
        """Offer a newly created ledger on every line, without losing entries."""
        self.reload_ledgers()
        self._loading = True
        for row in range(self.grid.rowCount()):
            combo = self.grid.cellWidget(row, 0)
            if combo and combo.findText(name) < 0:
                combo.addItem(name)
        self._loading = False

    def reload_ledgers(self) -> None:
        self._ledgers = db.get_ledgers()
        self._ledger_names = list(self._ledgers["name"])
        self._ledger_ids = dict(zip(self._ledgers["name"],
                                    self._ledgers["id"].astype(int)))

    def reset(self) -> None:
        self._loading = True
        self.reload_ledgers()
        self.editing_id = None
        self.title.setText("Voucher Entry")
        self.cancel_button.setVisible(False)
        self.narration.clear()
        self.date_edit.setDate(to_qdate(date.today()))
        self.grid.setRowCount(0)
        self._loading = False
        self._add_row()
        self._add_row()
        self._type_changed(self.type_box.currentText())

    def load_voucher(self, voucher_id: int) -> None:
        record = db.get_voucher(voucher_id)
        if not record:
            return
        head, lines = record
        self._loading = True
        self.reload_ledgers()
        self.editing_id = int(head["id"])
        self.title.setText(
            f"Altering {head['voucher_type']} voucher no. {head['number']}")
        self.cancel_button.setVisible(True)
        self.type_box.setCurrentText(str(head["voucher_type"]))
        self.date_edit.setDate(to_qdate(str(head["voucher_date"])))
        self.narration.setText(str(head["narration"]))
        self.number_label.setText(f"No. {head['number']}")
        self.grid.setRowCount(0)
        self._loading = False
        for line in lines:
            self._add_row(str(line["ledger_name"]), float(line["debit"]),
                          float(line["credit"]))
        self._recalculate()

    def accept_voucher(self) -> None:
        rows = self.row_values()
        try:
            db.save_voucher(
                voucher_type=self.type_box.currentText(),
                voucher_date=from_qdate(self.date_edit.date()),
                narration=self.narration.text(),
                lines=rows,
                voucher_id=self.editing_id,
            )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Cannot accept", str(exc))
            return
        total = sum(r["debit"] for r in rows)
        was_editing = self.editing_id is not None
        self.reset()
        self.posted.emit()
        window = self.window()
        if isinstance(window, QtWidgets.QMainWindow):
            window.statusBar().showMessage(
                ("Voucher altered — " if was_editing else "Voucher accepted — ")
                + money(total), 6000)


# --------------------------------------------------------------------------- #
# report screens
# --------------------------------------------------------------------------- #
class PeriodBar(QtWidgets.QWidget):
    """Which period a report covers: pick a financial year, or set dates.

    The year dropdown is the quick path - "the Balance Sheet for 2025-2026" is
    how the question is actually asked, and reaching it by typing two dates is
    needless work. The dates stay, because a period that is not a whole year
    (a quarter, a month, up to yesterday) still has to be reachable.

    The two cannot be allowed to disagree: editing a date by hand moves the
    dropdown to **Custom dates**, because leaving it reading "FY 2026-2027"
    over a period that is no longer that year would be a lie about what you
    are looking at.
    """

    changed = QtCore.Signal()

    SINCE = "Since books began"
    CUSTOM = "Custom dates"
    # Marks the since-books-began entry. The years carry a FinancialYear and
    # Custom carries None, so the three are told apart by what they hold
    # rather than by their position in a list that changes with the data.
    ALL = "all"

    def __init__(self, with_from: bool = True, parent=None):
        super().__init__(parent)
        self.with_from = with_from
        # Set while the bar updates its own dates, so that the handlers which
        # watch for YOUR edits do not fire for ours - without it, choosing a
        # year would immediately flip the dropdown to Custom.
        self._quiet = False
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QtWidgets.QLabel("Period"))
        self.year_box = QtWidgets.QComboBox()
        self.year_box.setToolTip(
            "The financial year to report on. The years come from the books, "
            "and the month one opens on is set on the Company screen.")
        self.year_box.currentIndexChanged.connect(self._year_chosen)
        row.addWidget(self.year_box)

        if with_from:
            row.addWidget(QtWidgets.QLabel("From"))
            self.from_edit = QtWidgets.QDateEdit()
            self.from_edit.setCalendarPopup(True)
            self.from_edit.setDisplayFormat("dd/MM/yyyy")
            self.from_edit.dateChanged.connect(self._date_typed)
            row.addWidget(self.from_edit)

        row.addWidget(QtWidgets.QLabel("To"))
        self.to_edit = QtWidgets.QDateEdit(to_qdate(date.today()))
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_edit.dateChanged.connect(self._date_typed)
        row.addWidget(self.to_edit)

        row.addStretch(1)

        self.reload_years()

    # --- the year list ---------------------------------------------------- #
    def reload_years(self) -> None:
        """(Re)fill the dropdown from the books, keeping the year selected.

        Called again whenever the books change under it - another company
        opened, or the financial-year start month edited on the Company
        screen - because both change what the years ARE. Matching on the
        label rather than the index means a year that still exists stays
        selected even though the list around it has moved.
        """
        wanted = self.year_box.currentText()
        years = acc.financial_years()

        self._quiet = True
        self.year_box.clear()
        # Since-books-began lives in this dropdown rather than beside it as a
        # tickbox: it is one of the periods you can choose, and a row holding
        # both was 1468px wide at the largest text size - wider than the
        # 1400px ceiling the whole app has to fit inside.
        if self.with_from:
            self.year_box.addItem(self.SINCE, self.ALL)
        for year in years:
            self.year_box.addItem(f"FY {year.label}", year)
        self.year_box.addItem(self.CUSTOM, None)

        index = self.year_box.findText(wanted) if wanted else -1
        if index < 0:
            current = acc.current_financial_year()
            index = max(0, self.year_box.findText(f"FY {current.label}"))
        self.year_box.setCurrentIndex(index)
        self._quiet = False
        self._apply(self.year_box.currentData())

    def _year_chosen(self, _index: int) -> None:
        if self._quiet:
            return
        self._apply(self.year_box.currentData())

    def _apply(self, chosen) -> None:
        """Put the chosen period's dates into the editors, then report it.

        ``None`` is Custom, which means leave the dates exactly as they are -
        the point of Custom is that you set them.
        """
        if chosen is None:
            self.changed.emit()
            return
        self._quiet = True
        if chosen == self.ALL:
            # No start date at all, so the From editor has nothing to say.
            if self.with_from:
                self.from_edit.setEnabled(False)
            self.to_edit.setDate(to_qdate(date.today()))
        else:
            if self.with_from:
                self.from_edit.setEnabled(True)
                self.from_edit.setDate(to_qdate(chosen.start))
            # The year in progress runs to TODAY, not to its close: a balance
            # sheet dated next March, with nothing posted between, tells you
            # nothing you did not already know.
            self.to_edit.setDate(to_qdate(min(chosen.end, date.today())))
        self._quiet = False
        self.changed.emit()

    def _date_typed(self, *_) -> None:
        """A date changed by hand: the period is no longer a whole year."""
        if self._quiet:
            return
        self._mark_custom()
        self.changed.emit()

    def _mark_custom(self) -> None:
        index = self.year_box.findText(self.CUSTOM)
        if index >= 0 and self.year_box.currentIndex() != index:
            self._quiet = True
            self.year_box.setCurrentIndex(index)
            self._quiet = False

    def selected_year(self):
        """The chosen financial year, or None for custom or all dates."""
        chosen = self.year_box.currentData()
        return chosen if isinstance(chosen, acc.FinancialYear) else None

    def range(self) -> tuple[date | None, date]:
        """The period, as ``accounting`` wants it: None means no start date."""
        if self.year_box.currentData() == self.ALL or not self.with_from:
            return None, from_qdate(self.to_edit.date())
        return from_qdate(self.from_edit.date()), from_qdate(self.to_edit.date())


class DayBookScreen(QtWidgets.QWidget):
    open_voucher = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Day Book"))
        self.period = PeriodBar()
        self.period.changed.connect(self.refresh)
        layout.addWidget(self.period)

        filters = QtWidgets.QHBoxLayout()
        filters.addWidget(QtWidgets.QLabel("Type"))
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItems(["All"] + list(db.VOUCHER_TYPES))
        self.type_filter.currentTextChanged.connect(self.refresh)
        filters.addWidget(self.type_filter)
        filters.addStretch(1)
        self.count = flowing(QtWidgets.QLabel())
        filters.addWidget(self.count)
        layout.addLayout(filters)

        self.table = FrameTable()
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table, 1)
        layout.addWidget(QtWidgets.QLabel(
            "Double-click a voucher to alter it."))
        self._frame = pd.DataFrame()

    def refresh(self) -> None:
        start, end = self.period.range()
        frame = acc.day_book(start, end)
        kind = self.type_filter.currentText()
        if kind != "All" and not frame.empty:
            frame = frame[frame["Vch Type"] == kind]
        self._frame = frame.reset_index(drop=True)
        self.count.setText(f"{len(self._frame)} voucher(s)")
        shown = self._frame.drop(columns=["voucher_id"]) if not frame.empty \
            else pd.DataFrame(columns=["Date", "Particulars", "Vch Type",
                                       "Vch No", "Debit", "Credit"])
        self.table.load(shown, numeric=("Debit", "Credit"))

    def _open(self, index) -> None:
        if 0 <= index.row() < len(self._frame):
            self.open_voucher.emit(int(self._frame.iloc[index.row()]["voucher_id"]))


class LedgerScreen(QtWidgets.QWidget):
    open_voucher = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Ledger"))

        picker = QtWidgets.QHBoxLayout()
        picker.addWidget(QtWidgets.QLabel("Account"))
        self.ledger_box = QtWidgets.QComboBox()
        self.ledger_box.setEditable(True)
        self.ledger_box.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.ledger_box.currentTextChanged.connect(self.refresh)
        picker.addWidget(self.ledger_box, 1)
        layout.addLayout(picker)

        self.period = PeriodBar()
        self.period.changed.connect(self.refresh)
        layout.addWidget(self.period)

        self.caption = flowing(QtWidgets.QLabel())
        layout.addWidget(self.caption)
        self.table = FrameTable()
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table, 1)
        self.footer = QtWidgets.QWidget()
        self.footer_slot = QtWidgets.QVBoxLayout()
        self.footer_slot.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.footer_slot)
        self._frame = pd.DataFrame()

    def reload_ledgers(self) -> None:
        current = self.ledger_box.currentText()
        names = list(db.get_ledgers(include_inactive=True)["name"])
        self.ledger_box.blockSignals(True)
        self.ledger_box.clear()
        self.ledger_box.addItems(names)
        if current in names:
            self.ledger_box.setCurrentText(current)
        self.ledger_box.blockSignals(False)

    def refresh(self) -> None:
        name = self.ledger_box.currentText()
        ledgers = db.get_ledgers(include_inactive=True).set_index("name")
        if name not in ledgers.index:
            self.caption.setText("Pick an account.")
            self.table.load(pd.DataFrame())
            return
        start, end = self.period.range()
        statement = acc.ledger_statement(int(ledgers.loc[name, "id"]), start, end)
        self.caption.setText(
            f"<b>{statement['ledger']}</b> &nbsp; under {statement['group']}"
            f" &nbsp;·&nbsp; Opening {acc.fmt_side(statement['opening'])}"
            f" &nbsp;·&nbsp; Closing <b>{acc.fmt_side(statement['closing'])}</b>")
        self._frame = statement["entries"].reset_index(drop=True)
        shown = self._frame.drop(columns=["voucher_id"]) if not self._frame.empty \
            else pd.DataFrame(columns=["Date", "Particulars", "Vch Type",
                                       "Vch No", "Debit", "Credit", "Balance"])
        self.table.load(shown, numeric=("Debit", "Credit"))

        while self.footer_slot.count():
            item = self.footer_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.footer_slot.addWidget(totals_bar(
            ("Debit", f"{statement['debit_total']:,.2f}"),
            ("Credit", f"{statement['credit_total']:,.2f}"),
            ("Closing", acc.fmt_side(statement["closing"]))))

    def _open(self, index) -> None:
        if 0 <= index.row() < len(self._frame):
            self.open_voucher.emit(int(self._frame.iloc[index.row()]["voucher_id"]))


class TrialBalanceScreen(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Trial Balance"))
        self.period = PeriodBar(with_from=False)
        self.period.changed.connect(self.refresh)
        layout.addWidget(self.period)
        self.by_group = QtWidgets.QCheckBox("Summarise by group")
        self.by_group.toggled.connect(self.refresh)
        layout.addWidget(self.by_group)
        self.status = flowing(QtWidgets.QLabel())
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = FrameTable()
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        _, as_at = self.period.range()
        trial = acc.trial_balance(as_at, by_group=self.by_group.isChecked())
        rows = trial["rows"]
        if rows.empty:
            self.table.load(pd.DataFrame(columns=["Particulars", "Debit", "Credit"]),
                            numeric=("Debit", "Credit"))
        else:
            total = {"Particulars": "Total", "Debit": trial["debit"],
                     "Credit": trial["credit"]}
            if "Under" in rows.columns:
                total["Under"] = ""
            shown = pd.concat([rows, pd.DataFrame([total])], ignore_index=True)
            self.table.load(shown, numeric=("Debit", "Credit"), bold_last=True)

        if abs(trial["difference"]) <= acc.EPS:
            self.status.setText("Debits equal credits.")
            tone(self.status, "good")
        else:
            self.status.setText(
                f"Out by {money(abs(trial['difference']))} — this is the "
                "difference in opening balances, not a problem with any "
                "voucher. Every voucher is forced to balance when accepted.")
            tone(self.status, "warn")


class ProfitLossScreen(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Profit & Loss"))
        self.period = PeriodBar()
        # Opens on the financial year, not on since-books-began as it used to:
        # a profit and loss account is a statement FOR a year, and with a year
        # dropdown on the screen the period should agree with what it says.
        # Since-books-began is still one choice away in the same dropdown.
        self.period.changed.connect(self.refresh)
        layout.addWidget(self.period)

        self.trading_label = flowing(QtWidgets.QLabel())
        layout.addWidget(self.trading_label)
        trading = QtWidgets.QHBoxLayout()
        self.trading_expense = FrameTable()
        self.trading_income = FrameTable()
        trading.addWidget(self.trading_expense)
        trading.addWidget(self.trading_income)
        layout.addLayout(trading, 1)
        self.gross_label = flowing(QtWidgets.QLabel())
        layout.addWidget(self.gross_label)

        self.pl_label = flowing(QtWidgets.QLabel())
        layout.addWidget(self.pl_label)
        indirect = QtWidgets.QHBoxLayout()
        self.indirect_expense = FrameTable()
        self.indirect_income = FrameTable()
        indirect.addWidget(self.indirect_expense)
        indirect.addWidget(self.indirect_income)
        layout.addLayout(indirect, 1)
        self.net_label = flowing(QtWidgets.QLabel())
        layout.addWidget(self.net_label)

    def refresh(self) -> None:
        start, end = self.period.range()
        report = acc.profit_and_loss(start, end)
        totals = report["totals"]
        blank = pd.DataFrame(columns=["Particulars", "Under", "Amount"])

        self.trading_label.setText(
            f"<b>Trading account</b> &nbsp; purchases and direct expenses "
            f"{money(totals['trading_expense'])} &nbsp;|&nbsp; sales and direct "
            f"incomes {money(totals['trading_income'])}")
        self.trading_expense.load(
            report["trading_expense"] if not report["trading_expense"].empty else blank,
            numeric=("Amount",))
        self.trading_income.load(
            report["trading_income"] if not report["trading_income"].empty else blank,
            numeric=("Amount",))
        gross = totals["gross_profit"]
        self.gross_label.setText(
            f"<b>{'Gross profit' if gross >= 0 else 'Gross loss'}: "
            f"{money(abs(gross))}</b>")

        self.pl_label.setText(
            f"<b>Profit &amp; loss account</b> &nbsp; indirect expenses "
            f"{money(totals['indirect_expense'])} &nbsp;|&nbsp; indirect incomes "
            f"{money(totals['indirect_income'])}")
        self.indirect_expense.load(
            report["indirect_expense"] if not report["indirect_expense"].empty
            else blank, numeric=("Amount",))
        self.indirect_income.load(
            report["indirect_income"] if not report["indirect_income"].empty
            else blank, numeric=("Amount",))
        net = totals["net_profit"]
        self.net_label.setText(
            f"<b>{'Net profit' if net >= 0 else 'Net loss'}: {money(abs(net))}</b>")


class BalanceSheetScreen(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Balance Sheet"))
        self.period = PeriodBar(with_from=False)
        self.period.changed.connect(self.refresh)
        layout.addWidget(self.period)
        self.status = flowing(QtWidgets.QLabel())
        layout.addWidget(self.status)

        sides = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        self.liability_label = flowing(QtWidgets.QLabel())
        self.liabilities = FrameTable()
        left.addWidget(self.liability_label)
        left.addWidget(self.liabilities)
        right = QtWidgets.QVBoxLayout()
        self.asset_label = flowing(QtWidgets.QLabel())
        self.assets = FrameTable()
        right.addWidget(self.asset_label)
        right.addWidget(self.assets)
        sides.addLayout(left)
        sides.addLayout(right)
        layout.addLayout(sides, 1)
        # Wrapped, and muted like every other piece of guidance. Unwrapped, a
        # sentence this long sets the window's MINIMUM width to the width of
        # the sentence - it was forcing 1770px, so the window could not be made
        # narrower than that and grew worse with every step of text size.
        note = QtWidgets.QLabel(
            "Profit & Loss A/c carries the net profit from the start of the "
            "books to this date. Nominal ledgers are closed into it.")
        note.setWordWrap(True)
        layout.addWidget(muted(note))

    def refresh(self) -> None:
        _, as_at = self.period.range()
        sheet = acc.balance_sheet(as_at)
        totals = sheet["totals"]
        self.liability_label.setText(
            f"<b>Liabilities</b> &nbsp; {money(totals['liabilities'])}")
        self.asset_label.setText(f"<b>Assets</b> &nbsp; {money(totals['assets'])}")
        self.liabilities.load(sheet["liabilities"], numeric=("Amount",))
        self.assets.load(sheet["assets"], numeric=("Amount",))
        if abs(totals["difference"]) <= acc.EPS:
            self.status.setText("Both sides agree.")
            tone(self.status, "good")
        else:
            self.status.setText("The two sides do not agree — that should be "
                                "impossible, please report it.")
            tone(self.status, "bad")


class MastersScreen(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Masters"))

        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs, 1)

        # --- ledgers ---
        ledger_page = QtWidgets.QWidget()
        ledger_layout = QtWidgets.QVBoxLayout(ledger_page)
        self.ledger_table = FrameTable()
        ledger_layout.addWidget(self.ledger_table, 1)

        form = QtWidgets.QGridLayout()
        self.led_name = QtWidgets.QLineEdit()
        self.led_name.setPlaceholderText("e.g. Bank of India")
        self.led_group = QtWidgets.QComboBox()
        self.led_group.setEditable(True)
        self.led_group.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.led_open = QtWidgets.QDoubleSpinBox()
        self.led_open.setRange(0, 1e12)
        self.led_open.setDecimals(2)
        self.led_open.setGroupSeparatorShown(True)
        self.led_side = QtWidgets.QComboBox()
        self.led_side.addItems(list(db.SIDES))
        form.addWidget(QtWidgets.QLabel("Name"), 0, 0)
        form.addWidget(self.led_name, 0, 1)
        form.addWidget(QtWidgets.QLabel("Under"), 0, 2)
        form.addWidget(self.led_group, 0, 3)
        form.addWidget(QtWidgets.QLabel("Opening"), 1, 0)
        form.addWidget(self.led_open, 1, 1)
        form.addWidget(QtWidgets.QLabel("Dr / Cr"), 1, 2)
        form.addWidget(self.led_side, 1, 3)
        ledger_layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        create = QtWidgets.QPushButton("Create ledger")
        create.clicked.connect(self.create_ledger)
        delete = QtWidgets.QPushButton("Delete selected")
        delete.clicked.connect(self.delete_ledger)
        buttons.addWidget(create)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        ledger_layout.addLayout(buttons)
        tabs.addTab(ledger_page, "Ledgers")

        # --- groups ---
        group_page = QtWidgets.QWidget()
        group_layout = QtWidgets.QVBoxLayout(group_page)
        self.group_table = FrameTable()
        group_layout.addWidget(self.group_table, 1)
        group_form = QtWidgets.QHBoxLayout()
        self.grp_name = QtWidgets.QLineEdit()
        self.grp_name.setPlaceholderText("e.g. Vehicle Loan")
        self.grp_parent = QtWidgets.QComboBox()
        self.grp_parent.setEditable(True)
        self.grp_parent.completer().setFilterMode(QtCore.Qt.MatchContains)
        group_form.addWidget(QtWidgets.QLabel("Name"))
        group_form.addWidget(self.grp_name, 1)
        group_form.addWidget(QtWidgets.QLabel("Under"))
        group_form.addWidget(self.grp_parent, 1)
        add_group = QtWidgets.QPushButton("Create group")
        add_group.clicked.connect(self.create_group)
        group_form.addWidget(add_group)
        group_layout.addLayout(group_form)
        tabs.addTab(group_page, "Groups")

        self.refresh()

    def refresh(self) -> None:
        ledgers = db.get_ledgers(include_inactive=True)
        balances = acc.balances().set_index("ledger_id")
        view = pd.DataFrame({
            "Ledger": ledgers["name"],
            "Under": ledgers["group_name"],
            "Opening": ledgers["opening"],
            "Dr/Cr": ledgers["opening_side"],
            "Closing": ledgers["id"].astype(int).map(
                lambda i: acc.fmt_side(float(balances.loc[i, "closing"]))
                if i in balances.index else "—"),
        })
        self.ledger_table.load(view, numeric=("Opening",))
        self._ledger_names = list(ledgers["name"])

        groups = db.get_groups()
        self.group_table.load(pd.DataFrame({
            "Group": groups["name"],
            "Under": groups["parent_name"].fillna("—"),
            "Nature": groups["nature"],
            "Trading": groups["affects_gross"].map({1: "yes", 0: ""}),
            "Reserved": groups["is_reserved"].map({1: "yes", 0: ""}),
        }))
        names = list(groups["name"])
        for box in (self.led_group, self.grp_parent):
            current = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItems(names)
            if current in names:
                box.setCurrentText(current)
            box.blockSignals(False)

    def _warn(self, exc: Exception) -> None:
        QtWidgets.QMessageBox.warning(self, "Cannot do that", str(exc))

    def create_ledger(self) -> None:
        try:
            db.add_ledger(self.led_name.text(), self.led_group.currentText(),
                          self.led_open.value(), self.led_side.currentText())
        except ValueError as exc:
            self._warn(exc)
            return
        self.led_name.clear()
        self.led_open.setValue(0)
        self.refresh()
        self.changed.emit()

    def delete_ledger(self) -> None:
        row = self.ledger_table.currentRow()
        if row < 0 or row >= len(self._ledger_names):
            return
        name = self._ledger_names[row]
        try:
            db.delete_ledger(db.ledger_id(name))
        except ValueError as exc:
            self._warn(exc)
            return
        self.refresh()
        self.changed.emit()

    def create_group(self) -> None:
        try:
            db.add_group(self.grp_name.text(), self.grp_parent.currentText())
        except ValueError as exc:
            self._warn(exc)
            return
        self.grp_name.clear()
        self.refresh()
        self.changed.emit()


# --------------------------------------------------------------------------- #
# choosing a company at launch
# --------------------------------------------------------------------------- #
# Only the fields needed to open a usable set of books. The rest - address,
# PAN, GSTIN - are filled in afterwards on the Company screen, so creating a
# company is not a fifteen-field form before you can enter a single voucher.
NEW_COMPANY_FIELDS = ("company_name", "fy_start_month", "books_begin",
                      "currency")


class NewCompanyDialog(QtWidgets.QDialog):
    """Create a company, which means creating its database file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create a company")
        self.created: Path | None = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(muted(flowing(QtWidgets.QLabel(
            "Each company is a separate set of books, in its own file in the "
            "data folder. Address, PAN and GSTIN can be filled in afterwards "
            "on the Company screen."))))

        form = QtWidgets.QFormLayout()
        by_key = {field.key: field for field in db.COMPANY_FIELDS}
        self.editors: dict[str, QtWidgets.QWidget] = {}
        defaults = db.DEFAULT_SETTINGS
        for key in NEW_COMPANY_FIELDS:
            field = by_key[key]
            editor = editor_for(field)
            if key == "fy_start_month":
                editor.setCurrentIndex(int(defaults.get(key, 4)) - 1)
            elif key == "books_begin":
                editor.setDate(to_qdate(date.today()))
            elif key == "currency":
                editor.setCurrentText(defaults.get(key, "₹"))
            self.editors[key] = editor
            form.addRow(field.label + (" *" if field.required else ""), editor)
        layout.addLayout(form)

        self.status = flowing(QtWidgets.QLabel())
        layout.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.editors["company_name"].setFocus()

    def values(self) -> dict[str, str]:
        out = {}
        for key, editor in self.editors.items():
            if isinstance(editor, QtWidgets.QComboBox):
                out[key] = (str(editor.currentData())
                            if editor.currentData() is not None
                            else editor.currentText())
            elif isinstance(editor, QtWidgets.QDateEdit):
                out[key] = from_qdate(editor.date()).isoformat()
            else:
                out[key] = editor.text()
        return out

    def _create(self) -> None:
        try:
            self.created = db.create_company(self.values())
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            tone(self.status, "bad")
            return
        self.accept()


class CompanyPicker(QtWidgets.QDialog):
    """Which set of books to work in — a dropdown, over the open window.

    Shown just after the app appears, and again on F3. It opens OVER a running
    window rather than in front of it, so the app is up and usable first and
    the company already open is what the dropdown starts on.

    It never creates anything by itself: *New company…* is a button you press.
    """

    def __init__(self, parent=None, current=None):
        super().__init__(parent)
        self.setWindowTitle("Select company")
        self.chosen: Path | None = None
        # Which company to start the dropdown on. Passed in rather than read
        # from db.DB_PATH, because creating a company switches that - and the
        # dropdown should show the books the window is displaying.
        self.current = Path(current) if current else Path(db.DB_PATH)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Select company"))
        self.note = muted(flowing(QtWidgets.QLabel()))
        layout.addWidget(self.note)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Company"))
        self.combo = QtWidgets.QComboBox()
        self.combo.currentIndexChanged.connect(self._describe)
        row.addWidget(self.combo, 1)
        layout.addLayout(row)

        self.detail = muted(flowing(QtWidgets.QLabel()))
        layout.addWidget(self.detail)
        layout.addStretch(1)

        buttons = QtWidgets.QHBoxLayout()
        new = QtWidgets.QPushButton("New company…")
        new.setToolTip("Create another set of books")
        new.clicked.connect(self.create)
        buttons.addWidget(new)
        buttons.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setToolTip("Stay in the company that is already open")
        cancel.clicked.connect(self.reject)
        self.open_button = QtWidgets.QPushButton("Open")
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(cancel)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)

        self.reload()
        self.resize(520, 240)

    def reload(self) -> None:
        companies = db.list_companies()
        self.combo.blockSignals(True)
        self.combo.clear()
        select = 0
        for index, company in enumerate(companies):
            self.combo.addItem(
                f"{company['company_name']}   ({company['file']})",
                company["path"])
            if company["file"] == self.current.name:
                select = index          # the company the window is showing
        self.combo.blockSignals(False)
        if companies:
            self.combo.setCurrentIndex(select)
            self.note.setText(
                f"{len(companies)} "
                f"compan{'y' if len(companies) == 1 else 'ies'} in "
                f"{db.DATA_DIR}.")
        else:
            self.note.setText(
                f"No companies in {db.DATA_DIR} yet. "
                f"Use New company to add one.")
        self.open_button.setEnabled(bool(companies))
        self._describe()
        self.combo.setFocus()

    def _describe(self) -> None:
        """Say what is actually in the company the dropdown is showing."""
        path = self.selected()
        if path is None:
            self.detail.clear()
            return
        details = db.peek_company(path)
        changed = datetime.fromtimestamp(path.stat().st_mtime)
        parts = [f"{details['file']}",
                 f"last changed {changed.strftime('%d/%m/%Y %H:%M')}"]
        if details["gstin"]:
            parts.append(f"GSTIN {details['gstin']}")
        if path.name == self.current.name:
            parts.append("open now")
        self.detail.setText(" · ".join(parts))

    def selected(self) -> Path | None:
        data = self.combo.currentData()
        return Path(data) if data else None

    def _open(self) -> None:
        path = self.selected()
        if path is None:
            return
        self.chosen = path
        self.accept()

    def create(self) -> None:
        """Only ever reached by pressing the button."""
        dialog = NewCompanyDialog(self)
        if dialog.exec() and dialog.created is not None:
            self.chosen = dialog.created
            self.accept()


# --------------------------------------------------------------------------- #
# company master
# --------------------------------------------------------------------------- #
class CompanyScreen(QtWidgets.QWidget):
    """Who the books belong to: name, address, registrations, the year.

    The form is BUILT FROM ``db.COMPANY_FIELDS`` rather than written out, so a
    field added to that tuple appears here and in the Streamlit form with
    nothing further to write, and both save through the same validation.
    """

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Company"))
        layout.addWidget(muted(flowing(QtWidgets.QLabel(
            "Printed on statements and quoted on returns. Everything but the "
            "name can be left blank until you have it — but a PAN, GSTIN, TAN "
            "or CIN that IS filled in has to be the right shape, because a "
            "malformed one is worse than an absent one."))))

        # Fifteen rows at the largest text size is taller than the window, so
        # the form scrolls instead of having its last fields cut off.
        host = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(host)
        self.form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.editors: dict[str, QtWidgets.QWidget] = {}
        for field in db.COMPANY_FIELDS:
            editor = editor_for(field)
            if field.hint:
                editor.setToolTip(field.hint)
            self.editors[field.key] = editor
            label = QtWidgets.QLabel(
                f"{field.label} *" if field.required else field.label)
            self.form.addRow(label, editor)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        self.status = flowing(QtWidgets.QLabel())
        layout.addWidget(self.status)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        revert = QtWidgets.QPushButton("Revert")
        revert.setToolTip("Discard edits and reload what is saved")
        revert.clicked.connect(self.refresh)
        self.save_button = QtWidgets.QPushButton("Save  (Ctrl+S)")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(revert)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        action = QtGui.QAction("Save company", self)
        action.setShortcut(QtGui.QKeySequence("Ctrl+S"))
        action.triggered.connect(self.save)
        self.addAction(action)

        self.refresh()

    def refresh(self) -> None:
        """Load what is saved, discarding any edits.

        Called when you switch TO this screen, and by Revert - but deliberately
        NOT by refresh_all(), which would throw away half-typed details the
        moment a voucher was posted elsewhere. The voucher screen is left out
        of refresh_all() for the same reason: both hold input, not a report.
        """
        values = db.get_company()
        for field in db.COMPANY_FIELDS:
            editor = self.editors[field.key]
            value = values.get(field.key, "")
            if field.kind == "multiline":
                editor.setPlainText(value)
                fit_lines(editor)
            elif field.kind == "month":
                editor.setCurrentIndex(max(0, int(value or 4) - 1))
            elif field.kind == "date":
                editor.setDate(to_qdate(value) if value
                               else to_qdate(date.today()))
            elif field.kind == "choice":
                editor.setCurrentText(value)
            else:
                editor.setText(value)
        self.status.clear()

    def values(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for field in db.COMPANY_FIELDS:
            editor = self.editors[field.key]
            if field.kind == "multiline":
                out[field.key] = editor.toPlainText()
            elif field.kind == "month":
                out[field.key] = str(editor.currentData())
            elif field.kind == "date":
                out[field.key] = from_qdate(editor.date()).isoformat()
            elif field.kind == "choice":
                out[field.key] = editor.currentText()
            else:
                out[field.key] = editor.text()
        return out

    def save(self) -> bool:
        """Save, or explain why not. Rejected input is LEFT IN THE FORM, so a
        single bad character does not cost the rest of the typing."""
        try:
            saved = db.save_company(self.values())
        except ValueError as exc:
            self.status.setText(str(exc))
            tone(self.status, "bad")
            return False
        # Re-show the cleaned values: identifiers come back upper-cased, which
        # the user should see rather than wonder about.
        for key in db.UPPER_FIELDS:
            self.editors[key].setText(saved[key])
        self.status.setText(f"Saved. {saved['company_name']}"
                            + (f" · GSTIN {saved['gstin']}" if saved["gstin"]
                               else ""))
        tone(self.status, "good")
        self.changed.emit()
        return True


# --------------------------------------------------------------------------- #
# main window
# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        db.init_db()
        # Set by "Switch company"; main() reads it after the window closes and
        # comes back round to open the chosen company.
        self.switch_requested = False
        # The company THIS window is showing. Compared against rather than
        # db.DB_PATH, because creating a company switches the data layer as a
        # side effect - so db.DB_PATH can already have moved on while these
        # screens still show the old books.
        self.company_file = Path(db.DB_PATH)

        # Before any widget is built, so nothing is created under the wrong
        # palette or at the wrong size. Read from the books, so both choices
        # survive a restart and are the same whichever machine opens this file.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            theme.remember_native_style(app)
            theme.remember_base_font(app)
            theme.apply(app, db.get_setting(theme.SETTING_KEY, theme.DEFAULT))
            theme.apply_font(
                app, db.get_setting(theme.FONT_SETTING_KEY, theme.DEFAULT_TEXT))

        self._set_title()
        # The window grows with the text. At a larger size the same 1180x760
        # would simply push the lower half of a screen out of view, which is
        # the opposite of making anything easier to read.
        self.resize(self._sized_to_text())

        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        self.voucher = VoucherScreen()
        self.daybook = DayBookScreen()
        self.ledger = LedgerScreen()
        self.trial = TrialBalanceScreen()
        self.profit = ProfitLossScreen()
        self.sheet = BalanceSheetScreen()
        self.masters = MastersScreen()
        self.company = CompanyScreen()

        self.screens = [
            ("Voucher Entry", self.voucher),
            ("Day Book", self.daybook),
            ("Ledger", self.ledger),
            ("Trial Balance", self.trial),
            ("Profit && Loss", self.profit),
            ("Balance Sheet", self.sheet),
            ("Masters", self.masters),
            ("Company", self.company),
        ]
        for _, widget in self.screens:
            self.stack.addWidget(widget)

        self.voucher.posted.connect(self.refresh_all)
        self.voucher.masters_changed.connect(self._masters_changed)
        self.masters.changed.connect(self.refresh_all)
        self.daybook.open_voucher.connect(self._alter)
        self.ledger.open_voucher.connect(self._alter)
        # The company name is in the title bar and its currency symbol is in
        # every figure, so saving it has to reach the whole window.
        self.company.changed.connect(self._company_changed)

        self._build_menu()
        self.statusBar().showMessage("F4–F9 switch voucher type · Ctrl+A accepts")
        self.refresh_all()
        self.show_screen(0)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        go = bar.addMenu("&Go")
        for index, (label, _) in enumerate(self.screens):
            action = QtGui.QAction(label.replace("&&", "&"), self)
            action.setShortcut(QtGui.QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(lambda _=False, i=index: self.show_screen(i))
            go.addAction(action)

        voucher_menu = bar.addMenu("&Voucher")
        for key, name in VOUCHER_KEYS.items():
            action = QtGui.QAction(f"{name}\t{key}", self)
            action.setShortcut(QtGui.QKeySequence(key))
            action.triggered.connect(
                lambda _=False, n=name: self._set_voucher_type(n))
            voucher_menu.addAction(action)
        voucher_menu.addSeparator()
        accept = QtGui.QAction("Accept voucher", self)
        accept.setShortcut(QtGui.QKeySequence("Ctrl+A"))
        accept.triggered.connect(self._accept)
        voucher_menu.addAction(accept)
        create_master = QtGui.QAction("Create ledger	Alt+C", self)
        create_master.triggered.connect(
            lambda: (self.show_screen(0), self.voucher.create_ledger()))
        voucher_menu.addAction(create_master)
        set_date = QtGui.QAction("Set date", self)
        set_date.setShortcut(QtGui.QKeySequence("F2"))
        set_date.triggered.connect(
            lambda: (self.show_screen(0), self.voucher.date_edit.setFocus()))
        voucher_menu.addAction(set_date)

        escape = QtGui.QAction("Back to voucher entry", self)
        escape.setShortcut(QtGui.QKeySequence("Esc"))
        escape.triggered.connect(lambda: self.show_screen(0))
        self.addAction(escape)

        refresh = QtGui.QAction("Refresh", self)
        refresh.setShortcut(QtGui.QKeySequence("F11"))
        refresh.triggered.connect(self.refresh_all)
        self.addAction(refresh)

        company_menu = bar.addMenu("&Company")
        details = QtGui.QAction("Company details", self)
        details.triggered.connect(
            lambda: self.show_screen(len(self.screens) - 1))
        company_menu.addAction(details)
        company_menu.addSeparator()
        switch = self._switch_action = QtGui.QAction("Switch company…\tF3", self)
        switch.setShortcut(QtGui.QKeySequence("F3"))
        switch.setEnabled(not db.DB_PINNED)
        switch.setToolTip("Close these books and choose another company"
                          if not db.DB_PINNED else
                          "BOOKS_DB pins the data file for this session")
        switch.triggered.connect(self.switch_company)
        company_menu.addAction(switch)
        new_company = QtGui.QAction("New company…", self)
        new_company.setEnabled(not db.DB_PINNED)
        new_company.triggered.connect(self.new_company)
        company_menu.addAction(new_company)

        company_menu.addSeparator()
        backup = QtGui.QAction("Back up now\tCtrl+B", self)
        backup.setShortcut(QtGui.QKeySequence("Ctrl+B"))
        backup.setToolTip("Copy these books into the backup folder. One is "
                          "also taken automatically every time the app opens.")
        backup.triggered.connect(self.backup_now)
        company_menu.addAction(backup)
        open_folder = QtGui.QAction("Open backup folder", self)
        open_folder.triggered.connect(self.open_backup_folder)
        company_menu.addAction(open_folder)

        settings_menu = bar.addMenu("&Settings")

        size_menu = settings_menu.addMenu("&Text size")
        saved_text = theme.resolve_text(
            db.get_setting(theme.FONT_SETTING_KEY, theme.DEFAULT_TEXT))
        self._text_group = QtGui.QActionGroup(self)
        self._text_group.setExclusive(True)
        self._text_actions = {}
        for key in theme.TEXT_ORDER:
            action = QtGui.QAction(theme.TEXT_LABELS[key], self, checkable=True)
            action.setChecked(key == saved_text)
            action.triggered.connect(
                lambda _=False, k=key: self.set_text_size(k))
            self._text_group.addAction(action)
            size_menu.addAction(action)
            self._text_actions[key] = action

        # The familiar zoom keys, so you can nudge it while reading rather
        # than going back to the menu.
        size_menu.addSeparator()
        for label, shortcut, delta in (("Bigger", "Ctrl+=", 1),
                                       ("Smaller", "Ctrl+-", -1)):
            action = QtGui.QAction(label, self)
            action.setShortcut(QtGui.QKeySequence(shortcut))
            action.triggered.connect(
                lambda _=False, d=delta: self.step_text_size(d))
            size_menu.addAction(action)
            self.addAction(action)
        # Ctrl++ as well: on many layouts that is what Ctrl and the plus key
        # actually sends, and only Ctrl+= is bound above.
        plus = QtGui.QAction("Bigger", self)
        plus.setShortcut(QtGui.QKeySequence("Ctrl++"))
        plus.triggered.connect(lambda: self.step_text_size(1))
        self.addAction(plus)

        settings_menu.addSeparator()
        scheme_menu = settings_menu.addMenu("&Colour scheme")
        saved = db.get_setting(theme.SETTING_KEY, theme.DEFAULT)
        self._scheme_group = QtGui.QActionGroup(self)
        self._scheme_group.setExclusive(True)
        self._scheme_actions = {}
        for position, key in enumerate(theme.ORDER, start=1):
            action = QtGui.QAction(theme.LABELS[key], self, checkable=True)
            action.setChecked(key == saved)
            action.setShortcut(QtGui.QKeySequence(f"Ctrl+Shift+{position}"))
            action.triggered.connect(
                lambda _=False, k=key: self.set_color_scheme(k))
            self._scheme_group.addAction(action)
            scheme_menu.addAction(action)
            self._scheme_actions[key] = action

    def set_color_scheme(self, key: str) -> None:
        """Switch scheme, save it, and repaint what the stylesheet cannot.

        The muted labels follow the stylesheet on their own. The status lines
        do not - they were given a colour when a report last ran - so their
        stored tone is re-applied here rather than recomputing every report.
        """
        app = QtWidgets.QApplication.instance()
        if app is not None:
            theme.apply(app, key)
        db.set_setting(theme.SETTING_KEY, key)
        if key in self._scheme_actions:
            self._scheme_actions[key].setChecked(True)
        self._repaint_tones()
        scheme = theme.active()
        label = theme.LABELS.get(key, scheme.label)
        if key == theme.AUTO:
            label = f"{label} — {scheme.label} right now"
        self.statusBar().showMessage(f"Colour scheme: {label}")

    def _repaint_tones(self) -> None:
        for label in self.findChildren(QtWidgets.QLabel):
            token = label.property("tone")
            if token:
                label.setStyleSheet(theme.fg(token))

    # --- text size ------------------------------------------------------- #
    BASE_WIDTH = 1180
    BASE_HEIGHT = 760

    def _sized_to_text(self) -> QtCore.QSize:
        """The window size for the active text size.

        Grows with the text, but never past the display: at the largest step
        the scaled size came to 1967x1267, which is taller than a 1080p screen
        and would have put the Accept button under the taskbar. Clamped to the
        available desktop, then raised to whatever the layout genuinely needs.
        """
        scale = theme.text_scale()
        size = QtCore.QSize(round(self.BASE_WIDTH * scale),
                            round(self.BASE_HEIGHT * scale))
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            size = size.boundedTo(screen.availableGeometry().size())
        return size.expandedTo(self.minimumSizeHint())

    def step_text_size(self, delta: int) -> None:
        """Move one step up or down the list, stopping at the ends."""
        order = list(theme.TEXT_ORDER)
        index = order.index(theme.active_text()) + delta
        index = max(0, min(len(order) - 1, index))
        self.set_text_size(order[index])

    def set_text_size(self, key: str) -> None:
        """Resize the text, then make the layout follow it.

        Setting the application font is only half the job. Three kinds of thing
        do not follow it on their own and are fixed up here:

        * widgets whose point size was set once in a constructor - the screen
          headings and the monospaced amount labels, marked with the "heading"
          and "mono" properties when they were built;
        * table rows and columns, whose measured heights and widths were taken
          against the old metrics;
        * the window itself, which would otherwise keep a size chosen for
          smaller text and push the bottom of the screen out of view.
        """
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        theme.apply_font(app, key)
        key = theme.active_text()
        db.set_setting(theme.FONT_SETTING_KEY, key)
        if key in self._text_actions:
            self._text_actions[key].setChecked(True)

        for widget in self.findChildren(QtWidgets.QWidget):
            if widget.property("heading"):
                font = widget.font()
                font.setPointSize(theme.heading_point_size())
                widget.setFont(font)
            elif widget.property("mono"):
                widget.setFont(mono_font())
            elif widget.property("lines"):
                fit_lines(widget)

        # Rebuilds every table against the new metrics, which re-fonts the
        # amount items and re-measures the columns.
        self.refresh_all()
        for table in self.findChildren(QtWidgets.QTableWidget):
            table.resizeRowsToContents()

        if not (self.isMaximized() or self.isFullScreen()):
            self.resize(self._sized_to_text())
        self.statusBar().showMessage(
            f"Text size: {theme.TEXT_LABELS[key]} ({theme.point_size()}pt)")

    def _set_title(self) -> None:
        self.setWindowTitle(f"{db.company_display_name()} — Bookkeeper")

    def ask_company(self) -> None:
        """Offer the company dropdown over the open window.

        This is what runs just after launch, and on F3. Choosing the company
        already open, or cancelling, simply leaves you where you are - only a
        DIFFERENT company closes and reopens the window.
        """
        if db.DB_PINNED:
            return
        picker = CompanyPicker(self, current=self.company_file)
        if not picker.exec() or picker.chosen is None:
            self._stay()
            return
        chosen = Path(picker.chosen)
        if chosen.name == self.company_file.name:
            self._stay()
            self.statusBar().showMessage(
                f"Staying in {db.company_display_name()}")
            return
        self._open_company(chosen)

    def switch_company(self) -> None:
        """F3: the same dropdown, asked for deliberately."""
        self.ask_company()

    def new_company(self) -> None:
        dialog = NewCompanyDialog(self)
        if not dialog.exec() or dialog.created is None:
            self._stay()
            return
        self._open_company(Path(dialog.created))

    def _stay(self) -> None:
        """Point the data layer back at the books this window is showing.

        Needed because creating a company switches to it: if the user then
        cancels, the window would be showing one company and every query would
        be answering from another.
        """
        db.use_company(self.company_file)

    def _open_company(self, path: Path) -> None:
        """Leave these books and reopen the window on another company.

        Closing and reopening is deliberate: rebuilding eight screens in place
        against a different database is a lot of state to get right, and a
        voucher part-entered against the OLD company is exactly the kind of
        thing that would survive it.
        """
        if not self._confirm_leaving("Switch company"):
            self._stay()
            return
        db.use_company(path)
        db.remember_last_company(path)
        self.switch_requested = True
        self.close()

    def part_entered_rows(self) -> list[int]:
        """Voucher rows with a ledger chosen but not yet accepted.

        Separate from the confirmation below so it can be tested without a
        modal dialog blocking the run.
        """
        return [row for row in range(self.voucher.grid.rowCount())
                if self.voucher.grid.cellWidget(row, 0)
                and self.voucher.grid.cellWidget(row, 0).currentText().strip()]

    def _confirm_leaving(self, what: str) -> bool:
        """Warn if a voucher is part-entered, since leaving discards it."""
        if not self.part_entered_rows():
            return True
        answer = QtWidgets.QMessageBox.question(
            self, what,
            f"A voucher is part-entered on the Voucher Entry screen. "
            f"{what} and it will be discarded.\n\nContinue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        return answer == QtWidgets.QMessageBox.Yes

    # --- backups ---------------------------------------------------------- #
    def backup_on_open(self) -> None:
        """Copy the books before this session touches them.

        Silent when it works: an automatic safety net is not news, and a
        message here would displace the opening-balance warning the status bar
        has just put up. LOUD when it fails, though - a backup you believe is
        being taken and is not is the exact shape of the data loss this
        project has already had once, and it stayed invisible because nothing
        ever said otherwise.
        """
        try:
            db.backup_company(self.company_file, tag="open")
        except Exception as exc:                      # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Could not back up",
                f"These books were NOT backed up when the app opened:\n\n"
                f"{exc}\n\nYour books are fine and you can carry on. Try "
                f"Company > Back up now, and check there is room on the disk.")

    def backup_now(self) -> None:
        """Company > Back up now, for before you do something you are unsure
        about."""
        try:
            made = db.backup_company(self.company_file, tag="manual")
        except Exception as exc:                      # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Could not back up", f"Nothing was written:\n\n{exc}")
            return
        kept = len(db.backups_for(self.company_file))
        if made is None:
            # Not a failure, and saying "done" would be a lie - so say which.
            QtWidgets.QMessageBox.information(
                self, "Already backed up",
                "These books have not changed since the last backup, so "
                f"nothing new was written.\n\n{kept} backup(s) kept in:\n"
                f"{db.backup_dir()}")
            return
        self.statusBar().showMessage(f"Backed up to {made.name}", 6000)
        QtWidgets.QMessageBox.information(
            self, "Backed up",
            f"{db.company_display_name()} copied to:\n\n{made}\n\n"
            f"{kept} backup(s) kept; the oldest are dropped beyond "
            f"{db.KEEP_BACKUPS}.")

    def open_backup_folder(self) -> None:
        folder = db.backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(folder)))

    def _company_changed(self) -> None:
        """Company details were saved: the title and every figure can change,
        since the currency symbol and the financial year both live there."""
        self._set_title()
        self.voucher.reload_ledgers()
        self.ledger.reload_ledgers()
        # The financial-year start month is on that screen, and it decides
        # what the years ARE - so the dropdowns have to be rebuilt, not just
        # the reports re-run.
        for _, widget in self.screens:
            bar = getattr(widget, "period", None)
            if isinstance(bar, PeriodBar):
                bar.reload_years()
        for _, widget in self.screens:
            if widget is not self.company and hasattr(widget, "refresh"):
                widget.refresh()

    def _masters_changed(self) -> None:
        """A master was created mid-voucher: refresh everything but the grid."""
        self.ledger.reload_ledgers()
        self.masters.refresh()
        for screen in (self.daybook, self.trial, self.profit, self.sheet):
            screen.refresh()

    def _set_voucher_type(self, name: str) -> None:
        self.show_screen(0)
        self.voucher.type_box.setCurrentText(name)

    def _accept(self) -> None:
        if self.stack.currentIndex() == 0 and self.voucher.accept_button.isEnabled():
            self.voucher.accept_voucher()

    def _alter(self, voucher_id: int) -> None:
        self.voucher.load_voucher(int(voucher_id))
        self.show_screen(0)

    def show_screen(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        widget = self.screens[index][1]
        if hasattr(widget, "reload_ledgers"):
            widget.reload_ledgers()
        if hasattr(widget, "refresh"):
            widget.refresh()

    def refresh_all(self) -> None:
        self.voucher.reload_ledgers()
        self.ledger.reload_ledgers()
        # The voucher and company screens hold INPUT, not a report. Refreshing
        # them here would discard a part-entered voucher or half-typed company
        # details the moment anything else in the app changed.
        for _, widget in self.screens:
            if widget not in (self.voucher, self.company) \
                    and hasattr(widget, "refresh"):
                widget.refresh()

        gap = acc.opening_difference()
        if abs(gap) > acc.EPS:
            self.statusBar().showMessage(
                f"Difference in opening balances: {money(abs(gap))} "
                f"{'Dr' if gap > 0 else 'Cr'} — shown as its own line on the "
                "Balance Sheet until the opening balances agree.")


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Bookkeeper")
    theme.remember_native_style(app)
    theme.remember_base_font(app)

    # The app OPENS FIRST, on the company used last, and asks afterwards (user
    # asked 2026-10-16). Nothing is created on the way in: a fresh install
    # falls back to the default file, exactly as before this app knew about
    # more than one company, so starting up never demands a company be made.
    if not db.DB_PINNED:
        db.use_company(db.startup_company())

    ask_on_open = not db.DB_PINNED

    # One pass per company opened. Switching closes the window and comes back
    # here, which is far safer than rebuilding every screen in place against a
    # different database.
    while True:
        window = MainWindow()
        # Before anything is entered: whatever this session does, the books as
        # they were on opening are already safe on disk. Also covers switching
        # company, which comes back round this loop.
        window.backup_on_open()
        window.show()
        if ask_on_open:
            # After the window is up and painted, not before it.
            QtCore.QTimer.singleShot(0, window.ask_company)
        app.exec()
        if db.DB_PINNED or not window.switch_requested:
            return 0
        # A company was chosen; open it without asking all over again.
        ask_on_open = False


if __name__ == "__main__":
    raise SystemExit(main())
