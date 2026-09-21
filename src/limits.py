"""
Safety limits for a deployment that anyone can reach. Every limit is OFF unless its environment variable is
set, so local runs and tests are never throttled:

  WRITE_LIMIT_PER_MINUTE     max changes (POST/PUT/PATCH/DELETE) per visitor per minute
  AUTH_LIMIT_PER_15_MIN      max log-in / sign-up attempts per visitor per 15 minutes (slows password guessing)
  DAILY_SIGNUP_LIMIT         max new accounts per day
  DAILY_SUMMARY_LIMIT        max Claude-written plan summaries per day (over the cap, a standard summary is used)
  DAILY_SCREENSHOT_LIMIT     max screenshot readings (Claude vision) per day
  DAILY_FOOD_LOOKUP_LIMIT    max automatic USDA nutrition lookups per day (over the cap, values are entered by hand)
  MAX_FOODS_PER_USER         max foods in one person's library
  KEEP_PLAN_BATCHES          how many generated plans to keep per person (older ones are deleted)
  MAX_UPLOAD_MB              largest upload accepted (default 500)
  MAX_EXPORT_XML_MB          largest export.xml accepted after unzipping (0 = no limit)
"""

import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


def int_setting(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


_recent = defaultdict(deque)


def client_ip(request) -> str:
    # Behind Render's proxy the last X-Forwarded-For entry is the address that reached the
    # proxy; earlier entries can be forged by the visitor.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"


def _rate_limited(bucket: str, ip: str, limit: int, window_seconds: int, now: float = None) -> bool:
    if limit <= 0:
        return False
    now = time.time() if now is None else now
    window = _recent[(bucket, ip)]
    while window and now - window[0] > window_seconds:
        window.popleft()
    if len(window) >= limit:
        return True
    window.append(now)
    return False


def too_many_writes(ip: str, now: float = None) -> bool:
    return _rate_limited("write", ip, int_setting("WRITE_LIMIT_PER_MINUTE"), 60, now)


def too_many_auth_attempts(ip: str, now: float = None) -> bool:
    return _rate_limited("auth", ip, int_setting("AUTH_LIMIT_PER_15_MIN"), 15 * 60, now)


def reset_rate_limits() -> None:
    _recent.clear()


def use_daily_allowance(conn, kind: str, env_name: str) -> bool:
    """Counts one use of `kind` against today's cap. False means the cap is used up.
    With the setting unset (or 0) there is no cap and nothing is counted."""
    limit = int_setting(env_name)
    if limit <= 0:
        return True
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO usage_counters (day, kind, count) VALUES (?, ?, 0) ON CONFLICT (day, kind) DO NOTHING",
        (day, kind),
    )
    cursor = conn.execute(
        "UPDATE usage_counters SET count = count + 1 WHERE day = ? AND kind = ? AND count < ?",
        (day, kind, limit),
    )
    conn.commit()
    return cursor.rowcount == 1
