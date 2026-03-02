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

# Install all dependencies (recommended)
pip install -e ".[phonenumbers]"
# Ubuntu 23.04+ may require: pip install --break-system-packages -e ".[phonenumbers]"
# Or use a virtual environment (see Troubleshooting below)
# Alternatively — plain requirements file:
# pip install -r requirements.txt

# Launch
python3 start-webui.py
```

Then open: **http://localhost:8421**

---

### macOS

macOS ships with Python 2.7. You need Python 3.11+.

```bash
# Install Homebrew if not already present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12
brew install python@3.12

# Clone the project
git clone https://github.com/jameswintermute/vcard.git
cd vcard

# Install dependencies
pip3 install -e ".[phonenumbers]"

# Launch
python3 start-webui.py
```

Then open: **http://localhost:8421**

> **Apple Silicon:** All dependencies have native ARM wheels — no Rosetta needed.

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
- **Proprietary field stripping** — removes all `X-*` vendor fields, `PRODID`, and traces from Apple, Google, Proton, or vCard Studio itself. One-click from the Clean panel.
- **Cross-source duplicate detection** via email, phone, and fuzzy name matching
- **Phone number normalisation** to E.164 international format, with GOV.UK style display spacing (e.g. `+44 1932 269627`). Optional `phonenumbers` package for global number validation.
- **Typed email and phone fields** — tag each email or phone as HOME, WORK, MOBILE, or OTHER; label is exported as the vCard TYPE parameter and shown in the print view.
- **Category tagging** — rule-based auto-tagging via `local/vcard.conf`, with interactive review
- **KIND classification** — individual, organisation, self
- **Self / profile card** — tag your own card as KIND=self; skipped in duplicate checks and quality reports
- **RELATED linking** — link spouses, partners, siblings, parents, children with bidirectional vCard 4.0 RELATED properties
- **MEMBER linking** — assign individuals as members of an organisation card (vCard 4.0 MEMBER)
- **UID, REV, PRODID** — every card carries a stable unique identifier, a last-modified timestamp (UTC ISO 8601), and a PRODID identifying this tool
- **Address normalisation** — single-line address detection and structured field parsing
- **Quality review** — scan contacts for missing emails, phones, addresses, categories; mark any field as "not required" to permanently exclude it from future scans
- **Birthdays & Anniversaries tab** — month-by-month view of birthdays and anniversaries with age calculation; configurable category filter; printable birthday calendar
- **Raw vCard viewer** — inspect the full vCard source of any contact with syntax highlighting
- **Export options** — combined `.vcf`, per-category `.vcf`, individual file per contact (named `vcard-<ISO8601>-<LastName>-<FirstName>.vcf`), and `.csv`
- **Checkpoint autosave** — every edit is immediately persisted; resume exactly where you left off after a restart

---

## 📂 Project Layout

```
cards-in/           ← drop your exported .vcf source files here
cards-out/          ← clean output files written here
cards-wip/          ← autosave checkpoint (do not edit manually)
local/vcard.conf    ← your personal config (auto-created on first run)
src/vcard_normalizer/
  server.py         ← local HTTP server and all API endpoints
  static/index.html ← the entire Web UI (single-file, no build step)
  model.py          ← Card, Address, NameComponents, Related data classes
  normalize.py      ← field parsing and cleaning
  dedupe.py         ← similarity scoring and duplicate clustering
  formatters.py     ← phones, categories, KIND classification
  exporter.py       ← vCard 4.0 serialisation and individual file export
  checkpoint.py     ← autosave and resume
  config.py         ← TOML config and workspace initialisation
  proprietary.py    ← X-* field stripping rules
start-webui.py      ← launch script
```

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
