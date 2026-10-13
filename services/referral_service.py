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


async def process_referral(
    referrer_id: int, 
    new_user_id: int, 
    pool, 
    bot_id: int = 1
) -> tuple[bool, int, datetime | None]:
    """
    Award REFERRAL_BONUS_DAYS Pro days to referrer.
    Returns:
        (success: bool, days_awarded: int, new_expires_at: datetime | None)
    """
    # Self-referral guard
    if referrer_id == new_user_id:
        logger.warning(f"Self-referral attempt blocked for {referrer_id}")
        return False, 0, None

    async with pool.acquire() as conn:
        # Check new user hasn't already credited a referrer
        new_user = await conn.fetchrow(
            """
            SELECT referred_by, referral_rewarded 
            FROM users 
            WHERE telegram_id = $1 AND bot_id = $2
            """, 
            new_user_id, bot_id
        )
        if not new_user:
            logger.warning(f"New user {new_user_id} not found on bot {bot_id}")
            return False, 0, None

        if new_user.get("referral_rewarded"):
            logger.info(f"User {new_user_id} was already rewarded — skipping")
            return False, 0, None

        existing_referred_by = new_user.get("referred_by")
        if existing_referred_by and existing_referred_by != referrer_id:
            logger.info(f"User {new_user_id} has different referrer {existing_referred_by} vs {referrer_id}")
            return False, 0, None

        # Check referrer exists on this bot
        referrer = await conn.fetchrow(
            """
            SELECT telegram_id, plan, is_trial, trial_expires_at, plan_expires_at, referral_bonus_days 
            FROM users 
            WHERE telegram_id = $1 AND bot_id = $2
            """,
            referrer_id, bot_id
        )
        if not referrer:
            logger.warning(f"Referrer {referrer_id} not found in DB on bot {bot_id}")
            return False, 0, None

        current_bonus = referrer["referral_bonus_days"] or 0
        if current_bonus >= REFERRAL_MAX_DAYS:
            logger.info(f"Referrer {referrer_id} already at max bonus ({REFERRAL_MAX_DAYS} days)")
            # Still mark new user as rewarded so we don't double-credit
            await conn.execute(
                """
                UPDATE users 
                SET referred_by = $1, referral_rewarded = TRUE 
                WHERE telegram_id = $2 AND bot_id = $3
                """,
                referrer_id, new_user_id, bot_id
            )
            return False, 0, None

        # Calculate actual days to award (respect cap)
        days_to_award = min(REFERRAL_BONUS_DAYS, REFERRAL_MAX_DAYS - current_bonus)

        # Mark new user as referred and rewarded
        await conn.execute(
            """
            UPDATE users 
            SET referred_by = $1, referral_rewarded = TRUE 
            WHERE telegram_id = $2 AND bot_id = $3
            """,
            referrer_id, new_user_id, bot_id
        )

        now = datetime.now(timezone.utc)

        if referrer["plan"] in ("pro", "proplus", "premium"):
            # Paid Pro user — extend their plan expiration date
            exp = referrer.get("plan_expires_at")
            exp_aware = exp.replace(tzinfo=timezone.utc) if (exp and exp.tzinfo is None) else (exp or now)
            new_expires = max(exp_aware, now) + timedelta(days=days_to_award)
            await conn.execute(
                """
                UPDATE users
                SET plan_expires_at = $1,
                    referral_bonus_days = referral_bonus_days + $2,
                    updated_at = NOW()
                WHERE telegram_id = $3 AND bot_id = $4
                """,
                new_expires, days_to_award, referrer_id, bot_id
            )
        else:
            # Free user or trial user — allocate exactly the Pro Trial plan!
            # Trial = full Pro entitlements (8 daily jobs, instant alerts, browse all jobs, quality AI)
            exp = referrer.get("trial_expires_at")
            exp_aware = exp.replace(tzinfo=timezone.utc) if (exp and exp.tzinfo is None) else None
            # If current trial is still active in the future, add to it; otherwise start from now
            base_time = exp_aware if (exp_aware and exp_aware > now) else now
            new_expires = base_time + timedelta(days=days_to_award)
            await conn.execute(
                """
                UPDATE users
                SET is_trial = TRUE,
                    trial_used = TRUE,
                    trial_started_at = COALESCE(trial_started_at, $1),
                    trial_expires_at = $2,
                    plan = 'trial',
                    referral_bonus_days = referral_bonus_days + $3,
                    updated_at = NOW()
                WHERE telegram_id = $4 AND bot_id = $5
                """,
                now, new_expires, days_to_award, referrer_id, bot_id
            )

    logger.info(
        f"Referral processed: referrer={referrer_id} earned {days_to_award} days "
        f"(total bonus={current_bonus + days_to_award}) on bot {bot_id} for referring {new_user_id}. "
        f"New expiry: {new_expires}"
    )
    return True, days_to_award, new_expires


async def get_referral_stats(telegram_id: int, pool, bot_id: int = 1) -> dict:
    """Return referral stats for a user on a given bot."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT referral_bonus_days FROM users WHERE telegram_id = $1 AND bot_id = $2", 
            telegram_id, bot_id
        )
        referral_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM users 
            WHERE referred_by = $1 AND bot_id = $2 AND referral_rewarded = TRUE
            """, 
            telegram_id, bot_id
        )

    bonus_days    = (row["referral_bonus_days"] or 0) if row else 0
    days_left_cap = max(0, REFERRAL_MAX_DAYS - bonus_days)

    return {
        "referrals_made": referral_count or 0,
        "bonus_days_earned": bonus_days,
        "days_until_cap": days_left_cap,
        "at_cap": bonus_days >= REFERRAL_MAX_DAYS,
    }
