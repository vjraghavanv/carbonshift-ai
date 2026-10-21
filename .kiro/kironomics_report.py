#!/usr/bin/env python3
"""Kironomics session reporter - reads Kiro's state.vscdb and sends to the backend."""
import os, sys, ssl, json, sqlite3, urllib.request, urllib.error, time
from pathlib import Path

API_KEY = "29d6d90e111fb3272709d87538d59135de60bd6be0247675a4524f62aac1e50e"
API_BASE = "https://2q4zt5zl9e.execute-api.us-east-1.amazonaws.com/dev"

def read_int(path, default=0):
    try:
        return int(Path(path).read_text().strip())
    except Exception:
        return default

tools = read_int("/tmp/kironomics_tools")
prompts = read_int("/tmp/kironomics_prompts")
start = read_int("/tmp/kironomics_start", int(time.time()))
elapsed = max(0, int(time.time()) - start)

# Read Kiro's state.vscdb (silent fail if missing or no usageState)
plan_data = {}
try:
    home = Path.home()
    if sys.platform == "darwin":
        db = home / "Library/Application Support/Kiro/User/globalStorage/state.vscdb"
    elif sys.platform.startswith("win"):
        db = Path(os.environ.get("APPDATA", str(home / "AppData/Roaming"))) / "Kiro/User/globalStorage/state.vscdb"
    else:
        db = home / ".config/Kiro/User/globalStorage/state.vscdb"
    if db.exists():
        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key=?",
            ("kiro.kiroAgent",),
        ).fetchone()
        conn.close()
        if row:
            state = json.loads(row[0])
            usage = state.get("kiro.resourceNotifications.usageState", {})
            breakdowns = usage.get("usageBreakdowns", [])
            if breakdowns:
                bd = breakdowns[0]
                plan_data = {
                    "currentUsage": bd.get("currentUsage"),
                    "usageLimit": bd.get("usageLimit"),
                    "percentageUsed": bd.get("percentageUsed"),
                    "resetDate": bd.get("resetDate"),
                }
except Exception:
    pass

payload = {
    "token": API_KEY,
    "tool_calls": tools,
    "prompts": prompts,
    "elapsed_seconds": elapsed,
    **plan_data,
}

# Build a verified TLS context. Prefer certifi's CA bundle (some Python builds —
# e.g. the python.org macOS build — ship without a usable default CA bundle, which
# makes urllib raise CERTIFICATE_VERIFY_FAILED), then fall back to the default.
def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return None

# POST to the hosted backend. Verified TLS by default; if this machine has no
# working CA bundle (cert verify fails), retry once unverified so the report
# still lands — the payload is only usage counts, sent over HTTPS.
try:
    req = urllib.request.Request(
        f"{API_BASE}/kironomics/session",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5, context=_ssl_context()).read()
    except (ssl.SSLError, urllib.error.URLError) as e:
        if "certificate verify failed" in str(e).lower():
            urllib.request.urlopen(req, timeout=5, context=ssl._create_unverified_context()).read()
        else:
            raise
except Exception:
    pass

# Cleanup temp counters
for f in ("/tmp/kironomics_tools", "/tmp/kironomics_prompts", "/tmp/kironomics_start"):
    try:
        os.remove(f)
    except Exception:
        pass
