# vcard-normalizer

A Python CLI to clean, merge, and export address books from multiple sources
(iCloud, Protonmail, Google, Outlook, etc.) into a single normalised vCard 4.0
file.

---

## The core workflow: merging multiple sources

```
cards-merge/
  icloud.vcf        ← exported from iCloud / Apple Contacts
  protonmail.vcf    ← exported from Proton Mail
  google.vcf        ← exported from Google Contacts (optional)
```

```sh
vcard-normalize merge --owner-name "James"
```

That's it. The tool reads every `.vcf` in the folder, strips proprietary Apple /
Google fields and all photos, normalises phone numbers to international format,
detects duplicates *across sources* (same person in iCloud and Protonmail),
interactively merges them, auto-tags categories, and writes one clean output
file.

---

## How to export from each source

### Apple iCloud
1. Open **Contacts.app** on Mac
2. Select all (`⌘A`) → **File → Export → Export vCard…**
3. Save as `cards-merge/icloud.vcf`

### Proton Mail
1. Go to **proton.me/mail** → Settings → **Contacts**
2. Click **Export** → Export all → download the `.vcf`
3. Save as `cards-merge/protonmail.vcf`

### Google Contacts
1. Go to **contacts.google.com**
2. Click **Export** → vCard (for iOS) → **Export**
3. Save as `cards-merge/google.vcf`

### Outlook / Microsoft 365
1. Open **Outlook** → People → **Manage → Export contacts**
2. Choose "All contacts" and `.vcf` format
3. Save as `cards-merge/outlook.vcf`

---

## Features

### M1 — Core normalisation & deduplication
- Parse vCard 3.0 and 4.0 files from any source.
- Strip proprietary vendor fields (Apple `X-AB*`, Google `X-GOOGLE*`, generic `X-*`).
- Strip photos, logos, and sound clips — they bloat the file for no benefit.
- Detect duplicates via email, phone, and fuzzy name matching (rapidfuzz).
- Interactive TUI merge: choose base card, union all data, or skip.
- Export sorted, clean vCard 4.0 UTF-8.

### M2 — Phone number normalisation
- Converts bare local numbers (`07980 220 220`) to E.164 international (`+44 7980 220 220`).
- Infers country from the contact's address when present; falls back to `default_region`.
- Phone normalisation runs **before** deduplication so `07980220220` and
  `+447980220220` are correctly treated as the same person.

### M3 — Categories & KIND
- Rule-based auto-tagging from `local/vcard.conf` (Work, School, Medical, etc.).
- Interactive category review in `--interactive` mode.
- Heuristic `KIND` assignment (individual vs org).

### M4 — Reporting
- Per-source breakdown in the summary (how many cards from iCloud, Protonmail, etc.).
- `--diff` flag: per-contact change log in the terminal.
- `--write-changelog`: saves `<output>.changes.txt`.
- `--dry-run`: full preview with no files written.

---

## Install

```sh
pipx install .
# or:
pip install -e ".[dev]"
```

Requires Python >= 3.11.

---

## Commands

### `merge` — the recommended command for multi-source workflows

```sh
# Drop .vcf files into cards-merge/, then:
vcard-normalize merge --owner-name "James"

# Non-interactive (auto-merge), dry run to preview first:
vcard-normalize merge --owner-name "James" --no-interactive --dry-run --diff

# Specify a different source folder:
vcard-normalize merge --owner-name "James" --dir ~/Downloads/vcards/
```

### `ingest` — direct glob control

```sh
# Explicit file globs
vcard-normalize ingest \
  --input "cards-raw/icloud.vcf" \
  --input "cards-raw/protonmail.vcf" \
  --owner-name "James"
```

---

## CLI options (both commands)

| Option | Default | Description |
|---|---|---|
| `--owner-name` / `-n` | required | Your name (used in output filename) |
| `--output` / `-o` | auto-named | Explicit output `.vcf` path |
| `--region` / `-r` | `GB` | Default ISO-2 region for phone parsing |
| `--interactive/--no-interactive` | interactive | TUI for merges + categories |
| `--auto-categories/--no-auto-categories` | on | Rule-based category tagging |
| `--dry-run` | off | Process but write nothing |
| `--diff` | off | Print per-contact changes |
| `--write-changelog` | off | Write `.changes.txt` alongside VCF |
| `--keep-unknown` | off | Keep unrecognised `X-*` fields |
| `--prefer-v` | `4.0` | Target vCard version (`3.0` or `4.0`) |

`merge` also takes `--dir` (default: `cards-merge/`).

---

## Configuration (`local/vcard.conf`)

Auto-created on first run. TOML format.

```toml
owner_name = "James"
default_region = "GB"

[[category_rules]]
name = "Work"
patterns = [" ltd", " plc", " llc", " inc",
            "re:@(?!gmail\\.|yahoo\\.|hotmail\\.|outlook\\.)"]

[[category_rules]]
name = "School"
patterns = ["school", "university", "college", ".edu"]

[[category_rules]]
name = "Medical"
patterns = ["doctor", "dr.", "clinic", "hospital", "nhs"]
```

---

## Project layout

```
cards-merge/        ← drop exported .vcf source files here
cards-raw/          ← legacy / single-file input
cards-clean/        ← output directory (auto-created)
local/vcard.conf    ← your personal config (auto-created)
src/vcard_normalizer/
  cli.py            ← merge + ingest commands
  io.py             ← file reading, source tracking
  normalize.py      ← field parsing, photo stripping
  dedupe.py         ← similarity scoring, clustering
  formatters.py     ← phones, categories, KIND
  exporter.py       ← vCard 4.0 serialisation
  report.py         ← summary, diff, changelog
  config.py         ← TOML config + workspace setup
  proprietary.py    ← X-* field stripping rules
  interactive.py    ← TUI merge prompts
```

---

## Development

```sh
pip install -e ".[dev]"
pytest
ruff check src/
mypy src/
```

---

## License

GPL-3.0-or-later
