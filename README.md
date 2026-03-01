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

```bash
git clone https://github.com/jameswintermute/vcard.git
cd vcard
pip install -e .
python start-webui.py
```

Then open your browser to:

    http://localhost:8421

---

## ⚙ Features

- **vCard 3.0 & 4.0** parsing and standards-compliant 4.0 export
- **Proprietary field stripping** — removes `X-AB*`, `X-GOOGLE*`, photos, and vendor clutter
- **Cross-source duplicate detection** via email, phone, and fuzzy name matching
- **Phone number normalisation** to E.164 international format, inferred from address or home country setting
- **Category tagging** — rule-based auto-tagging via `local/vcard.conf`, with interactive review
- **KIND classification** — individual, organisation, self
- **Self / profile card** — tag your own card as KIND=self; skipped in duplicate checks and quality reports
- **RELATED linking** — link spouses, partners, siblings, parents, children with bidirectional vCard 4.0 RELATED properties
- **MEMBER linking** — assign individuals as members of an organisation card (vCard 4.0 MEMBER)
- **UID, REV, PRODID** — every card carries a stable unique identifier, a last-modified timestamp (UTC ISO 8601), and a PRODID identifying this tool
- **Address normalisation** — single-line address detection and structured field parsing
- **Quality review** — scan contacts for missing emails, phones, addresses, categories
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
