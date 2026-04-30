#!/usr/bin/env python3
"""
mbox_to_md.py
Converts a Gmail .mbox export into Obsidian-friendly .md files.

Features:
- One .md file per thread (replies grouped chronologically)
- Quoted text collapsed to blockquotes
- Attachments saved to ./attachments/ and linked inline
- Filename: MM-DD-YYYY - Subject.md (dated by last email in thread)
- ISO dates inside frontmatter and note body
- Skips existing files (safe to re-run)
- Gmail labels in frontmatter

Usage:
    python3 mbox_to_md.py <input.mbox> <output_folder>

Example:
    python3 mbox_to_md.py ~/Downloads/Work.mbox ~/vault/Archive/Gmail/Work
"""

import mailbox
import os
import sys
import re
import hashlib
import quopri
import base64
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from collections import defaultdict


# ─── Config ───────────────────────────────────────────────────────────────────

ATTACHMENTS_FOLDER = "attachments"

# Strip these prefixes from subject lines
SUBJECT_STRIP = re.compile(r'^(Re:|RE:|Fwd:|FWD:|Fw:|FW:)\s*', re.IGNORECASE)

# Quoted line patterns (lines starting with >)
QUOTE_LINE = re.compile(r'^(>+)\s?(.*)')

# Common email signature delimiters
SIG_DELIMITERS = ['-- ', '—', '________________________________']


# ─── Helpers ──────────────────────────────────────────────────────────────────

def decode_str(value):
    """Decode encoded email header strings."""
    if value is None:
        return ""
    try:
        parts = decode_header(value)
        result = []
        for part, encoding in parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result).strip()
    except Exception:
        return str(value).strip()


def clean_subject(subject):
    """Strip Re:/Fwd: prefixes from subject."""
    subject = decode_str(subject)
    while SUBJECT_STRIP.match(subject):
        subject = SUBJECT_STRIP.sub('', subject).strip()
    return subject or "No Subject"


def safe_filename(text, max_length=80):
    """Convert text to a safe filename."""
    text = re.sub(r'[\\/*?:"<>|#%&{}$!\'@+`=]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    text = text.strip('.')
    return text[:max_length] if text else "No Subject"


def parse_date(msg):
    """Parse email date, return datetime object. Falls back to epoch."""
    date_str = msg.get("Date", "")
    try:
        dt = parsedate_to_datetime(date_str)
        # Normalize to UTC-aware datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def format_date_frontmatter(dt):
    """Format date for frontmatter: YYYY-MM-DD."""
    return dt.strftime("%Y-%m-%d")


def format_date_filename(dt):
    """Format date for filename: MM-DD-YYYY."""
    return dt.strftime("%m-%d-%Y")


def format_datetime_display(dt):
    """Format date for display in note body."""
    return dt.strftime("%Y-%m-%d %H:%M")


def get_thread_id(msg):
    """
    Get a stable thread identifier.
    Uses Gmail X-GM-THRID if available (most reliable),
    otherwise chains via References/In-Reply-To, then Message-ID.
    """
    thrid = msg.get("X-GM-THRID", "").strip()
    if thrid:
        return thrid

    references = msg.get("References", "").strip()
    if references:
        return references.split()[0]

    in_reply_to = msg.get("In-Reply-To", "").strip()
    if in_reply_to:
        return in_reply_to

    return msg.get("Message-ID", "").strip() or hashlib.md5(
        str(parse_date(msg).timestamp()).encode()
    ).hexdigest()


def get_labels(msg):
    """Extract Gmail labels from X-Gmail-Labels header."""
    labels_raw = msg.get("X-Gmail-Labels", "")
    if not labels_raw:
        return []
    labels = [l.strip().strip('"') for l in labels_raw.split(",")]
    # Filter out noise labels
    skip = {"Opened", "Personal", "category_personal", "category_updates",
            "category_promotions", "category_social", "category_forums"}
    return [l for l in labels if l and l not in skip]


def decode_payload(part):
    """Decode email part payload to string."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        try:
            return payload.decode("utf-8", errors="replace")
        except Exception:
            return payload.decode("latin-1", errors="replace")


def extract_text_body(msg):
    """
    Extract plain text body from email message.
    Prefers text/plain, falls back to stripping text/html.
    """
    plain = None
    html = None

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            if ct == "text/plain" and plain is None:
                plain = decode_payload(part)
            elif ct == "text/html" and html is None:
                html = decode_payload(part)
    else:
        ct = msg.get_content_type()
        if ct == "text/plain":
            plain = decode_payload(msg)
        elif ct == "text/html":
            html = decode_payload(msg)

    if plain:
        return plain
    if html:
        return strip_html(html)
    return ""


def strip_html(html):
    """Very basic HTML to plain text."""
    # Replace block elements with newlines
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<p[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<div[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</div>', '\n', html, flags=re.IGNORECASE)
    # Remove all other tags
    html = re.sub(r'<[^>]+>', '', html)
    # Decode common HTML entities
    html = html.replace('&nbsp;', ' ').replace('&amp;', '&')
    html = html.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    # Clean up excessive whitespace
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


def format_body_as_markdown(body):
    """
    Convert email body to Markdown.
    - Lines starting with > become blockquotes
    - Consecutive quoted lines are grouped
    - Signature delimiters collapse the sig
    """
    lines = body.splitlines()
    output = []
    in_quote = False
    in_sig = False

    for line in lines:
        # Stop at signature delimiter
        if any(line.strip().startswith(sig) for sig in SIG_DELIMITERS):
            in_sig = True
            output.append("\n---\n*— signature omitted —*")
            break

        quote_match = QUOTE_LINE.match(line)
        if quote_match:
            # It's a quoted line
            quote_content = quote_match.group(2)
            if not in_quote:
                output.append("")  # blank line before blockquote block
                in_quote = True
            output.append(f"> {quote_content}")
        else:
            if in_quote:
                output.append("")  # blank line after blockquote block
                in_quote = False
            output.append(line)

    return "\n".join(output).strip()


def get_attachments(msg):
    """
    Extract attachments from email.
    Returns list of (filename, bytes) tuples.
    """
    attachments = []
    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        cd = str(part.get("Content-Disposition", ""))
        if "attachment" not in cd:
            continue
        filename = part.get_filename()
        if not filename:
            continue
        filename = decode_str(filename)
        payload = part.get_payload(decode=True)
        if payload:
            attachments.append((filename, payload))

    return attachments


def save_attachment(filename, data, attachments_dir):
    """
    Save attachment to disk. Handles duplicate filenames by appending a hash.
    Returns the final saved filename.
    """
    os.makedirs(attachments_dir, exist_ok=True)
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", filename)
    out_path = os.path.join(attachments_dir, safe_name)

    # If file already exists with same content, reuse it
    if os.path.exists(out_path):
        with open(out_path, 'rb') as f:
            existing = f.read()
        if existing == data:
            return safe_name
        # Different file, append hash to avoid collision
        name, ext = os.path.splitext(safe_name)
        short_hash = hashlib.md5(data).hexdigest()[:6]
        safe_name = f"{name}_{short_hash}{ext}"
        out_path = os.path.join(attachments_dir, safe_name)

    with open(out_path, 'wb') as f:
        f.write(data)

    return safe_name


# ─── Core Conversion ──────────────────────────────────────────────────────────

def build_thread_md(thread_msgs, output_dir):
    """
    Convert a list of email messages (one thread) into a single .md file.
    Returns (filepath, was_skipped) tuple.
    """
    # Sort chronologically
    thread_msgs.sort(key=lambda m: parse_date(m))

    last_msg = thread_msgs[-1]
    first_msg = thread_msgs[0]

    # Filename based on last email date + cleaned subject
    last_date = parse_date(last_msg)
    subject = clean_subject(first_msg.get("Subject", "No Subject"))
    date_str_filename = format_date_filename(last_date)
    safe_subj = safe_filename(subject)
    filename = f"{date_str_filename} - {safe_subj}.md"
    filepath = os.path.join(output_dir, filename)

    # Skip if already exists
    if os.path.exists(filepath):
        return filepath, True

    # Collect all participants
    participants = set()
    all_labels = set()
    for msg in thread_msgs:
        sender = decode_str(msg.get("From", ""))
        if sender:
            participants.add(sender)
        to = decode_str(msg.get("To", ""))
        if to:
            for p in to.split(","):
                participants.add(p.strip())
        all_labels.update(get_labels(msg))

    # Build frontmatter
    first_date_str = format_date_frontmatter(parse_date(first_msg))
    last_date_str = format_date_frontmatter(last_date)
    from_str = decode_str(first_msg.get("From", ""))
    labels_list = sorted(all_labels)
    participants_list = sorted(participants)

    frontmatter_lines = [
        "---",
        f'subject: "{subject}"',
        f"from: {from_str}",
        f"date_first: {first_date_str}",
        f"date_last: {last_date_str}",
        f"participants:",
    ]
    for p in participants_list:
        frontmatter_lines.append(f"  - {p}")
    if labels_list:
        frontmatter_lines.append("labels:")
        for l in labels_list:
            frontmatter_lines.append(f"  - {l}")
    frontmatter_lines.append(f"message_count: {len(thread_msgs)}")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    # Build note body
    body_lines = [f"# {subject}", ""]

    # Attachments dir
    attachments_dir = os.path.join(output_dir, ATTACHMENTS_FOLDER)
    all_attachments = []

    # Build each message block
    for i, msg in enumerate(thread_msgs):
        msg_date = parse_date(msg)
        msg_from = decode_str(msg.get("From", "Unknown"))
        msg_to = decode_str(msg.get("To", ""))
        date_display = format_datetime_display(msg_date)

        body_lines.append(f"---")
        body_lines.append(f"")
        body_lines.append(f"### {msg_from}")
        body_lines.append(f"**Date:** {date_display}  ")
        if msg_to:
            body_lines.append(f"**To:** {msg_to}  ")
        body_lines.append("")

        # Email body
        raw_body = extract_text_body(msg)
        md_body = format_body_as_markdown(raw_body)
        if md_body:
            body_lines.append(md_body)
        else:
            body_lines.append("*(no body)*")
        body_lines.append("")

        # Attachments for this message
        msg_attachments = get_attachments(msg)
        for att_name, att_data in msg_attachments:
            saved_name = save_attachment(att_name, att_data, attachments_dir)
            all_attachments.append(saved_name)

    # Attachments section at bottom
    if all_attachments:
        body_lines.append("---")
        body_lines.append("")
        body_lines.append("## Attachments")
        body_lines.append("")
        for att in all_attachments:
            body_lines.append(f"- [[{ATTACHMENTS_FOLDER}/{att}]]")
        body_lines.append("")

    # Combine
    full_content = frontmatter + "\n\n" + "\n".join(body_lines)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)

    return filepath, False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 mbox_to_md.py <input.mbox> <output_folder>")
        print("Example: python3 mbox_to_md.py ~/Downloads/Work.mbox ~/vault/Archive/Gmail/Work")
        sys.exit(1)

    mbox_path = os.path.expanduser(sys.argv[1])
    output_dir = os.path.expanduser(sys.argv[2])

    if not os.path.exists(mbox_path):
        print(f"❌ Error: mbox file not found: {mbox_path}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"📬 Reading: {mbox_path}")
    print(f"📁 Output:  {output_dir}")
    print("")

    # Read mbox
    mbox = mailbox.mbox(mbox_path)

    # Group messages by thread
    threads = defaultdict(list)
    total_msgs = 0

    print("🔍 Grouping messages into threads...")
    for msg in mbox:
        thread_id = get_thread_id(msg)
        threads[thread_id].append(msg)
        total_msgs += 1

    print(f"   Found {total_msgs} messages in {len(threads)} threads")
    print("")

    # Convert each thread
    converted = 0
    skipped = 0
    errors = 0

    for i, (thread_id, msgs) in enumerate(threads.items(), 1):
        try:
            filepath, was_skipped = build_thread_md(msgs, output_dir)
            filename = os.path.basename(filepath)
            if was_skipped:
                print(f"  ⏭️  Skipped (exists): {filename}")
                skipped += 1
            else:
                print(f"  ✅ {filename}")
                converted += 1
        except Exception as e:
            print(f"  ❌ Error on thread {thread_id[:20]}...: {e}")
            errors += 1

    print("")
    print("─" * 50)
    print(f"✅ Converted:  {converted} threads")
    print(f"⏭️  Skipped:    {skipped} (already existed)")
    print(f"❌ Errors:     {errors}")
    print(f"📁 Output:     {output_dir}")
    if os.path.exists(os.path.join(output_dir, ATTACHMENTS_FOLDER)):
        att_count = len(os.listdir(os.path.join(output_dir, ATTACHMENTS_FOLDER)))
        print(f"📎 Attachments: {att_count} files saved")
    print("")
    print("Done! Open your vault in Obsidian to see the imported emails.")


if __name__ == "__main__":
    main()
