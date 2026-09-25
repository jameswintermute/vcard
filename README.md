![GPL-3.0 License](https://img.shields.io/badge/license-GPLv3--or--later-blue)
![Offline First](https://img.shields.io/badge/offline-first-green)
![Standard vCard](https://img.shields.io/badge/standard-vCard%204.0-orange)

# vCard

### Own Your Contacts. Protect Your Relationships.

> A free software, offline-first local Web UI for reclaiming control of your address book.

---

## ✊ Reclaim Your Contacts. Reclaim Your Privacy.

Before the internet became commercial infrastructure, an address book was something deeply personal. It held the names and numbers of the people who mattered — friends, family, colleagues, neighbours. It represented relationships built over years.

It was private.  
It was trusted.  
It was yours.

The early web was built on openness, decentralisation, and shared standards. It was never designed so that third parties could quietly harvest, analyse, and monetise our personal networks.

Yet today, contact lists are routinely uploaded, scanned, enriched, and embedded into corporate ecosystems. Additional fields are injected. Identifiers are rewritten. Portability becomes friction.

If you cannot inspect the code that processes your relationships,  
you do not truly control them.

Rooted in open standards and the spirit of the GNU GPL, this project restores clarity and stewardship to something very human — your connections.

---

## 🎯 What This Project Does

This tool helps you:

- **Own your contacts** — the real people in your life — rather than rent that information to platforms.
- **Consolidate and de-duplicate** multiple exports into a single clean dataset.
- **Auto-format and normalise** standards-compliant vCard 4.0 records.
- **Remove proprietary clutter** and vendor-specific fields.
- **Keep contacts portable** across platforms without lock-in.
- **Work entirely offline** — no telemetry, no cloud dependency.

The result:

A concise, accurate, usable contact list  
that you control completely.

---

## 🤝 How Will This Actually Help Me?

This project is not trying to replace your contact app.

It exists for moments like:

- You are consolidating multiple accounts (Apple, Google, Proton, Outlook).
- You want a clean master copy of your contacts.
- You are switching platforms and don't trust automatic migration.
- You suspect you have duplicates or inconsistent formatting.
- You want a portable, standards-compliant address book you control.

In practical terms, it helps by:

- Removing duplicate entries across exports.
- Standardising phone numbers to international format (E.164).
- Stripping vendor-specific fields that accumulate over time.
- Producing a clean, portable vCard 4.0 file.
- Letting you review and merge contacts intentionally.

It does not:

- Sync automatically.
- Upload your data anywhere.
- Replace your phone's contacts app.
- Collect analytics.

It simply gives you a clean, trustworthy master copy of your address book.

---

## 🌐 Local Web Interface (Offline First)

This application runs entirely on your machine.

It launches a local Web UI at **http://localhost:8421**, allowing you to:

- Upload exported `.vcf` files from Apple, Google, Proton, or Outlook
- Review and merge detected duplicates interactively
- Edit, add, and delete contacts
- Link related contacts — spouses, partners, family, colleagues
- Assign contacts as members of an organisation card
- Apply category rules and quality filters
- Export a clean, normalised vCard 4.0 file — combined or as individual per-card files

There is:

- No remote server  
- No background syncing  
- No external API calls  
- No data leaving your device

Your address book stays exactly where it belongs — with you.

---

## 🚀 Getting Started

### Dependencies

**Python 3.11 or later** is required.

| Package | Required | Purpose |
|---------|----------|---------|
| `vobject` | ✅ Required | vCard 2.1 / 3.0 / 4.0 parsing |
| `typer` | ✅ Required | CLI interface |
| `rich` | ✅ Required | Terminal output |
| `rapidfuzz` | ✅ Required | Fuzzy duplicate detection |
| `phonenumbers` | ✅ Strongly recommended | Google's libphonenumber for correct E.164 normalisation and international display formatting. Graceful fallback if missing. |

---

### Ubuntu / Debian Linux

```bash
# Install Python 3.11+ and git (usually already present)
sudo apt update && sudo apt install python3 python3-pip git

# Clone the project
git clone https://github.com/jameswintermute/vcard.git
cd vcard

# Install web UI dependencies (no Xcode / compiler needed)
pip install -r requirements.txt
# Ubuntu 23.04+ may require: pip install --break-system-packages -r requirements.txt

# Or install everything including the CLI terminal launcher:
# pip install -e ".[full]"

# Launch
python3 start-webui.py
```

Then open: **http://localhost:8421**

---

### macOS

**Important:** Do not use Homebrew to install Python — Homebrew requires Xcode Command Line Tools, which triggers a large download. Use the official Python installer from python.org instead.

**Step 1 — Install Python 3.12 from python.org:**

Go to [https://www.python.org/downloads/](https://www.python.org/downloads/) and download the macOS installer. Run it and follow the prompts. No Xcode or Homebrew needed.

**Step 2 — Download vCard Studio:**

```bash
git clone https://github.com/jameswintermute/vcard.git
cd vcard
```

Or download and unzip the repository from GitHub.

**Step 3 — Launch:**

**Option A — Double-click (easiest):**

Find `vcard-studio.command` in the project folder and double-click it. The first time, macOS will ask if you're sure — click Open. The script checks for Python, installs any missing dependencies automatically, and opens your browser.

**Option B — Terminal:**

```bash
cd /path/to/vcard
pip3 install -r requirements.txt
python3 start-webui.py
```

Then open: **http://localhost:8421**

> **Apple Silicon (M1/M2/M3):** All dependencies have native ARM wheels — no Rosetta needed.

> **"Cannot be opened because it is from an unidentified developer":** Right-click `vcard-studio.command` → Open → Open. You only need to do this once.

---

### Windows

WSL2 is strongly recommended. Native Windows is supported but has minor limitations.

**Option A — WSL2 (recommended):**

```powershell
# In PowerShell (as Administrator):
wsl --install

# Restart, then open Ubuntu from the Start menu.
# Follow the Ubuntu instructions above from inside WSL.
```

**Option B — Native Windows:**

```powershell
# 1. Install Python 3.12 from https://python.org
#    Check "Add Python to PATH" during installation.
# 2. Install Git from https://git-scm.com

git clone https://github.com/jameswintermute/vcard.git
cd vcard
pip install -e ".[phonenumbers]"
python start-webui.py
```

> **Windows note:** If the server fails to start ("address already in use"), close the previous  
> terminal window and try again. WSL2 avoids this limitation.

---

### Troubleshooting

**The browser opens but shows no contacts / cards-in not recognised**

Always run from the project root directory:
```bash
cd /path/to/vcard
python3 start-webui.py
```
If files in `cards-in/` are still not recognised, check the terminal for error output.

**Port 8421 already in use**

```bash
# Linux / macOS:
lsof -i :8421
kill <PID shown>
python3 start-webui.py
```

**"Quit" button does nothing**

Some browsers block `confirm()` dialogs on localhost. Check your browser's popup settings  
for `localhost`, or stop the server from the terminal with `Ctrl-C`.

**`ModuleNotFoundError: No module named 'vcard_normalizer'`**

Run from the project root with the package installed:
```bash
cd /path/to/vcard
pip install -e .
python3 start-webui.py
```

**`externally-managed-environment` error (Ubuntu 23.04+)**

```bash
# Option A — override the guard (simple):
pip install --break-system-packages -e ".[phonenumbers]"

# Option B — use a virtual environment (cleaner):
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[phonenumbers]"
python3 start-webui.py
```

---

## ⚙ Features

- **vCard 3.0 & 4.0** parsing and standards-compliant 4.0 export
- **Provider-aware cleaning** — normalises Apple grouped metadata such as `X-ABLabel`, preserves useful provider semantics, and strips unsupported proprietary noise without treating every `X-*` field as disposable
- **Non-destructive additive import** — the permanent master record is authoritative; imports fill gaps and union multi-value fields rather than replacing a richer master contact
- **Cross-source duplicate detection** via email, phone, and fuzzy name matching, followed by the same lossless field-aware merge used by normal import
- **Phone number normalisation** to E.164 international format, with GOV.UK style display spacing (e.g. `+44 1932 269627`). Optional `phonenumbers` package for global number validation.
- **Typed and labelled contact data** — email, phone, URL and address metadata can retain HOME/WORK/MOBILE types, preferred status and Apple custom labels
- **Nicknames and URLs** — first-class central fields preserved through normal and Apple-compatible exports
- **Category tagging** — rule-based auto-tagging via `local/vcard.conf`, with interactive review
- **KIND classification** — individual, organisation, group and self/profile semantics
- **Self / profile card** — tag your own card as KIND=self; skipped in duplicate checks and quality reports
- **RELATED linking** — link spouses, partners, siblings, parents, children with bidirectional vCard 4.0 RELATED properties
- **Membership linking** — standards-compliant vCard 4.0 `MEMBER` for `KIND=group`; organisation membership is preserved with a vCard Studio extension rather than emitting invalid RFC 6350 combinations
- **Stable central identity** — every card carries a vCard Studio UID while provider-issued UIDs are retained as external aliases for safer re-import matching
- **Address normalisation** — single-line address detection, structured field parsing, address type/custom-label preservation and Apple country hints
- **Quality review** — scan contacts for missing emails, phones, addresses, categories; mark any field as "not required" to permanently exclude it from future scans
- **Birthdays & Anniversaries tab** — month-by-month view of birthdays and anniversaries with age calculation; configurable category filter; printable birthday calendar
- **Raw vCard viewer** — inspect the full vCard source of any contact with syntax highlighting
- **Export options** — combined `.vcf`, Apple/iCloud-compatible `.vcf`, per-category `.vcf`, individual file per contact, and `.csv`
- **Permanent master autosave** — every edit is immediately persisted to the central master and individual-contact files

---

## 📂 Project Layout

```
cards-in/               ← drop .vcf files here to import (processed once, then moved)
  processed/            ← imported files moved here automatically after import
cards-master/           ← permanent master database (primary store — never delete)
  master.vcf            ← compiled master: all contacts in one file (fast load)
  master.json           ← metadata: saved_at, total count, source files
  contacts/             ← one .vcf per contact, named by canonical UID
    vcard-studio-<uuid>.vcf
cards-out/              ← exports for sharing (Apple, category subsets, CSV)
print/                  ← generated address label and address book HTML files
log/
  activity.log          ← syslog-style activity log (counts and UIDs only, no names)
local/vcard.conf        ← your personal config (auto-created on first run)
src/vcard_normalizer/
  server.py             ← local HTTP server and all API endpoints
  static/index.html     ← the entire Web UI (single-file, no build step)
  model.py              ← canonical Card/Address/TypedValue data model
  normalize.py          ← provider-aware field parsing and cleaning
  merge.py              ← non-destructive, field-aware merge engine
  dedupe.py             ← similarity scoring and duplicate clustering
  formatters.py         ← phones, categories, KIND classification
  exporter.py           ← canonical vCard 4.0 and Apple-compatible serialisation
  master.py             ← permanent master database and additive import matching
  activitylog.py        ← syslog-style activity logging
  checkpoint.py         ← legacy (kept for migration compatibility)
  config.py             ← TOML config and workspace initialisation
  proprietary.py        ← unsupported X-* stripping rules
  print_modules/        ← pluggable printer support (see below)
    __init__.py         ← auto-discovers modules at startup
    brother_ql820nwb.py ← Brother QL-820NWB label printer
    generic_a4.py       ← generic A4 / US Letter office printer
    README.md           ← contributor guide for adding new printers
start-webui.py          ← launch script
```

### How the database works

`cards-master/` is your permanent address book and the **authoritative system of record**. Every edit writes two places simultaneously:

1. `contacts/<uid>.vcf` — the individual contact file, updated immediately
2. `master.vcf` — the compiled view, rewritten on every save

On startup, `master.vcf` is loaded directly (fast). If it is ever missing or corrupt, the server automatically reconstructs it from the individual `contacts/` files.

**Import** (`cards-in/`) is deliberately **additive and non-destructive**. Matching contacts are enriched field-by-field: missing scalar values are filled, multi-value data such as email/phone/address/category/relationship data is unioned, and an incoming conflicting scalar does not silently replace a populated master value. Provider-issued UIDs are retained as aliases so later provider exports can continue to match the same central contact.

**Duplicate resolution** uses the same field-aware merge rules as import. This avoids the previous failure mode where an import preserved a central field but a subsequent automatic duplicate merge selected another whole card and discarded it.

**Export** (`cards-out/`) never modifies master state. Full exports use vCard 4.0; the Apple/iCloud target uses vCard 3.0 plus Apple-compatible metadata and a private round-trip safety capsule for central fields Apple vCard 3.0 cannot express directly.

**Activity log** (`log/activity.log`) records what happened and when — import counts, edit UIDs, export filenames — without recording any contact names, emails, or addresses.

### Apple / iCloud round-trip

The recommended workflow is:

```text
vCard Studio master → Apple export → iCloud / Contacts → iCloud export → cards-in/ → master
```

The central master remains authoritative throughout that cycle. An iCloud re-import may add a new phone, email, URL, address or other missing information, but it cannot replace an already populated central scalar merely because the Apple card contains more fields overall.

The Apple adapter understands grouped Apple metadata such as `itemN.X-ABLabel` and `itemN.X-ABADR`, preserving useful phone/email/URL/address labels instead of deleting every `itemN.X-*` line. Apple-native company/profile hints, special-date metadata and related-name metadata are emitted where useful. vCard Studio also retains central-only values in a compact `[vCS: ...]` NOTE capsule so fields such as relationships, membership, gender and anniversary information can be reconstructed if Apple does not preserve a native equivalent.

Apple/iCloud **Lists are not the same thing as vCard `CATEGORIES`** and are not reconstructed by a normal `.vcf` round-trip. vCard Studio categories remain central contact metadata; use Apple's own archive facilities if Apple List membership itself must be backed up.

---

## ⚙ Configuration (`local/vcard.conf`)

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

## 📖 A Brief History

Version 1.0 of this project was a user-written command-line tool. It handled the core workflow — parsing multiple `.vcf` exports, stripping proprietary fields, normalising phone numbers, deduplicating across sources, and writing a clean output file — entirely from the terminal.

From version 3.0 onwards the project became a fully featured local Web UI. The CLI pipeline remains the processing backbone, but the primary interface is now a browser-based application running on `localhost:8421`. No build tools, no framework dependencies, no cloud — just a Python server and a single HTML file.

---

## 🧾 License

Released under the GNU General Public License (GPL-3.0-or-later).

You are free to:

- Use it  
- Study it  
- Modify it  
- Share it

Transparency matters when handling personal relationships.

---

## 📚 Further Reading

- Electronic Frontier Foundation (EFF)  
  https://www.eff.org

- The Age of Surveillance Capitalism — Shoshana Zuboff

- GNU Project Philosophy  
  https://www.gnu.org/philosophy/

- W3C Open Standards Principles  
  https://www.w3.org/standards/

---

**Your contacts are not a product.  
They are relationships.  
Own them. Protect them.**
