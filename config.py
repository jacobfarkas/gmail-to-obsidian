# config.py
# Edit the settings below to match your vault setup.
# Your API key lives in api.env — never edit it here.

from dotenv import load_dotenv
import os

# Load API key from api.env file
load_dotenv("api.env")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not ANTHROPIC_API_KEY:
    raise ValueError("❌ ANTHROPIC_API_KEY not found. Make sure api.env exists with your key.")

# ─── Settings — edit these ────────────────────────────────────────────────────

# Root folder that contains your Gmail folder and output file
# Links in Email-Todos.md are calculated relative to this path
VAULT_ROOT = "~/vault/ToDo"

# Folder containing your converted email .md files
GMAIL_FOLDER = "~/vault/ToDo/Gmail/Work"

# Output file for the generated todo list
OUTPUT_FILE = "~/vault/ToDo/Email-Todos.md"

# Claude model to use
MODEL = "claude-sonnet-4-6"
