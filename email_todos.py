#!/usr/bin/env python3
"""
email_todos.py
Scans a folder of Obsidian .md email files (converted from Gmail mbox),
uses the Claude API to identify actionable todos, and outputs a single
Email-Todos.md file grouped by month (newest first), then by sender
within each month, with links back to source emails.

Usage:
    python3 ~/Desktop/email_todos.py

Requirements:
    pip3 install anthropic python-dotenv
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try:
    import anthropic
except ImportError:
    print("❌ Missing dependency. Run: pip3 install anthropic python-dotenv")
    sys.exit(1)

# Import all config from config.py
try:
    from config import ANTHROPIC_API_KEY, GMAIL_FOLDER, OUTPUT_FILE, MODEL, VAULT_ROOT
except ImportError:
    print("❌ config.py not found. Make sure it's in the same folder as this script.")
    sys.exit(1)
except ValueError as e:
    print(e)
    sys.exit(1)


# ─── Constants ────────────────────────────────────────────────────────────────

MAX_TOKENS = 500
API_DELAY = 0.3
MAX_CONTENT_CHARS = 3000


# ─── Helpers ──────────────────────────────────────────────────────────────────

def parse_frontmatter(content):
    """Extract YAML frontmatter and body from .md file."""
    frontmatter = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            raw_fm = parts[1].strip()
            body = parts[2].strip()
            for line in raw_fm.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    frontmatter[key.strip()] = value.strip().strip('"')

    return frontmatter, body


def get_vault_relative_path(filepath):
    """
    Convert absolute filepath to a path relative to VAULT_ROOT.
    All link paths are driven by VAULT_ROOT in config.py.

    e.g. if VAULT_ROOT = ~/vault/ToDo
    ~/vault/ToDo/Gmail/Work/04-30-2026 - Budget.md
      -> Gmail/Work/04-30-2026 - Budget
    """
    vault_root = os.path.expanduser(VAULT_ROOT)
    rel = os.path.relpath(filepath, vault_root)
    return rel[:-3] if rel.endswith(".md") else rel


def truncate_content(body, max_chars=MAX_CONTENT_CHARS):
    """Truncate email body to keep API costs reasonable."""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "\n\n... [truncated for analysis]"


def parse_date_last(frontmatter):
    """Parse date_last from frontmatter. Falls back to epoch."""
    date_str = frontmatter.get("date_last", "")
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except Exception:
        return datetime(1970, 1, 1)


def month_key(dt):
    return (dt.year, dt.month)


def month_label(dt):
    return dt.strftime("%B %Y")


def analyze_email(client, frontmatter, body):
    """Send email to Claude API. Returns list of {task, reason} dicts."""
    subject = frontmatter.get("subject", "No Subject")
    sender = frontmatter.get("from", "Unknown")
    date = frontmatter.get("date_last", "")

    prompt = f"""You are analyzing an email thread to identify actionable todos for the recipient.

Email metadata:
- Subject: {subject}
- From: {sender}
- Date: {date}

Email content:
{truncate_content(body)}

Identify any clear action items that the email recipient needs to take. Be selective — only flag genuine todos, not informational emails.

Respond ONLY with valid JSON in exactly this format, no other text:
{{
  "has_todo": true or false,
  "todos": [
    {{
      "task": "short, clear action item (max 10 words)",
      "reason": "one sentence explaining why this is actionable"
    }}
  ]
}}

If no todos, return: {{"has_todo": false, "todos": []}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        data = json.loads(raw)

        if data.get("has_todo") and data.get("todos"):
            return data["todos"]
        return []

    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"    ⚠️  API error: {e}")
        return []


def format_sender(sender_str):
    return sender_str.strip() or "Unknown Sender"


def build_output(todos_by_month_sender, generated_at):
    """Build Email-Todos.md: month (newest first) → sender (alpha) → todos."""
    total = sum(
        len(items)
        for senders in todos_by_month_sender.values()
        for items in senders.values()
    )

    lines = [
        "# Email Todos",
        "",
        f"*Generated: {generated_at}*  ",
        f"*Source: `{GMAIL_FOLDER}`*  ",
        f"*Total todos: {total}*",
        "",
        "---",
        "",
    ]

    if not todos_by_month_sender:
        lines.append("*No actionable todos found in your emails.*")
        return "\n".join(lines)

    for month_k in sorted(todos_by_month_sender.keys(), reverse=True):
        senders_dict = todos_by_month_sender[month_k]
        dt = datetime(month_k[0], month_k[1], 1)

        lines.append(f"## {month_label(dt)}")
        lines.append("")

        for sender in sorted(senders_dict.keys()):
            lines.append(f"### {sender}")
            lines.append("")
            for item in senders_dict[sender]:
                lines.append(f"- [ ] {item['task']} [[{item['link']}|↗]]")
                lines.append(f"  > {item['reason']}")
                lines.append("")
            lines.append("")

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    gmail_folder = os.path.expanduser(GMAIL_FOLDER)
    output_file = os.path.expanduser(OUTPUT_FILE)

    md_files = [
        f for f in sorted(Path(gmail_folder).glob("*.md"))
        if f.name != "Email-Todos.md"
    ]

    if not md_files:
        print(f"❌ No .md files found in {gmail_folder}")
        sys.exit(1)

    print(f"📂 Scanning: {gmail_folder}")
    print(f"📧 Found {len(md_files)} email files")
    print(f"🤖 Analyzing with Claude ({MODEL})")
    print(f"🔗 Links relative to: {VAULT_ROOT}")
    print("")

    todos_by_month_sender = defaultdict(lambda: defaultdict(list))
    found_count = 0
    skipped_count = 0

    for i, filepath in enumerate(md_files, 1):
        filename = filepath.name
        print(f"  [{i:3d}/{len(md_files)}] {filename[:60]}", end="", flush=True)

        content = filepath.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)

        if not body.strip():
            print(" — skipped (empty)")
            skipped_count += 1
            continue

        todos = analyze_email(client, frontmatter, body)

        if todos:
            sender = format_sender(frontmatter.get("from", "Unknown"))
            link = get_vault_relative_path(str(filepath))
            date = parse_date_last(frontmatter)
            mk = month_key(date)

            for todo in todos:
                todo["link"] = link
                todo["filename"] = filename
                todos_by_month_sender[mk][sender].append(todo)

            print(f" — ✅ {len(todos)} todo(s)")
            found_count += len(todos)
        else:
            print(" — no todos")
            skipped_count += 1

        time.sleep(API_DELAY)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    output_content = build_output(todos_by_month_sender, generated_at)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_content)

    print("")
    print("─" * 50)
    print(f"✅ Todos found:   {found_count}")
    print(f"⏭️  No todos:      {skipped_count}")
    print(f"📅 Months:        {len(todos_by_month_sender)}")
    print(f"📄 Output:        {output_file}")
    print("")
    print("Done! Open Email-Todos.md in Obsidian.")


if __name__ == "__main__":
    main()
