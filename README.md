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
| `F3` | Switch company |
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

## More than one company

**The app opens first, then asks.** It comes up on the company you used last,
and a **Select company** dialog appears over the running window with a
dropdown of the companies it found. Keep the one you are in (Cancel), pick
another, or press **New company…**. Inside the app, **F3** (Company ▸ Switch
company) brings the same dropdown back.

Nothing is ever created on the way in. A fresh install opens the default
`books.db` — exactly as the app behaved before it knew about more than one
company — rather than demanding a company be created before you can see
anything. Creating one is always a button you press.

**Each company is its own database file** in `data/`, named after the company:

```
data/aarkaya-handicrafts-llc.db
data/shubh-traders.db
data/books.db
```

That is how Tally keeps a company per data folder, and it is why the accounting
code did not have to change: no query needed a company filter. It also means a
company is backed up, copied or handed to someone by moving one file. The
trade-off is no cross-company reporting — nothing in the app reports across
companies anyway.

**The folder is the list.** There is no index file to fall out of step with
what is on disk, so dropping a company file into `data/` makes it appear and
taking one out makes it vanish. Files with `backup`, `tmp` or `old` in the name
are skipped, or the backup beside your books would show up as a second company
with the same name.

A few details worth knowing:

* Creating a company asks only for **name, financial year, books-begin date and
  currency** — enough to enter a voucher. Address, PAN and GSTIN are filled in
  afterwards on the Company screen, rather than facing you with fifteen fields
  before you can do anything.
* **Two companies may share a name**; the second file gets a `-2` suffix.
* **Switching closes and reopens the window** rather than rebuilding eight
  screens against a different database. If a voucher is part-entered you are
  warned first, since leaving discards it. Choosing the company you are already
  in does nothing at all.
* Because the dialog opens **over a running window**, it simply inherits that
  company's colours and text size — those settings live inside each company's
  file, and a dialog shown *before* the window would have appeared in the
  wrong ones.
* The window remembers **which file it was opened with** (`company_file`), and
  the dialog preselects from that rather than from `db.DB_PATH` — creating a
  company switches the data layer as a side effect, so the two can differ for
  a moment, and a cancel puts it back.
* **Appearance and company details are per company.** Each file carries its own
  `color_scheme`, `text_size`, currency and financial year.
* `BOOKS_DB` **pins the file and switches the picker off** — the test suites
  and anyone pointing at a shared folder have already chosen. `BOOKS_DIR` moves
  the whole company folder.
* The browser version has a **Company selector in the sidebar** instead, since
  a browser tab has no launch moment. It creates nothing; use the desktop app
  for that.

## Backups

Copies of the books live in **`data/backups/`**, named for the company they
came from and when they were taken:

```
data/backups/books-20261018-150337-open.db
data/backups/books-20261018-145823-manual.db
```

**One is taken every time the desktop app opens**, before anything is entered,
so whatever a session does the books as they were are already safe. Switching
company (`F3`) takes one of the company being opened too, since that comes back
round the same loop in `main()`.

**Company ▸ Back up now** (`Ctrl+B`) takes one on demand — for before you do
something you are unsure about. **Company ▸ Open backup folder** opens it in
Explorer. Streamlit gets the button but not the automatic copy: it re-runs the
whole script on every interaction, so "on open" has no meaning in a browser tab
and hooking it there would copy the books on every click.

The last **20** per company are kept (`db.KEEP_BACKUPS`) and older ones pruned.
These are tens of kilobytes, unlike the 144 MB the exe archive has to ration.
A prune that cannot delete a file gives up on that file rather than failing —
Windows will refuse to delete what something else has open, and a backup folder
you happen to be browsing must not be able to stop a backup being taken.

Three things about how it works that are not obvious:

* **It uses SQLite's own online backup, not a file copy.** A copy taken while a
  write is in flight can capture a torn database, and it looks perfectly fine
  right up to the day you need it. `test_books.py` runs `PRAGMA
  integrity_check` on a backup and compares its voucher count with the live
  books, because "a file appeared" is not the same as "a backup exists".
* **Each backup carries the hash of the books it came from**, stamped into its
  own `settings` table as `backup_source_sha256`, alongside which file and when.
  This is what lets an unchanged book be skipped instead of copied again —
  opening the app five times without entering anything leaves one copy, not
  five, so the useful ones are not pushed out. It has to be *carried* rather
  than recomputed: the backup API rebuilds the file page by page, so the copy
  is logically identical but **not byte-identical** to its source and hashing
  the copy tells you nothing about where it came from.
* **They sit in a subfolder so they can never be mistaken for a company.**
  `company_files()` globs `*.db` without recursing, so the folder is invisible
  to the picker whatever the files are called. The name-based guard
  (`_NOT_COMPANIES`) still covers the older flat `books.backup-....db`.

**What this does not protect against.** The backups are on the same disk as the
books. They cover a mistake, a bad import or a corrupted file; they do **not**
cover the drive failing, the laptop being lost, or the folder being deleted. For
that, `data/` needs to be copied somewhere else — another drive, or a synced
folder. Nothing in the app does that for you.

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

## Choosing the period

Every report carries a **Period** dropdown listing the financial years the
books touch — `FY 2025-2026`, `FY 2026-2027` — so "the balance sheet for
2025-2026" is one choice rather than two typed dates. The From/To editors stay
beside it for a period that is not a whole year.

A year means the **whole** year, opening day to closing day — including a
closing day still in the future for the year in progress. A year named in a
dropdown has to mean that year; clamping the end to today, as this first did,
quietly reports a different period from the one on screen.

The list comes from the **data** — voucher dates and the books-begin date — so
it grows by itself and there is nothing to maintain. The year before the
current one is offered even with nothing posted in it, because comparing with
last year is routine and a prior-year balance sheet is meaningful from the
opening balances alone. Earlier years than that have to be earned by a voucher
dated in them.

A financial year is **not** assumed to start in April. It follows
`fy_start_month` on the Company screen, and books that run the calendar year
are a different shape rather than a special case: the year ends in December of
its own year and is labelled `2026`, since `2026-2026` would be nonsense.

**Custom dates…** asks for them. A period report is asked for a From and a To;
an as-at report is asked for one date, because a balance sheet is drawn at a
moment and its balances run from the beginning of the books whatever you put in
a start field — offering one would be offering a control that does nothing. The
dialog refuses a period that ends before it starts, and cancelling leaves both
the dates and the dropdown exactly as they were.

Choosing it used to do nothing at all: the dropdown changed, the editors were
left alone, and if **Since books began** had been chosen first the From editor
was still disabled, so a custom period could never be given a start date.
Typing in the date editors is the other way in, and it re-enables From for the
same reason.

Editing a date by hand also moves the dropdown to **Custom dates…**. Leaving it
reading "FY 2026-2027" over a period that is no longer that year would be a
lie about what you are looking at — and the one thing a report must not do is
misdescribe its own period. Period reports (Day Book, Ledger, P&L) also carry
**Since books began** in the same dropdown rather than beside it as a tickbox:
it is one of the periods you can choose, and a row holding both was 1468px
wide at the largest text size, over the 1400px ceiling.

The arithmetic is in `accounting.py` — `fy_bounds`, `fy_label`,
`financial_years`, `current_financial_year` — and **shared by both front
ends**, which each used to work it out for themselves. That is two places for
"when does the year end" to be wrong in different ways. `test_books.py` works
the boundaries by hand: April and January years, the first and last day of a
year, a leap day, an unbroken run of years with no gaps or repeats, and a
start month that is garbage falling back to April rather than stopping the
reports from opening.

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

Produces **`Bookkeeper.exe` in this folder, beside `data/`** — copy the two
together anywhere and double-click, no Python needed on that machine.

**The books live in a `data` folder next to the executable.** That is why the
exe is built here rather than into `dist/`: here, the packaged app and
`python desktop.py` read the *same* books. Built into `dist/` they had a set
each, and vouchers entered through one were missing from the other. Set
`BOOKS_DIR` to override — a OneDrive or shared folder, say.

> **This was a real data-loss bug, fixed 2026-10-16.** The data folder was
> anchored on `__file__`, and a PyInstaller *onefile* build unpacks itself into
> a temporary directory that is **deleted when the app exits** — so the
> packaged app wrote its books somewhere that ceased to exist the moment it
> closed, having looked throughout as though it had saved. A company created in
> the exe, with journals entered, was gone on the next launch and was not
> recoverable. `db._app_dir()` now anchors on `sys.executable` when
> `sys.frozen` is set. It is invisible from source, where `__file__` is
> correct, so `test_books.py` pretends to be frozen and asserts the anchor
> follows the executable.
>
> For the same reason `build_exe.py` no longer wipes its output folder — that
> folder holds real books.

## Tests

```bash
python test_books.py                               # the accounting
python test_ui.py                                  # the Streamlit front end
QT_QPA_PLATFORM=offscreen python test_desktop.py   # the desktop front end
python test_multi_company.py                       # choosing a company
```

The first three set `BOOKS_DB`, which pins the data file and switches the
company picker off — so they cover everything *except* the way the app actually
starts. `test_multi_company.py` runs unpinned, with `BOOKS_DIR` on a scratch
folder, and drives the real launch path in both front ends: creating companies,
that their books are genuinely separate, the picker's listing and preselection,
switching, and that a backup file is not mistaken for a company.

All four point `BOOKS_DIR` at a temporary folder, so no suite can write a
company into your real `data/` directory.

`test_books.py` works a full set of books by hand — opening balances, a credit
sale part received, a credit purchase part paid, a contra, bank interest — and
asserts the trial balance and balance sheet differences are exactly `0.0` with
no tolerance, including after edits, deletes and custom sub-groups.

`test_desktop.py` drives the real Qt widgets with the offscreen platform, so
the desktop build is tested rather than only eyeballed: function keys, the
disabled Accept button, the balance check, the voucher-type advice, posting,
altering from the Day Book, and creating masters.

What a screen LOOKS like is the one thing these cannot assert. `screenshot.py`
renders the real screens to PNGs in `shots/`, so a change to any of them can be
compared against the build before it:

```bash
python screenshot.py                        # every scheme, three screens
python screenshot.py --scheme dark --tag after
python screenshot.py --screens 0 3          # Voucher Entry, Trial Balance
```

It copies your books into a scratch folder and pins `BOOKS_DB` to the copy, so
taking a screenshot cannot write to `data/`, and it never shows the window. It
runs on the *native* platform rather than offscreen on purpose: Light keeps the
native widget style, and offscreen would render it as Fusion — that is, not the
thing being judged.
