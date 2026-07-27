"""
supabase_client.py
-------------------
Central place for creating Supabase clients.

Two flavors are used across the app:

1. `get_anon_client()` — a plain client using the anon key. Used for the
   login screen itself (before we have a user session), and as a safe
   fallback anywhere a user-scoped client can't be built.

2. `get_session_client()` — a client for the *currently logged-in* user,
   built by taking the anon client and attaching the access/refresh
   tokens Supabase Auth issued at login (stored in the Flask session).
   This lets PostgREST evaluate `auth.uid()` / Row Level Security as
   that specific user, rather than as an anonymous caller.

Role checks (Admin / Ops / Client) are enforced in the Flask layer via
`decorators.py` in Phase 2. RLS policies added in schema_phase2.sql
cover the `profiles` table; extending RLS to guards/clients/complaints
etc. is recommended before any *direct* browser-to-Supabase calls are
introduced (flagged as Phase 3 hardening in the schema file).
"""

from flask import session
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY

# A single shared anon-key client is safe to reuse — it holds no
# per-user state until we explicitly attach a session to it.
_anon_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_anon_client() -> Client:
    """Client using only the anon key — no logged-in user context."""
    return _anon_client


def get_session_client() -> Client:
    """
    Client scoped to the currently logged-in user (if any).

    Falls back to the anon client if there's no session, or if attaching
    the stored tokens fails for any reason (e.g. expired refresh token) —
    callers should treat data as "anonymous view" in that case, which
    the Flask-layer role decorators already guard against being reached
    without a valid login.
    """
    tokens = session.get("supabase_tokens")
    if not tokens:
        return _anon_client

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    try:
        client.auth.set_session(tokens["access_token"], tokens["refresh_token"])
    except Exception:
        # supabase-py version differences / expired token — degrade gracefully.
        return _anon_client
    return client
