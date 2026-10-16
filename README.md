# Bookkeeper — Tally-style double-entry bookkeeping

Two front ends over one set of books:

```bash
python desktop.py          # native desktop app (PySide6/Qt)
streamlit run app.py       # browser version
```

Both share `db.py` and `accounting.py` and read the same `data/books.db`, so
you can use whichever suits the moment. The accounting lives in those two
modules, not in either interface.

## Why a desktop build

Voucher entry wants a grid that reacts to every keystroke and function keys
that switch voucher type. Streamlit reruns the whole script on each
interaction, so the browser version is fine for reports but never feels like
Tally for data entry. The desktop app is for entry; use either for reports.

### Keyboard

| Key | Does |
| --- | --- |
| `F4` `F5` `F6` `F7` `F8` `F9` | Contra, Payment, Receipt, Journal, Sales, Purchase |
| `Ctrl+A` | Accept the voucher |
| `Ctrl+1` … `Ctrl+8` | Jump between screens (`Ctrl+8` is Company) |
| `Ctrl+S` | Save the company details, on that screen |
| `Alt+C` | Create a ledger from the line you are on |
| `F2` | Set the voucher date |
| `F11` | Refresh every report |
| `Esc` | Back to voucher entry |
| `Ctrl+Shift+1` … `Ctrl+Shift+5` | Colour scheme |
| `Ctrl+=` / `Ctrl+-` | Text bigger / smaller |

## Text size

**Settings › Text size** — Normal, Large, Larger, Largest — or nudge it with
`Ctrl+=` and `Ctrl+-` while you are reading. Saved in the books as `text_size`,
alongside the colour scheme.

**Large is the default**, two points above the platform size. Sizes are held as
a *step* above whatever your Windows display setting gives, not as absolute
point sizes, so Normal is always exactly the platform's own size on any machine.

The layout follows the size, which took more than setting the application font.
Three kinds of thing do not follow it by themselves:

* **Fonts built by hand.** `QFont(family)` does **not** inherit the application
  font's size — it comes back at a system default of 12pt. That left the
  monospaced amount columns pinned at 12pt, so they would have looked *smaller*
  than their own labels once the body text grew. Build them with `mono_font()`
  and headings with `heading()`, never `QFont(...)` directly.
* **Widgets whose point size was set once in a constructor** — the screen
  headings and the mono labels. They are marked with a `heading` / `mono`
  property when built, and `set_text_size` finds them again and re-fonts them.
* **The window.** It grows with the text, clamped to the display, so a larger
  font does not push the Accept button under the taskbar.

**Long labels must wrap.** A window can never be narrower than its widest
*unwrapped* label, so one long sentence silently sets a floor for the whole
app — the Balance Sheet note was demanding 1770px, wider than a 1366px laptop
screen, and grew with every step. Report captions go through `flowing()`, which
wraps them. `test_desktop.py` guards the floor: no screen may demand more than
1400px at the largest size, and nothing may be clipped.

## Colour schemes

**Settings › Colour scheme**, in the desktop app. Five choices:

| Scheme | Looks like |
| --- | --- |
| **Light** | The default. Dark text on white, on the platform's own widget style — no banding. |
| **Dark** | Dark grey ground, light text, with the status colours lifted so they stay readable. |
| **Bookkeeper Classic** | The DOS-era accounting screen: deep blue `#000080`, cream text, cyan selection bar. |
| **Bookkeeper Light** | The modern take: light body, a blue-grey band behind the headers, a yellow highlight row. |
| **Follow Windows** | Matches the OS light/dark setting. |

The two **Bookkeeper** schemes are the accounting-screen look in its two eras —
the inky DOS blue, and the light one. Plain **Light** is neither; it is just the
platform's own appearance.

Renamed scheme keys are honoured on the way in — `color_scheme` saved as
`tally` still opens **Bookkeeper Classic**, and `tallyprime` opens
**Bookkeeper Light** — so renaming a scheme never silently resets someone's
choice. The map is `theme.ALIASES`.

The choice is saved in the books (`color_scheme` in the `settings` table), so it
survives a restart and travels with the data file. Switching repaints
immediately — there is nothing to restart.

Two things worth knowing if you add a scheme of your own in `theme.py`:

* **Nothing hardcodes a colour outside `theme.py`.** Four status colours carry
  meaning — a balanced voucher is green, out-of-balance red, a Tally-convention
  warning amber, guidance muted — and each is a *token* looked up on the active
  scheme. Previously they were hex literals, which is fine on white and
  illegible on anything else.
* **`test_desktop.py` measures contrast.** Every token in every scheme is
  checked against both backgrounds it can appear on and must clear the WCAG AA
  ratio of 4.5:1, so a new scheme cannot ship with an unreadable status line.
  The tightest in the current set is 5.22:1.

Light stays on the platform's native widget style, so it is identical to how the
app has always looked; the other schemes use Qt's Fusion style, because the
native Windows style paints from the OS theme and ignores the palette — a dark
scheme on it would keep white table headers and buttons.

The Streamlit version is unaffected; it keeps its browser default.

## Company details

**Ctrl+8**, or Masters → Company in the browser version. Fifteen fields:

| | |
| --- | --- |
| Identity | Company name (required), Mailing name |
| Address | Address, State, PIN code, Country, Phone, E-mail |
| Registrations | PAN, GSTIN, TAN, CIN |
| Books | Financial year begins, Books begin on, Currency symbol |

**Blank is always allowed** except the name — these are details you fill in as
you learn them, and refusing to save a half-known address would be worse than
useless. But a registration that *is* filled in has to be well formed, because
a malformed GSTIN is worse than an absent one: it reaches a filing looking
legitimate. PAN, GSTIN, TAN and CIN are stored upper case, and the form shows
them back that way so you can see it happened.

The sharpest check is the cross-reference: **a GSTIN contains its holder's PAN**
at characters 3–12, so if both fields are filled and they disagree, one of them
is wrong — and this is the only place that would ever be noticed.

```
The GSTIN carries PAN BBBPZ1234C, but the PAN field says AAAPZ1234C.
A GSTIN always contains the holder's PAN, so one of the two is wrong.
```

A rejected save **writes nothing and keeps your typing** — losing a form to one
bad character is worse than the bad character.

The field list lives in `db.COMPANY_FIELDS`, and both front ends render from it
and save through `db.save_company`. Adding a field to that tuple puts it on the
Qt screen and in the Streamlit form, validated the same way, with nothing
further to write.

## Creating masters mid-voucher

You rarely know every account before you start entering. Press **Alt+C** (or
the *Create ledger* button) on the voucher screen and the ledger is created
there and then, dropped into the line you were on, and usable immediately — the
same idea as Tally's Alt+C.

Two details that make it worth using rather than breaking off:

* **Whatever you had typed into the cell becomes the name**, so a half-typed
  account is not wasted.
* The dialog **says where the balance will land** — "a liability account, its
  balance will appear on the liabilities side of the Balance Sheet" — because
  the group you pick is the decision that matters, and it is easy to get wrong.

If the group you need does not exist either, **New group…** inside that dialog
creates it without losing the ledger you were part-way through.

The Streamlit version has the same thing as an expander above the grid.

## Structure

It follows Tally's, because the reports fall out of it:

```
Group  →  Ledger  →  Voucher line
```

* **Groups** form a tree, with the 27 reserved groups seeded as Tally has them
  — Capital Account, Sundry Debtors under Current Assets, Sundry Creditors
  under Current Liabilities, Duties & Taxes, Direct and Indirect Expenses, and
  so on. A group's **nature** (asset / liability / income / expense) decides
  which statement a balance lands on. A separate **trading** flag marks the
  accounts that produce gross profit.
* **Ledgers** are what you post to. Each sits under exactly one group and may
  carry an opening balance, entered as a positive amount plus Dr or Cr.
* **Vouchers** hold two or more lines whose debits and credits must agree.

Add your own sub-groups under any reserved group when you want finer
subtotals; a sub-group inherits its parent's nature.

Balances are held **debit-positive** internally: `+500` is 500 Dr, `-500` is
500 Cr. Presentation flips it back.

## Screens

| Screen | What it does |
| --- | --- |
| **Voucher Entry** | Type, date, auto number, narration, then a Dr/Cr grid with ledger autocomplete and running totals. Accept is disabled until the two sides agree. |
| **Day Book** | Every voucher in the period, newest first. Double-click to alter one. |
| **Ledger** | One account: opening balance, every entry with **To**/**By** particulars naming the other side, a running balance, closing. |
| **Trial Balance** | Closing balances as Dr and Cr, by ledger or summarised by group. |
| **Profit & Loss** | Trading account → gross profit, then the indirect accounts → net profit. |
| **Balance Sheet** | Liabilities and assets side by side, with net profit carried to Profit & Loss A/c. |
| **Masters** | Create and alter ledgers and sub-groups. |
| **Company** | Who the books belong to: name, address, PAN, GSTIN, TAN, CIN, financial year, currency. |

## The rules it enforces, and the ones it only advises

**Hard:** a voucher must balance, needs at least two lines, across at least two
different ledgers, each line on one side only. This is checked in `db.py`, not
just in the form, so it holds however the call arrives.

**Advisory:** the cash and bank conventions per voucher type — a Payment should
credit cash or bank, a Receipt should debit it, a Contra should be between two
of them, a Journal should touch neither. You get told, not blocked, because
real books occasionally need the exception.

## Difference in opening balances

Because every voucher balances, the sum of all closing balances always equals
the sum of all **opening** balances. So if your openings disagree, the trial
balance will too — and that is not a problem with any voucher.

Rather than hide it, the residual is shown as **Difference in opening
balances**: as a gap on the trial balance, and as its own line on the balance
sheet so that statement still balances. That is what Tally does.

## Packaging a desktop executable

```bash
pip install -r requirements-desktop.txt pyinstaller
python build_exe.py
```

Produces `dist/Bookkeeper.exe` — copy it anywhere and double-click, no Python
needed on that machine. The books live in `data/books.db` beside the
executable; keep the two together, or set `BOOKS_DB` to put the file somewhere
else such as a OneDrive folder.

## Tests

```bash
python test_books.py                              # the accounting, 92 checks
python test_ui.py                                 # the Streamlit front end
QT_QPA_PLATFORM=offscreen python test_desktop.py   # the desktop front end
```

`test_books.py` works a full set of books by hand — opening balances, a credit
sale part received, a credit purchase part paid, a contra, bank interest — and
asserts the trial balance and balance sheet differences are exactly `0.0` with
no tolerance, including after edits, deletes and custom sub-groups.

`test_desktop.py` drives the real Qt widgets with the offscreen platform, so
the desktop build is tested rather than only eyeballed: function keys, the
disabled Accept button, the balance check, the voucher-type advice, posting,
altering from the Day Book, and creating masters.
