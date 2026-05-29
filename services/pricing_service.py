"""
Pricing service — manages early adopter pricing, trial system, and slot tracking.
"""
from datetime import datetime, timedelta, timezone

# Launch date — when early adopter pricing started
LAUNCH_DATE = datetime(2026, 4, 26, tzinfo=timezone.utc)
EARLY_ADOPTER_DAYS = 30   # Early adopter pricing lasts 30 days
EARLY_ADOPTER_SLOTS = 200  # Max early adopter slots


async def get_current_pricing(db_pool) -> dict:
    """
    Returns current pricing state.
    Early adopter = slots not yet full (200 pro users).
    Time limit removed — price stays at ₹199 until 200 users subscribe.
    """
    config = await db_pool.fetchrow("SELECT * FROM pricing_config LIMIT 1")

    now = datetime.now(timezone.utc)
    # FUTURE: can re-add days cap if needed
    # days_since_launch = (now - LAUNCH_DATE).days
    early_adopter_active = (
        config["early_adopter_active"] and
        config["slots_filled"] < config["early_adopter_slots"]
    )

    slots_remaining = max(0, config["early_adopter_slots"] - config["slots_filled"])
    # days_remaining kept for compatibility but always shows max now
    days_remaining = EARLY_ADOPTER_DAYS

    return {
        "is_early_adopter_active": early_adopter_active,
        "current_price": (
            config["early_adopter_price"]
            if early_adopter_active
            else config["regular_price"]
        ),
        "early_adopter_price": config["early_adopter_price"],
        "regular_price": config["regular_price"],
        "slots_remaining": slots_remaining,
        "slots_filled": config["slots_filled"],
        "days_remaining": days_remaining,
        "total_slots": config["early_adopter_slots"],
    }


async def increment_slots_filled(db_pool):
    """Call this when a user successfully upgrades via early adopter pricing."""
    await db_pool.execute("""
        UPDATE pricing_config
        SET slots_filled = slots_filled + 1
        WHERE early_adopter_active = TRUE
          AND slots_filled < early_adopter_slots
    """)


async def start_trial(telegram_id: int, db_pool):
    """Start 3-day free trial for a new user. Only activates once."""
    now = datetime.now(timezone.utc)
    trial_expires = now + timedelta(days=3)

    await db_pool.execute("""
        UPDATE users
        SET is_trial = TRUE,
            trial_used = TRUE,
            trial_started_at = $2,
            trial_expires_at = $3,
            plan = 'trial'
        WHERE telegram_id = $1
          AND trial_started_at IS NULL
    """, telegram_id, now, trial_expires)

    return trial_expires


async def check_trial_status(telegram_id: int, db_pool) -> dict:
    """Returns trial status for a user."""
    user = await db_pool.fetchrow(
        "SELECT * FROM users WHERE telegram_id = $1",
        telegram_id
    )
    if not user:
        return {"status": "no_trial"}

    now = datetime.now(timezone.utc)

    if user["plan"] == "pro":
        return {"status": "pro"}

    if not user["is_trial"] and user["plan"] not in ("trial",):
        return {"status": "no_trial"}

    if user["trial_expires_at"] and now > user["trial_expires_at"]:
        # Trial expired — downgrade
        await db_pool.execute("""
            UPDATE users
            SET plan = 'free', is_trial = FALSE
            WHERE telegram_id = $1
        """, telegram_id)
        return {"status": "expired"}

    if user["trial_expires_at"]:
        hours_remaining = int(
            (user["trial_expires_at"] - now).total_seconds() / 3600
        )
        return {
            "status": "active",
            "hours_remaining": hours_remaining,
            "expires_at": user["trial_expires_at"],
        }

    return {"status": "no_trial"}
