# Gmail → Obsidian Pipeline

A two-script pipeline for importing Gmail emails into an Obsidian vault as plain Markdown files, then using the Claude AI API to automatically extract actionable todos from your emails — grouped by month and sender, with links back to the source email notes.

---

## Overview

```
Gmail (labeled emails)
        ↓  Google Takeout export
    .mbox file
        ↓  mbox_to_md.py
    Obsidian .md files  (one per thread, full content, attachments saved)
        ↓  email_todos.py + config.py + api.env
    Email-Todos.md  (AI-generated todo list, grouped by month then sender)
```

Everything is stored as plain Markdown files in your Obsidian vault. No cloud dependencies, no proprietary formats, no vendor lock-in.

---

## Requirements

- macOS or Linux
- Python 3.8+
- An [Anthropic API key](https://console.anthropic.com) (for `email_todos.py` only)
- [Obsidian](https://obsidian.md) with the [Tasks plugin](https://publish.obsidian.md/tasks)

Install dependencies:

```bash
pip3 install anthropic python-dotenv
```

---

## Files

| File | Purpose | Goes to GitHub? |
|------|---------|----------------|
| `mbox_to_md.py` | Converts mbox to Obsidian .md files | ✅ Yes |
| `email_todos.py` | AI todo extractor | ✅ Yes |
| `config.py` | All settings — paths, model, vault root | ✅ Yes |
| `api.env.example` | API key template (blank key) | ✅ Yes |
| `api.env` | Your actual Anthropic API key | ❌ No — excluded by `.gitignore` |
| `.gitignore` | Excludes `api.env` from GitHub | ✅ Yes |

All files live on your Desktop.

---

## First-Time Setup

### 1. Create your `api.env` file

Copy the template and add your key:

```bash
cp api.env.example api.env
```

Open `api.env` and paste your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
```

Get your API key at [console.anthropic.com](https://console.anthropic.com).

### 2. Edit `config.py`

Open `config.py` and set your vault paths:

```python
# Root folder that contains your Gmail folder and output file
# Links in Email-Todos.md are calculated relative to this path
VAULT_ROOT = "~/vault/ToDo"

# Folder containing your converted email .md files
GMAIL_FOLDER = "~/vault/ToDo/Gmail/Work"

# Output file for the generated todo list
OUTPUT_FILE = "~/vault/ToDo/Email-Todos.md"

# Claude model to use
MODEL = "claude-sonnet-4-6"
```

**Important:** `VAULT_ROOT` must be the folder that contains both your Gmail folder and your output file. All wikilinks in `Email-Todos.md` are calculated relative to this path so Obsidian resolves them correctly.

The script never hardcodes any paths — everything is driven by `config.py`.

---

## Step 1 — Export Gmail Label as MBOX

1. Go to [Google Takeout](https://takeout.google.com)
2. Click **Deselect All**
3. Scroll to **Mail** and check it
4. Click **All Mail data included**
5. Uncheck **All Mail**, then check only the specific label(s) you want
6. Click **Next Step** → **Create Export**
7. Download the `.zip` when ready and unzip it
8. Find the `.mbox` file inside the `Mail/` folder
9. Move the `.mbox` file to your Desktop

---

## Step 2 — Convert MBOX to Obsidian Markdown

### Script: `mbox_to_md.py`

Converts a Gmail `.mbox` export into individual Obsidian `.md` files — one per email thread.

**Usage:**

```bash
python3 ~/Desktop/mbox_to_md.py ~/Desktop/YourLabel.mbox ~/vault/ToDo/Gmail/YourLabel
```

Output folder is created automatically if it doesn't exist.

### What it produces

```
~/vault/ToDo/Gmail/Work/
    04-30-2026 - Budget Approval.md
    04-28-2026 - Project Kickoff.md
    /attachments/
        budget-draft.pdf
        timeline.xlsx
```

### Sample output file

```markdown
---
subject: "Budget Approval"
from: Sarah Chen <sarah@company.com>
date_first: 2026-04-28
date_last: 2026-04-30
participants:
  - Sarah Chen <sarah@company.com>
  - John Smith <john@company.com>
labels:
  - Work
  - Important
message_count: 3
---

# Budget Approval

---

### Sarah Chen <sarah@company.com>
**Date:** 2026-04-30 09:00
**To:** John Smith <john@company.com>

Can you approve the Q2 budget by Friday?

> ### John Smith — 2026-04-29
> Sure, send me the breakdown first.

## Attachments

- [[attachments/budget-draft.pdf]]
```

### Features

- One `.md` file per thread — replies grouped chronologically
- Quoted text collapsed to Markdown blockquotes
- `Re:` / `Fwd:` prefixes stripped from filenames
- Gmail labels captured in YAML frontmatter
- Attachments saved to `/attachments/` subfolder and linked inline
- Filename dated by **last** email in thread: `MM-DD-YYYY - Subject.md`
- ISO dates (`YYYY-MM-DD`) used inside frontmatter and note body
- Safely skips existing files if run twice
- No external dependencies — uses Python standard library only

---

## Step 3 — Generate AI Todo List from Emails

### Script: `email_todos.py`

Scans all `.md` email files in your Gmail folder, sends each to the Claude API, and produces a single `Email-Todos.md` file with actionable todos grouped by month (newest first), then alphabetically by sender within each month.

**Usage:**

```bash
python3 ~/Desktop/email_todos.py
```

No API key in the command — loaded automatically from `api.env`.

The terminal confirms settings before processing:

```
📂 Scanning: ~/vault/ToDo/Gmail/Work
📧 Found 136 email files
🤖 Analyzing with Claude (claude-sonnet-4-6)
🔗 Links relative to: ~/vault/ToDo
```

### Output: `~/vault/ToDo/Email-Todos.md`

```markdown
# Email Todos

*Generated: 2026-04-30 17:00*
*Source: `~/vault/ToDo/Gmail/Work/`*
*Total todos: 202*

---

## April 2026

### Mike Torres <mike@company.com>

- [ ] Review pull request #412 [[Gmail/Work/04-29-2026 - Code Review|↗]]
  > Mike flagged a blocking issue and needs your approval to merge

### Sarah Chen <sarah@company.com>

- [ ] Approve Q2 budget by Friday [[Gmail/Work/04-30-2026 - Budget Approval|↗]]
  > Sarah is waiting on your sign-off before she can proceed with procurement

## March 2026

### Sarah Chen <sarah@company.com>

- [ ] Reply with vendor shortlist [[Gmail/Work/03-15-2026 - Vendor Selection|↗]]
  > Sarah asked for your top 3 vendors by end of week, no response yet
```

### Features

- Claude AI judges email content — only genuine action items are extracted
- Grouped by month, newest first
- Senders sorted alphabetically within each month
- Each todo links directly back to the source `.md` file in Obsidian
- One-line AI reason explains why each item is actionable
- Overwrites `Email-Todos.md` fresh on each run
- Progress shown per file as it runs
- Rate limiting built in to avoid API errors
- Compatible with the Obsidian Tasks plugin

### API costs

Scanning 136 emails costs approximately **$0.05–0.15** depending on email length. The script truncates emails to 3,000 characters before sending to keep costs predictable.

---

## Vault Structure

```
~/vault/
    /ToDo/
        Email-Todos.md          ← AI-generated, regenerated each run
        /Gmail/
            /Work/
                04-30-2026 - Budget Approval.md
                04-28-2026 - Project Kickoff.md
                /attachments/
                    budget-draft.pdf
            /Finance/
                ...
    /Projects/
    /Daily/
    /Archive/
        /Evernote/
        /GoogleKeep/
```

---

## Recommended Obsidian Setup

- **Tasks plugin** — for querying and managing todos across your vault
- **Obsidian Sync** — for syncing vault across Mac and iOS/Android
- **Dataview plugin** — for advanced queries across email frontmatter

---

## Privacy

- `mbox_to_md.py` — runs entirely locally, no network calls
- `email_todos.py` — sends email content to Anthropic's API
  - API data is deleted within **7 days**
  - Never used for model training
  - See [Anthropic's privacy policy](https://privacy.anthropic.com)

For sensitive labels (legal, financial, medical), run `mbox_to_md.py` only and skip `email_todos.py`, or use a local model via [Ollama](https://ollama.com) by swapping the API call.

---

## Roadmap

- [ ] `email_todos.py` — support scanning multiple Gmail label subfolders
- [ ] `email_todos.py` — suggest due dates based on email urgency language
- [ ] `email_todos.py` — Ollama support for fully local/private processing
- [ ] `email_reply.py` — AI-drafted reply for each email, saved as `.md`

---

## License

MIT
