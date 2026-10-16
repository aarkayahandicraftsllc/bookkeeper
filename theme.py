"""Colour schemes for the desktop app.

You sit in front of one window all day, so the scheme is a *setting* rather
than a build-time choice: ``Settings > Colour scheme`` writes ``color_scheme``
into the shared ``settings`` table and the palette is applied live, with no
restart.

Why this is a module of its own instead of stylesheets scattered through
``desktop.py``: several status lines carry MEANING through colour — a balanced
voucher is green, an out-of-balance one red, a Tally-style convention warning
amber, guidance text muted grey. Those four were hardcoded hex, which is fine
on white and unreadable on anything else (``#666`` muted grey on a dark
background). Each is now a token looked up on the active scheme, so adding a
scheme cannot leave a status line illegible — ``test_desktop.py`` measures the
contrast of every token in every scheme and fails below the WCAG AA threshold.

Adding a scheme: add a ``Scheme`` to ``SCHEMES`` and its key to ``ORDER``. The
Settings menu, the persistence and the tests all read those two.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

AUTO = "auto"
DEFAULT = "light"

SETTING_KEY = "color_scheme"


@dataclass(frozen=True)
class Scheme:
    """One colour scheme.

    ``style`` is the Qt widget style to pair it with. Light stays on the
    platform's native style so it is pixel-identical to how the app has always
    looked; the dark and Tally schemes need **Fusion**, because the native
    Windows style paints most widgets from the OS theme and ignores QPalette,
    which would leave a dark palette with white table headers and buttons.
    """

    key: str
    label: str
    window: str          # app background
    base: str            # editable fields, table rows
    alt_base: str        # alternating rows, header sections
    text: str            # primary text
    muted: str           # guidance and hints
    good: str            # balanced, agrees, ready
    bad: str             # out of balance, error
    warn: str            # convention warning, opening difference
    highlight: str       # selection
    highlight_text: str
    border: str
    style: str = "Fusion"

    def color(self, token: str) -> str:
        """The hex for a semantic token, by name."""
        if token not in TOKENS:
            raise KeyError(f"unknown colour token {token!r}; "
                           f"expected one of {', '.join(TOKENS)}")
        return getattr(self, token)


# The semantic tokens call sites are allowed to ask for. Kept explicit so a
# typo raises instead of silently returning a structural colour.
TOKENS = ("text", "muted", "good", "bad", "warn")

SCHEMES: dict[str, Scheme] = {
    "light": Scheme(
        key="light",
        label="Light",
        window="#f0f0f0",
        base="#ffffff",
        alt_base="#f7f7f7",
        text="#202124",
        muted="#5f6368",
        good="#137333",
        bad="#b3261e",
        warn="#705400",
        highlight="#2f6feb",
        highlight_text="#ffffff",
        border="#d0d0d0",
        # The one scheme that keeps the platform look it has always had.
        style="",
    ),
    "dark": Scheme(
        key="dark",
        label="Dark",
        window="#202124",
        base="#292a2d",
        alt_base="#303134",
        text="#e8eaed",
        muted="#9aa0a6",
        good="#81c995",
        bad="#f28b82",
        warn="#fdd663",
        highlight="#8ab4f8",
        highlight_text="#202124",
        border="#3c4043",
    ),
    "classic": Scheme(
        key="classic",
        label="Bookkeeper Classic",
        # The DOS-era accounting screen: deep blue ground, cream text, cyan bar.
        window="#000080",
        base="#0000a0",
        alt_base="#000090",
        text="#ffffcc",
        muted="#c6c6f0",
        good="#7cff7c",
        bad="#ff9b9b",
        warn="#ffe066",
        highlight="#00ffff",
        highlight_text="#000080",
        border="#6a6ac8",
    ),
    "bookkeeper_light": Scheme(
        key="bookkeeper_light",
        label="Bookkeeper Light",
        # The modern accounting-screen look: a light body rather than a blue
        # ground, a blue-grey band behind the headers, a yellow highlight row.
        # Distinct from the plain Light scheme, which is simply the platform's
        # own grey-and-white with no banding.
        window="#eef2f7",
        base="#ffffff",
        alt_base="#dbe5f1",
        text="#14213d",
        muted="#515b70",
        good="#13653a",
        bad="#b3261e",
        warn="#6b4e00",
        highlight="#ffd400",
        highlight_text="#1a1a1a",
        border="#b8c6da",
    ),
}

# Order shown in the Settings menu. AUTO last, since it is a rule rather than
# a scheme. The two Bookkeeper schemes sit together: the DOS-era screen and
# the modern one.
ORDER = ("light", "dark", "classic", "bookkeeper_light", AUTO)

# Keys that have been renamed. A saved preference is a stored value, so an old
# one must keep working rather than silently resetting to Light. Both of these
# date from 2026-10-16, when the two schemes were renamed off the Tally name.
ALIASES = {
    "tally": "classic",                 # was "Tally classic"
    "tallyprime": "bookkeeper_light",   # was "TallyPrime light"
}

LABELS = {key: SCHEMES[key].label for key in SCHEMES} | {
    AUTO: "Follow Windows",
}

_active: Scheme = SCHEMES[DEFAULT]


def detect_os_scheme() -> str:
    """"light" or "dark", following the OS where we can read it.

    Qt 6.5+ exposes this through style hints. Falls back to the Windows
    registry, then to light - an unknown OS preference should not leave the
    app in a scheme the user never chose.
    """
    try:
        from PySide6 import QtCore, QtGui

        hints = QtGui.QGuiApplication.styleHints()
        if hints is not None:
            value = hints.colorScheme()
            if value == QtCore.Qt.ColorScheme.Dark:
                return "dark"
            if value == QtCore.Qt.ColorScheme.Light:
                return "light"
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            with key:
                light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if light else "dark"
        except Exception:
            pass

    return "light"


def resolve(key: str) -> Scheme:
    """Turn a stored preference into a scheme.

    Renamed keys are honoured, so a preference saved under an old name still
    opens in the scheme the user chose. Anything genuinely unknown falls back
    to the default rather than raising - a bad settings row should not stop the
    app from opening.
    """
    key = (key or "").strip().lower()
    key = ALIASES.get(key, key)
    if key == AUTO:
        key = detect_os_scheme()
    return SCHEMES.get(key, SCHEMES[DEFAULT])


def stylesheet(scheme: Scheme) -> str:
    """What QPalette cannot express.

    Muted labels are styled by object name rather than inline, so that
    switching scheme repaints the ones set up once in a constructor - they are
    never touched again, unlike the status lines a refresh rewrites.
    """
    rules = [f"QLabel#muted {{ color: {scheme.muted}; }}"]
    if scheme.style:  # Fusion schemes: palette alone leaves these pale
        rules += [
            f"QHeaderView::section {{ background: {scheme.alt_base};"
            f" color: {scheme.text}; border: 0px;"
            f" border-right: 1px solid {scheme.border};"
            f" border-bottom: 1px solid {scheme.border}; padding: 4px; }}",
            f"QTableWidget, QTableView {{ gridline-color: {scheme.border};"
            f" background: {scheme.base}; }}",
            f"QTableCornerButton::section {{ background: {scheme.alt_base};"
            f" border: 0px; }}",
            f"QMenuBar::item:selected, QMenu::item:selected {{"
            f" background: {scheme.highlight};"
            f" color: {scheme.highlight_text}; }}",
            f"QStatusBar {{ color: {scheme.muted}; }}",
            f"QToolTip {{ background: {scheme.base}; color: {scheme.text};"
            f" border: 1px solid {scheme.border}; }}",
        ]
    return "\n".join(rules)


def palette(scheme: Scheme):
    """A QPalette for the scheme. Imported lazily so theme.py stays testable
    without a QApplication."""
    from PySide6 import QtGui

    role = QtGui.QPalette.ColorRole
    group = QtGui.QPalette.ColorGroup
    pal = QtGui.QPalette()

    def put(r, value, groups=(group.Active, group.Inactive)):
        for g in groups:
            pal.setColor(g, r, QtGui.QColor(value))

    put(role.Window, scheme.window)
    put(role.WindowText, scheme.text)
    put(role.Base, scheme.base)
    put(role.AlternateBase, scheme.alt_base)
    put(role.Text, scheme.text)
    put(role.Button, scheme.window)
    put(role.ButtonText, scheme.text)
    put(role.ToolTipBase, scheme.base)
    put(role.ToolTipText, scheme.text)
    put(role.PlaceholderText, scheme.muted)
    put(role.Highlight, scheme.highlight)
    put(role.HighlightedText, scheme.highlight_text)
    put(role.Link, scheme.highlight)

    # Disabled widgets: muted everywhere, or a dark scheme shows black-on-dark.
    for r in (role.WindowText, role.Text, role.ButtonText):
        pal.setColor(group.Disabled, r, QtGui.QColor(scheme.muted))
    pal.setColor(group.Disabled, role.Base, QtGui.QColor(scheme.window))
    return pal


def apply(app, key: str) -> Scheme:
    """Apply a scheme to a live QApplication and remember it as active.

    Order matters: the style is swapped first, because ``setStyle`` installs
    the style's own standard palette and would undo ours.
    """
    global _active
    scheme = resolve(key)
    remember_native_style(app)

    if scheme.style:
        app.setStyle(scheme.style)
    elif _native_style:
        app.setStyle(_native_style)

    app.setPalette(palette(scheme))
    app.setStyleSheet(stylesheet(scheme))
    _active = scheme
    return scheme


_native_style = ""


def remember_native_style(app) -> None:
    """Record the platform's own style name, before anything switches it.

    The Light scheme goes back to the platform style so it looks exactly as the
    app always has; without this it would be stuck on Fusion once the user had
    tried a dark scheme.
    """
    global _native_style
    if not _native_style:
        _native_style = app.style().objectName()


def active() -> Scheme:
    return _active


def color(token: str) -> str:
    """The active scheme's hex for a semantic token."""
    return _active.color(token)


def fg(token: str) -> str:
    """A ready-made stylesheet for coloured text: ``theme.fg("good")``."""
    return f"color: {color(token)};"
