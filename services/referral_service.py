"""
Referral service — awards Pro days for successful referrals.
Rules:
  - 5 days per referral
  - Max 30 days total per user
  - Triggers only when referred user completes onboarding
  - Cannot refer yourself
  - Each new user can only credit one referrer
"""
from datetime import datetime, timedelta, timezone
from loguru import logger


REFERRAL_BONUS_DAYS = 5
REFERRAL_MAX_DAYS   = 30


async def process_referral(referrer_id: int, new_user_id: int, pool) -> bool:
    """
    Award REFERRAL_BONUS_DAYS Pro days to referrer.
    Returns True if reward was granted, False otherwise.
    """
    # Self-referral guard
    if referrer_id == new_user_id:
        logger.warning(f"Self-referral attempt blocked for {referrer_id}")
        return False

    async with pool.acquire() as conn:
        # Check new user hasn't already credited someone
        new_user = await conn.fetchrow(
            "SELECT referred_by FROM users WHERE telegram_id = $1", new_user_id
        )
        if not new_user or new_user["referred_by"] is not None:
            logger.info(f"User {new_user_id} already has a referrer — skipping")
            return False

        # Check referrer exists and hasn't hit the cap
        referrer = await conn.fetchrow(
            "SELECT telegram_id, plan, is_trial, trial_expires_at, referral_bonus_days FROM users WHERE telegram_id = $1",
            referrer_id
        )
        if not referrer:
            logger.warning(f"Referrer {referrer_id} not found in DB")
            return False

        current_bonus = referrer["referral_bonus_days"] or 0
        if current_bonus >= REFERRAL_MAX_DAYS:
            logger.info(f"Referrer {referrer_id} already at max bonus ({REFERRAL_MAX_DAYS} days)")
            # Still mark the new user's referrer so we don't double-credit
            await conn.execute(
                "UPDATE users SET referred_by = $1 WHERE telegram_id = $2",
                referrer_id, new_user_id
            )
            return False

        # Calculate actual days to award (respect cap)
        days_to_award = min(REFERRAL_BONUS_DAYS, REFERRAL_MAX_DAYS - current_bonus)

        # Mark the new user's referrer
        await conn.execute(
            "UPDATE users SET referred_by = $1 WHERE telegram_id = $2",
            referrer_id, new_user_id
        )

        # Extend or start referrer's trial
        now = datetime.now(timezone.utc)

        if referrer["plan"] == "pro":
            # Pro users get nothing from referral (already on paid plan)
            # But still track bonus days for when they downgrade
            await conn.execute(
                "UPDATE users SET referral_bonus_days = referral_bonus_days + $1 WHERE telegram_id = $2",
                days_to_award, referrer_id
            )
        elif referrer["is_trial"] and referrer["trial_expires_at"]:
            # Extend existing active trial
            exp = referrer["trial_expires_at"]
            exp_aware = exp.replace(tzinfo=timezone.utc) if exp.tzinfo is None else exp
            new_expires = max(exp_aware, now) + timedelta(days=days_to_award)
            await conn.execute(
                """
                UPDATE users
                SET trial_expires_at = $1,
                    referral_bonus_days = referral_bonus_days + $2,
                    is_trial = TRUE,
                    plan = 'trial'
                WHERE telegram_id = $3
                """,
                new_expires, days_to_award, referrer_id
            )
        else:
            # Free user with no active trial — start a fresh bonus trial
            new_expires = now + timedelta(days=days_to_award)
            await conn.execute(
                """
                UPDATE users
                SET is_trial = TRUE,
                    trial_expires_at = $1,
                    plan = 'trial',
                    referral_bonus_days = referral_bonus_days + $2
                WHERE telegram_id = $3
                """,
                new_expires, days_to_award, referrer_id
            )

    logger.info(
        f"Referral processed: referrer={referrer_id} earned {days_to_award} days "
        f"(total bonus={current_bonus + days_to_award}) for referring {new_user_id}"
    )
    return True


async def get_referral_stats(telegram_id: int, pool) -> dict:
    """Return referral stats for a user."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT referral_bonus_days FROM users WHERE telegram_id = $1", telegram_id
        )
        referral_count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE referred_by = $1", telegram_id
        )

    bonus_days    = (row["referral_bonus_days"] or 0) if row else 0
    days_left_cap = max(0, REFERRAL_MAX_DAYS - bonus_days)

    return {
        "referrals_made": referral_count,
        "bonus_days_earned": bonus_days,
        "days_until_cap": days_left_cap,
        "at_cap": bonus_days >= REFERRAL_MAX_DAYS,
    }
