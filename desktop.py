"""Tally-style bookkeeping — native desktop app (PySide6/Qt).

    python desktop.py

This is a second front end over the same books. ``db.py`` and ``accounting.py``
are shared with the Streamlit version untouched, and both read the same
``data/books.db``, so you can use whichever suits the moment.

Why a desktop build exists at all: voucher entry wants a grid that responds to
every keystroke without a round trip, and function keys that switch voucher
type the way Tally's do. Keyboard map follows Tally where it sensibly can:

    F4 Contra   F5 Payment   F6 Receipt   F7 Journal   F8 Sales   F9 Purchase
    Ctrl+A      accept the voucher
    Ctrl+1..7   jump between screens
    F2          set the voucher date
    Esc         back to voucher entry
"""

from __future__ import annotations

import sys
from datetime import date

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

import accounting as acc
import db

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
                    item.setFont(QtGui.QFont(MONO))
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


def heading(text: str, size: int = 15) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    font = label.font()
    font.setPointSize(size)
    font.setBold(True)
    label.setFont(font)
    return label


def totals_bar(*pairs: tuple[str, str]) -> QtWidgets.QWidget:
    """A right-aligned row of label/value pairs, for report footers."""
    box = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.addStretch(1)
    for label, value in pairs:
        cell = QtWidgets.QLabel(f"{label}  <b>{value}</b>")
        cell.setFont(QtGui.QFont(MONO))
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
        note.setStyleSheet("color: #666;")
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
        self.note.setStyleSheet("color: #666;")

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
        self.number_label.setFont(QtGui.QFont(MONO))
        head.addWidget(self.number_label)
        head.addStretch(1)
        self.hint = QtWidgets.QLabel()
        self.hint.setStyleSheet("color: #666;")
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
            widget.setFont(QtGui.QFont(MONO))
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
            item.setFont(QtGui.QFont(MONO))
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
        self.gap_label.setStyleSheet(
            "color: #137333;" if abs(gap) <= 0.005 and debit > 0 else "color: #b3261e;")

        balanced = abs(gap) <= 0.005 and debit > 0 and len(rows) >= 2
        distinct = len({r["ledger_id"] for r in rows}) >= 2
        self.accept_button.setEnabled(balanced and distinct)

        notes = db.voucher_type_warnings(
            self.type_box.currentText(), rows, self._ledgers)
        if not rows:
            self.notice.setText(
                "Pick a ledger on each line, then put the amount under Debit or "
                "Credit — never both on one line.")
            self.notice.setStyleSheet("color: #666;")
        elif not balanced or not distinct:
            self.notice.setText("Debit and credit must agree, across at least "
                                "two different ledgers.")
            self.notice.setStyleSheet("color: #b3261e;")
        elif notes:
            self.notice.setText("ℹ️  " + "  ".join(notes))
            self.notice.setStyleSheet("color: #8a6d00;")
        else:
            self.notice.setText("Debit equals credit — ready to accept.")
            self.notice.setStyleSheet("color: #137333;")

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
    """From/to dates with Tally-ish presets."""

    changed = QtCore.Signal()

    def __init__(self, with_from: bool = True, parent=None):
        super().__init__(parent)
        self.with_from = with_from
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        fy_start, fy_end = self._fy()
        if with_from:
            row.addWidget(QtWidgets.QLabel("From"))
            self.from_edit = QtWidgets.QDateEdit(to_qdate(fy_start))
            self.from_edit.setCalendarPopup(True)
            self.from_edit.setDisplayFormat("dd/MM/yyyy")
            self.from_edit.dateChanged.connect(lambda *_: self.changed.emit())
            row.addWidget(self.from_edit)

        row.addWidget(QtWidgets.QLabel("To"))
        self.to_edit = QtWidgets.QDateEdit(to_qdate(date.today()))
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_edit.dateChanged.connect(lambda *_: self.changed.emit())
        row.addWidget(self.to_edit)

        if with_from:
            self.since = QtWidgets.QCheckBox("Since books began")
            self.since.toggled.connect(self._toggle_since)
            row.addWidget(self.since)
        row.addStretch(1)

    @staticmethod
    def _fy() -> tuple[date, date]:
        month = int(db.get_setting("fy_start_month", "4"))
        today = date.today()
        year = today.year if today.month >= month else today.year - 1
        return date(year, month, 1), today

    def _toggle_since(self, on: bool) -> None:
        self.from_edit.setEnabled(not on)
        self.changed.emit()

    def range(self) -> tuple[date | None, date]:
        if self.with_from and self.since.isChecked():
            return None, from_qdate(self.to_edit.date())
        if not self.with_from:
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
        self.count = QtWidgets.QLabel()
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

        self.caption = QtWidgets.QLabel()
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
        self.status = QtWidgets.QLabel()
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
            self.status.setStyleSheet("color: #137333;")
        else:
            self.status.setText(
                f"Out by {money(abs(trial['difference']))} — this is the "
                "difference in opening balances, not a problem with any "
                "voucher. Every voucher is forced to balance when accepted.")
            self.status.setStyleSheet("color: #8a6d00;")


class ProfitLossScreen(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(heading("Profit & Loss"))
        self.period = PeriodBar()
        self.period.since.setChecked(True)
        self.period.changed.connect(self.refresh)
        layout.addWidget(self.period)

        self.trading_label = QtWidgets.QLabel()
        layout.addWidget(self.trading_label)
        trading = QtWidgets.QHBoxLayout()
        self.trading_expense = FrameTable()
        self.trading_income = FrameTable()
        trading.addWidget(self.trading_expense)
        trading.addWidget(self.trading_income)
        layout.addLayout(trading, 1)
        self.gross_label = QtWidgets.QLabel()
        layout.addWidget(self.gross_label)

        self.pl_label = QtWidgets.QLabel()
        layout.addWidget(self.pl_label)
        indirect = QtWidgets.QHBoxLayout()
        self.indirect_expense = FrameTable()
        self.indirect_income = FrameTable()
        indirect.addWidget(self.indirect_expense)
        indirect.addWidget(self.indirect_income)
        layout.addLayout(indirect, 1)
        self.net_label = QtWidgets.QLabel()
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
        self.status = QtWidgets.QLabel()
        layout.addWidget(self.status)

        sides = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        self.liability_label = QtWidgets.QLabel()
        self.liabilities = FrameTable()
        left.addWidget(self.liability_label)
        left.addWidget(self.liabilities)
        right = QtWidgets.QVBoxLayout()
        self.asset_label = QtWidgets.QLabel()
        self.assets = FrameTable()
        right.addWidget(self.asset_label)
        right.addWidget(self.assets)
        sides.addLayout(left)
        sides.addLayout(right)
        layout.addLayout(sides, 1)
        layout.addWidget(QtWidgets.QLabel(
            "Profit & Loss A/c carries the net profit from the start of the "
            "books to this date. Nominal ledgers are closed into it."))

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
            self.status.setStyleSheet("color: #137333;")
        else:
            self.status.setText("The two sides do not agree — that should be "
                                "impossible, please report it.")
            self.status.setStyleSheet("color: #b3261e;")


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
# main window
# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        db.init_db()
        company = db.get_setting("company_name", "My Company")
        self.setWindowTitle(f"{company} — Books")
        self.resize(1180, 760)

        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        self.voucher = VoucherScreen()
        self.daybook = DayBookScreen()
        self.ledger = LedgerScreen()
        self.trial = TrialBalanceScreen()
        self.profit = ProfitLossScreen()
        self.sheet = BalanceSheetScreen()
        self.masters = MastersScreen()

        self.screens = [
            ("Voucher Entry", self.voucher),
            ("Day Book", self.daybook),
            ("Ledger", self.ledger),
            ("Trial Balance", self.trial),
            ("Profit && Loss", self.profit),
            ("Balance Sheet", self.sheet),
            ("Masters", self.masters),
        ]
        for _, widget in self.screens:
            self.stack.addWidget(widget)

        self.voucher.posted.connect(self.refresh_all)
        self.voucher.masters_changed.connect(self._masters_changed)
        self.masters.changed.connect(self.refresh_all)
        self.daybook.open_voucher.connect(self._alter)
        self.ledger.open_voucher.connect(self._alter)

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
        for _, widget in self.screens:
            if widget is not self.voucher and hasattr(widget, "refresh"):
                widget.refresh()

        gap = acc.opening_difference()
        if abs(gap) > acc.EPS:
            self.statusBar().showMessage(
                f"Difference in opening balances: {money(abs(gap))} "
                f"{'Dr' if gap > 0 else 'Cr'} — shown as its own line on the "
                "Balance Sheet until the opening balances agree.")


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Books")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
