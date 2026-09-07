#!/usr/bin/env python3
"""
Fetch subscription plan usage for Claude and OpenAI Codex.

Claude: uses OAuth token from ~/.claude/.credentials.json
OpenAI Codex: uses OAuth token from ~/.codex/auth.json
              or CODEX_ACCESS_TOKEN env var / .env file
              endpoint: https://chatgpt.com/backend-api/wham/usage
"""

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_ENDPOINT   = "https://api.anthropic.com/api/oauth/usage"
TOKEN_ENDPOINT   = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID        = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def load_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"No credentials found at {CREDENTIALS_PATH}. "
            "Run `claude` to authenticate first."
        )
    with open(CREDENTIALS_PATH) as f:
        data = json.load(f)
    return data["claudeAiOauth"]


def save_credentials(creds: dict) -> None:
    """Merge `creds` into the stored claudeAiOauth block, writing atomically.

    Claude Code reads the same file, so a partial write would log the user out.
    """
    with open(CREDENTIALS_PATH) as f:
        data = json.load(f)
    data["claudeAiOauth"].update(creds)

    fd, tmp_path = tempfile.mkstemp(dir=CREDENTIALS_PATH.parent, prefix=".credentials.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, CREDENTIALS_PATH)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _refresh_token(refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_ENDPOINT,
        json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Token refresh failed ({resp.status_code}). Run `claude` and re-authenticate."
        )
    return resp.json()


def _refresh_and_store(creds: dict) -> str:
    """Refresh the access token and persist the whole rotated credential set."""
    new = _refresh_token(creds["refreshToken"])
    updated = {
        "accessToken": new["access_token"],
        # The refresh token rotates; keeping a stale one locks us (and Claude
        # Code) out on the next refresh.
        "refreshToken": new.get("refresh_token", creds["refreshToken"]),
    }
    if new.get("expires_in"):
        updated["expiresAt"] = int(time.time() * 1000) + int(new["expires_in"]) * 1000
    save_credentials(updated)
    return updated["accessToken"]


def _fetch_claude_usage(access_token: str) -> dict:
    resp = requests.get(
        USAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
        timeout=10,
    )
    if resp.status_code == 429:
        raise RuntimeError("Rate limited by usage endpoint. Try again in a few minutes.")
    resp.raise_for_status()
    return resp.json()


# Refresh this far ahead of the stored expiry rather than waiting for a 401.
REFRESH_LEEWAY_MS = 5 * 60 * 1000


def get_claude_usage() -> dict:
    creds = load_credentials()

    expires_at = creds.get("expiresAt")
    if expires_at and time.time() * 1000 >= expires_at - REFRESH_LEEWAY_MS:
        return _fetch_claude_usage(_refresh_and_store(creds))

    try:
        return _fetch_claude_usage(creds["accessToken"])
    except requests.HTTPError as e:
        if e.response.status_code not in (401, 403):
            raise
        return _fetch_claude_usage(_refresh_and_store(creds))


# ---------------------------------------------------------------------------
# OpenAI Codex — OAuth API (token from ~/.codex/auth.json)
# ---------------------------------------------------------------------------

CODEX_AUTH_PATH  = Path.home() / ".codex" / "auth.json"
CODEX_USAGE_URL  = "https://chatgpt.com/backend-api/wham/usage"


@dataclass
class RateWindow:
    used_percent: float
    resets_at: Optional[datetime] = None


@dataclass
class OpenAIUsage:
    primary_limit: Optional[RateWindow] = None    # 5-hour
    secondary_limit: Optional[RateWindow] = None  # weekly
    credits_remaining: Optional[float] = None
    account_plan: Optional[str] = None


def _load_codex_token() -> tuple[str, str]:
    """Return (access_token, account_id). .env / env var takes priority."""
    env_token = os.environ.get("CODEX_ACCESS_TOKEN", "").strip()
    if env_token:
        account_id = os.environ.get("CODEX_ACCOUNT_ID", "").strip()
        return env_token, account_id

    if not CODEX_AUTH_PATH.exists():
        raise FileNotFoundError(
            f"No Codex credentials found at {CODEX_AUTH_PATH}. "
            "Run `codex` to authenticate first, or set CODEX_ACCESS_TOKEN in .env."
        )
    with open(CODEX_AUTH_PATH) as f:
        auth = json.load(f)
    tokens = auth["tokens"]
    return tokens["access_token"], tokens.get("account_id", "")


def get_openai_usage() -> OpenAIUsage:
    """Fetch OpenAI Codex plan usage via the OAuth API."""
    access_token, account_id = _load_codex_token()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "token-usage-dash",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    resp = requests.get(CODEX_USAGE_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    usage = OpenAIUsage()
    usage.account_plan = data.get("plan_type")

    credits = data.get("credits", {})
    if credits.get("balance") is not None:
        usage.credits_remaining = float(credits["balance"])

    rate_limit = data.get("rate_limit", {})

    def _window(w: Optional[dict]) -> Optional[RateWindow]:
        if not w:
            return None
        used_pct = float(w.get("used_percent", 0))
        reset_ts = w.get("reset_at")
        resets_at = datetime.fromtimestamp(reset_ts, tz=timezone.utc) if reset_ts else None
        return RateWindow(used_percent=used_pct, resets_at=resets_at)

    usage.primary_limit   = _window(rate_limit.get("primary_window"))
    usage.secondary_limit = _window(rate_limit.get("secondary_window"))

    return usage


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_time_until(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    delta = dt - datetime.now(timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "now"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m" if h > 0 else f"{m}m"


def format_time_until_iso(iso_str: str) -> str:
    return format_time_until(datetime.fromisoformat(iso_str))


def _bar(used_pct: float, width: int = 20) -> str:
    filled = int(used_pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_claude_usage(usage: dict) -> None:
    labels = {
        "five_hour":        "5-hour   ",
        "seven_day":        "7-day    ",
        "seven_day_sonnet": "7d Sonnet",
        "seven_day_opus":   "7d Opus  ",
    }
    print("Claude plan usage:")
    any_data = False
    for key, label in labels.items():
        window = usage.get(key)
        if not window:
            continue
        any_data = True
        util = window["utilization"]
        remaining = 100 - util
        resets = format_time_until_iso(window["resets_at"])
        print(f"  {label}  [{_bar(util)}] {util:5.1f}% used  {remaining:5.1f}% left  resets in {resets}")
    if not any_data:
        print("  No usage data returned.")


def print_openai_usage(usage: OpenAIUsage) -> None:
    print("OpenAI Codex plan usage:")
    if usage.account_plan:
        print(f"  Plan: {usage.account_plan}")
    if usage.credits_remaining is not None:
        print(f"  Credits remaining: {usage.credits_remaining:,.1f}")
    if usage.primary_limit:
        w = usage.primary_limit
        resets = format_time_until(w.resets_at)
        print(f"  5-hour   [{_bar(w.used_percent)}] {w.used_percent:5.1f}% used  {100-w.used_percent:5.1f}% left  resets in {resets}")
    if usage.secondary_limit:
        w = usage.secondary_limit
        resets = format_time_until(w.resets_at)
        print(f"  Weekly   [{_bar(w.used_percent)}] {w.used_percent:5.1f}% used  {100-w.used_percent:5.1f}% left  resets in {resets}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Show subscription plan usage")
    parser.add_argument("--claude-only", action="store_true")
    parser.add_argument("--openai-only", action="store_true")
    args = parser.parse_args()

    show_claude = not args.openai_only
    show_openai = not args.claude_only
    errors = []

    if show_claude:
        print()
        try:
            print_claude_usage(get_claude_usage())
        except Exception as e:
            errors.append(str(e))
            print(f"Claude: error — {e}")

    if show_openai:
        print()
        try:
            print_openai_usage(get_openai_usage())
        except Exception as e:
            errors.append(str(e))
            print(f"OpenAI: error — {e}")

    print()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
