"""
config.py
---------
Central configuration for the Pakwatan Security ERP Portal.
Reads Supabase credentials from environment variables (via a local .env file
in development, or real environment variables in production).

Never hardcode SUPABASE_URL / SUPABASE_KEY directly in source files.
"""

import os
from dotenv import load_dotenv

# Load variables from a .env file if present (development convenience).
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "pakwatan_secret_key_12345")
SESSION_LIFETIME_MINUTES = int(os.getenv("SESSION_LIFETIME_MINUTES", "60"))
# Fail fast with a clear message instead of a confusing crash deep inside supabase-py.
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL or SUPABASE_KEY.\n"
        "Create a '.env' file in the project root (see .env.example) or export\n"
        "these as environment variables before running the app."
    )

# Flask settings
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "True") == "True"
FLASK_HOST = os.environ.get("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))
