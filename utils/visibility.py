"""
Unified Job Visibility Gatekeeper (RFC-004)
Single authoritative choke point governing job visibility across all send and browse paths.

Contexts:
  - 'instant': Real-time instant drops (Pro instant drops & Free weekly samples).
               Enforces: Blocked, Paused, Unlinked (fail-closed if mutes > 0), Mutes (with children), Watchlist.
  - 'digest': Morning daily feed delivery.
              Enforces: Blocked, Paused, Unlinked (fail-closed if mutes > 0), Mutes (with children).
              (Watchlist mode does NOT drop digest jobs; formatter pins followed companies at top).
  - 'sample': RFC-003 free sample candidate selection.
              Enforces: Blocked, Paused, Unlinked (fail-closed if mutes > 0), Mutes (with children).
  - 'browse': Interactive user browsing (/jobs command, manual search, detail views).
              Enforces: Unlinked (fail-closed if mutes > 0), Mutes (with children).
              (Blocked and Paused gates NEVER apply to user-initiated interactive browsing).
"""
from datetime import datetime, timezone
from loguru import logger


def is_job_visible_to_user(
    user: dict,
    job: dict,
    user_mutes: set[int] | None = None,
    user_follows: set[int] | None = None,
    context: str = "instant",
    now_utc: datetime | None = None,
) -> bool:
    """
    Evaluates whether a job can be sent to or viewed by a user.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # 1. Blocked User Gate (Push contexts only, never interactive browse)
    if context in ("instant", "digest", "sample"):
        if user.get("is_blocked"):
            return False

    # 2. Alerts Paused Gate (Push contexts only, never interactive browse)
    if context in ("instant", "digest", "sample"):
        paused_until = user.get("alerts_paused_until")
        if paused_until:
            if hasattr(paused_until, "tzinfo") and paused_until.tzinfo is None:
                paused_until = paused_until.replace(tzinfo=timezone.utc)
            if paused_until > now_utc:
                return False

    job_company_id = job.get("company_id")
    mutes = user_mutes or set()
    follows = user_follows or set()

    # 3. Unlinked Job Safety (Fail-Closed)
    if job_company_id is None:
        # If user has ANY active mutes, drop unlinked jobs across all contexts
        # to strictly protect employer privacy against backfill gaps.
        if len(mutes) > 0:
            return False
        # If user has 0 mutes: allowed in 'all' mode, blocked in 'watchlist' mode for instant drops
        filter_mode = user.get("company_filter_mode", "all")
        if filter_mode == "watchlist" and context == "instant":
            return False
        return True

    # 4. Employer Mute Gate (Covers company and all child subsidiaries)
    # Applies unconditionally across ALL contexts, including browse.
    if job_company_id in mutes:
        return False

    # 5. Watchlist Mode Gate (Only narrows instant drops for Pro users in watchlist mode)
    if context == "instant":
        is_pro = user.get("plan") in ("pro", "trial", "proplus", "premium")
        filter_mode = user.get("company_filter_mode", "all")
        if is_pro and filter_mode == "watchlist":
            return job_company_id in follows

    return True
