#!/usr/bin/env python3
"""
Fetch subscription plan usage for Claude, OpenAI Codex and OpenCode Go.

Claude: uses OAuth token from ~/.claude/.credentials.json
OpenAI Codex: uses OAuth token from ~/.codex/auth.json
              or CODEX_ACCESS_TOKEN env var / .env file
              endpoint: https://chatgpt.com/backend-api/wham/usage
OpenCode Go: uses the Zen API key from ~/.local/share/opencode/auth.json
             ("opencode-go" entry) or OPENCODE_GO_API_KEY env var / .env file
             endpoint: https://opencode.ai/zen/go/v1/usage
"""

import base64
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

# When credentials come from env vars (e.g. a container with no home-dir mount),
# refreshed tokens are cached here instead of being written back to the host.
# Override with CLAUDE_TOKEN_CACHE to point at a writable path.
TOKEN_CACHE_PATH = Path(
    os.environ.get("CLAUDE_TOKEN_CACHE", "")
    or (Path.home() / ".cache" / "token-usage-dash" / "claude_token.json")
)


def _claude_env_credentials() -> Optional[dict]:
    """Build a credential dict from env vars, or None when unset.

    CLAUDE_ACCESS_TOKEN is the minimum; CLAUDE_REFRESH_TOKEN additionally
    enables automatic renewal once the access token expires.
    """
    access_token = os.environ.get("CLAUDE_ACCESS_TOKEN", "").strip()
    if not access_token:
        return None
    creds = {"accessToken": access_token}
    refresh_token = os.environ.get("CLAUDE_REFRESH_TOKEN", "").strip()
    if refresh_token:
        creds["refreshToken"] = refresh_token
    expires_at = os.environ.get("CLAUDE_EXPIRES_AT", "").strip()
    if expires_at:
        try:
            creds["expiresAt"] = int(expires_at)
        except ValueError:
            pass
    return creds


def _load_token_cache() -> dict:
    """Read refreshed tokens cached from a previous run (env-var mode only)."""
    try:
        with open(TOKEN_CACHE_PATH) as f:
            cached = json.load(f)
        return cached if isinstance(cached, dict) else {}
    except (OSError, ValueError):
        return {}


def _store_token_cache(creds: dict) -> None:
    """Persist refreshed tokens so a long-running container reuses them."""
    try:
        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=TOKEN_CACHE_PATH.parent, prefix=".token.")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(creds, f)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, TOKEN_CACHE_PATH)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
    except OSError:
        # A cache we cannot write is not fatal: the env refresh token still
        # works, we just pay for a refresh on every run.
        pass


def load_credentials() -> dict:
    """Load Claude credentials from env vars, a token cache, or the CLI file.

    Env vars win so a container can run with no mounted credentials at all.
    """
    env_creds = _claude_env_credentials()
    if env_creds:
        # Prefer a cached refresh result over the (possibly stale) env token,
        # but only when the env supplied a refresh token to begin with.
        if env_creds.get("refreshToken"):
            cached = _load_token_cache()
            if cached.get("accessToken"):
                merged = dict(env_creds)
                merged.update(cached)
                return merged
        return env_creds

    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"No credentials found at {CREDENTIALS_PATH}. "
            "Run `claude` to authenticate first, or set CLAUDE_ACCESS_TOKEN "
            "(and optionally CLAUDE_REFRESH_TOKEN) in .env."
        )
    with open(CREDENTIALS_PATH) as f:
        data = json.load(f)
    return data["claudeAiOauth"]


def save_credentials(creds: dict) -> None:
    """Persist rotated credentials.

    In env-var mode there is no host file to update, so the refreshed tokens go
    to the local cache. Otherwise merge into the Claude Code credentials file
    atomically — Claude Code reads the same file, so a partial write would log
    the user out.
    """
    if _claude_env_credentials():
        cached = _load_token_cache()
        cached.update(creds)
        _store_token_cache(cached)
        return

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

# Public Codex CLI OAuth client, used for refresh_token grants.
CODEX_CLIENT_ID      = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"

# Refreshed Codex tokens are cached here when credentials come from env vars.
CODEX_TOKEN_CACHE_PATH = Path(
    os.environ.get("CODEX_TOKEN_CACHE", "")
    or (Path.home() / ".cache" / "token-usage-dash" / "codex_token.json")
)

# Refresh this far ahead of expiry rather than waiting for a 401.
CODEX_REFRESH_LEEWAY_S = 60 * 60  # 1 hour


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


def _jwt_expiry(token: str) -> Optional[datetime]:
    """Return the `exp` claim of a JWT, or None when it cannot be read."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        return datetime.fromtimestamp(int(exp), tz=timezone.utc) if exp else None
    except Exception:
        return None


def _codex_env_credentials() -> Optional[dict]:
    """Build Codex credentials from env vars, or None when unset."""
    token = os.environ.get("CODEX_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    creds = {"access_token": token}
    account_id = os.environ.get("CODEX_ACCOUNT_ID", "").strip()
    if account_id:
        creds["account_id"] = account_id
    refresh_token = os.environ.get("CODEX_REFRESH_TOKEN", "").strip()
    if refresh_token:
        creds["refresh_token"] = refresh_token
    return creds


def _load_codex_cache() -> dict:
    try:
        with open(CODEX_TOKEN_CACHE_PATH) as f:
            cached = json.load(f)
        return cached if isinstance(cached, dict) else {}
    except (OSError, ValueError):
        return {}


def _store_codex_cache(creds: dict) -> None:
    try:
        CODEX_TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=CODEX_TOKEN_CACHE_PATH.parent, prefix=".token.")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(creds, f)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, CODEX_TOKEN_CACHE_PATH)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
    except OSError:
        # An unwritable cache is not fatal; we just refresh again next run.
        pass


def _refresh_codex_token(refresh_token: str) -> dict:
    """Exchange a refresh token for a new access token.

    The response also rotates `refresh_token` and reports `earliest_refresh_at`,
    before which the server rejects further refreshes.
    """
    resp = requests.post(
        CODEX_TOKEN_ENDPOINT,
        json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CODEX_CLIENT_ID,
        },
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    if resp.status_code in (400, 401):
        raise RuntimeError(
            "Codex token refresh was rejected. Run `codex` to sign in again, "
            "then update CODEX_REFRESH_TOKEN (or delete the token cache)."
        )
    resp.raise_for_status()
    return resp.json()


def _refresh_codex_and_store(creds: dict) -> dict:
    new = _refresh_codex_token(creds["refresh_token"])
    updated = dict(creds)
    updated["access_token"] = new["access_token"]
    # The refresh token rotates; keeping the stale one breaks the next refresh.
    updated["refresh_token"] = new.get("refresh_token", creds["refresh_token"])
    if new.get("earliest_refresh_at"):
        updated["earliest_refresh_at"] = int(new["earliest_refresh_at"])
    elif new.get("expires_in"):
        updated["earliest_refresh_at"] = int(time.time()) + int(new["expires_in"])
    # `account_id` can arrive inside the new id_token; keep the existing one
    # unless the refresh explicitly returns a replacement.
    if new.get("account_id"):
        updated["account_id"] = new["account_id"]
    if creds.get("_env"):
        _store_codex_cache(updated)
    else:
        _save_codex_auth_file(updated)
    return updated


def _save_codex_auth_file(creds: dict) -> None:
    """Merge rotated tokens back into ~/.codex/auth.json atomically.

    The Codex CLI reads the same file, so a partial write would log it out.
    """
    with open(CODEX_AUTH_PATH) as f:
        auth = json.load(f)
    tokens = auth.setdefault("tokens", {})
    tokens["access_token"] = creds["access_token"]
    if creds.get("refresh_token"):
        tokens["refresh_token"] = creds["refresh_token"]
    if creds.get("account_id"):
        tokens["account_id"] = creds["account_id"]
    auth["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    fd, tmp_path = tempfile.mkstemp(dir=CODEX_AUTH_PATH.parent, prefix=".auth.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(auth, f, indent=2)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, CODEX_AUTH_PATH)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _load_codex_credentials() -> dict:
    """Load Codex credentials, preferring env vars, then the token cache."""
    env_creds = _codex_env_credentials()
    if env_creds:
        env_creds["_env"] = True
        if env_creds.get("refresh_token"):
            cached = _load_codex_cache()
            if cached.get("access_token"):
                merged = dict(env_creds)
                # Cached values win: they are newer than what the env supplied.
                merged.update(cached)
                merged["_env"] = True
                return merged
        return env_creds

    if not CODEX_AUTH_PATH.exists():
        raise FileNotFoundError(
            f"No Codex credentials found at {CODEX_AUTH_PATH}. "
            "Run `codex` to authenticate first, or set CODEX_ACCESS_TOKEN "
            "(with CODEX_REFRESH_TOKEN for auto-renewal) in .env."
        )
    with open(CODEX_AUTH_PATH) as f:
        auth = json.load(f)
    tokens = auth.get("tokens", {})
    creds = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "account_id": tokens.get("account_id", ""),
    }
    return creds


def _codex_token_is_stale(creds: dict) -> bool:
    """True when the access token is expired, unverifiable, or close to expiry."""
    # Never refresh before the server allows it, even if the JWT looks stale.
    earliest = creds.get("earliest_refresh_at")
    if earliest and time.time() < int(earliest):
        return False

    expiry = _jwt_expiry(creds.get("access_token", ""))
    if expiry is None:
        # Opaque or malformed token: we cannot tell when it expires. Since a
        # refresh token is available, refresh rather than send something we
        # cannot validate and fail later with a 401.
        return True
    return datetime.now(timezone.utc) >= expiry - timedelta(seconds=CODEX_REFRESH_LEEWAY_S)


def _load_codex_token() -> tuple[str, str]:
    """Return (access_token, account_id), refreshing when needed.

    `.env` / env var takes priority over the Codex CLI credentials file.
    """
    creds = _load_codex_credentials()

    if creds.get("refresh_token") and _codex_token_is_stale(creds):
        creds = _refresh_codex_and_store(creds)

    token = creds.get("access_token", "")
    if not token:
        raise RuntimeError(
            "No Codex access token available. Run `codex` to authenticate first."
        )
    return token, creds.get("account_id", "")


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

    # A token can be revoked server-side before its `exp`; refresh once and retry.
    if resp.status_code in (401, 403):
        creds = _load_codex_credentials()
        if creds.get("refresh_token"):
            creds = _refresh_codex_and_store(creds)
            headers["Authorization"] = f"Bearer {creds['access_token']}"
            if creds.get("account_id"):
                headers["ChatGPT-Account-Id"] = creds["account_id"]
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
# OpenCode Go — Zen API (key from ~/.local/share/opencode/auth.json)
# ---------------------------------------------------------------------------

OPENCODE_AUTH_PATH   = Path.home() / ".local" / "share" / "opencode" / "auth.json"
OPENCODE_GO_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"


@dataclass
class GoWindow:
    used_percent: float
    resets_at: Optional[datetime] = None


@dataclass
class OpenCodeGoUsage:
    rolling: Optional[GoWindow] = None  # 5-hour (20% of the monthly limit)
    weekly: Optional[GoWindow] = None   # weekly (50% of the monthly limit)
    monthly: Optional[GoWindow] = None  # monthly (100% of the monthly limit)


def _load_opencode_go_key() -> str:
    """Return the OpenCode Go API key. .env / env var takes priority."""
    env_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if env_key:
        return env_key

    if not OPENCODE_AUTH_PATH.exists():
        raise FileNotFoundError(
            f"No OpenCode credentials found at {OPENCODE_AUTH_PATH}. "
            "Run `opencode`, then `/connect` -> OpenCode Go to subscribe, "
            "or set OPENCODE_GO_API_KEY in .env."
        )
    with open(OPENCODE_AUTH_PATH) as f:
        auth = json.load(f)

    entry = auth.get("opencode-go")
    if not isinstance(entry, dict) or not entry.get("key"):
        raise RuntimeError(
            f"No OpenCode Go key in {OPENCODE_AUTH_PATH}. "
            "Run `opencode`, then `/connect` -> OpenCode Go to subscribe, "
            "or set OPENCODE_GO_API_KEY in .env."
        )
    return entry["key"]


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_opencode_go_usage() -> OpenCodeGoUsage:
    """Fetch OpenCode Go subscription usage via the Zen API."""
    api_key = _load_opencode_go_key()

    resp = requests.get(
        OPENCODE_GO_USAGE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "token-usage-dash",
        },
        timeout=15,
    )

    if resp.status_code == 401:
        raise RuntimeError(
            "OpenCode Go rejected the API key (401). "
            "Re-run `/connect` -> OpenCode Go in OpenCode, or set "
            "OPENCODE_GO_API_KEY in .env."
        )
    resp.raise_for_status()

    # Unknown paths on opencode.ai return an HTML 404 page, so never assume JSON.
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(
            "OpenCode Go usage endpoint returned a non-JSON response. "
            f"The endpoint may have moved (HTTP {resp.status_code})."
        ) from None

    usage = OpenCodeGoUsage()
    raw = data.get("usage") or {}

    def _window(w: Optional[dict]) -> Optional[GoWindow]:
        if not isinstance(w, dict):
            return None
        try:
            percent = float(w.get("percent", 0))
        except (TypeError, ValueError):
            percent = 0.0
        return GoWindow(used_percent=percent, resets_at=_parse_iso_utc(w.get("resetsAt")))

    usage.rolling = _window(raw.get("rolling"))
    usage.weekly  = _window(raw.get("weekly"))
    usage.monthly = _window(raw.get("monthly"))

    if usage.rolling is None and usage.weekly is None and usage.monthly is None:
        raise RuntimeError("OpenCode Go usage endpoint returned no usage windows.")

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
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    # Long horizons (weekly/monthly quotas) read better as days than as 167h/573h.
    if d > 0:
        return f"{d}d {h:02d}h" if h > 0 else f"{d}d"
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


def print_opencode_go_usage(usage: OpenCodeGoUsage) -> None:
    print("OpenCode Go plan usage:")
    rows = [
        ("5-hour ", usage.rolling),
        ("Weekly ", usage.weekly),
        ("Monthly", usage.monthly),
    ]
    any_data = False
    for label, w in rows:
        if not w:
            continue
        any_data = True
        resets = format_time_until(w.resets_at)
        print(f"  {label}  [{_bar(w.used_percent)}] {w.used_percent:5.1f}% used  {100-w.used_percent:5.1f}% left  resets in {resets}")
    if not any_data:
        print("  No usage data returned.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Show subscription plan usage")
    parser.add_argument("--claude-only", action="store_true")
    parser.add_argument("--openai-only", action="store_true")
    parser.add_argument("--opencode-only", action="store_true")
    args = parser.parse_args()

    only = args.claude_only or args.openai_only or args.opencode_only
    show_claude   = args.claude_only   or not only
    show_openai   = args.openai_only   or not only
    show_opencode = args.opencode_only or not only
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

    if show_opencode:
        print()
        try:
            print_opencode_go_usage(get_opencode_go_usage())
        except Exception as e:
            errors.append(str(e))
            print(f"OpenCode Go: error — {e}")

    print()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
