"""
Payment Service — Razorpay integration for subscription management.
"""
import razorpay
from loguru import logger
from config import settings


def _get_client() -> razorpay.Client:
    """Get Razorpay client instance."""
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


# Plan pricing in paise (1 INR = 100 paise)
PLAN_PRICES = {
    "pro": {"amount": 9900, "name": "Pro", "display": "₹99/month"},
    "proplus": {"amount": 69900, "name": "Pro+", "display": "₹699/month"},
    "premium": {"amount": 149900, "name": "Premium", "display": "₹1,499/month"},
}


async def _get_or_create_plan(client: razorpay.Client, db_pool, is_early_adopter: bool, amount: int) -> str:
    """Gets existing Razorpay Plan ID or creates one dynamically and saves it to DB."""
    config = await db_pool.fetchrow("SELECT * FROM pricing_config LIMIT 1")
    
    plan_col = "razorpay_early_plan_id" if is_early_adopter else "razorpay_reg_plan_id"
    existing_plan_id = config.get(plan_col)
    
    if existing_plan_id:
        return existing_plan_id
        
    # Create the plan on Razorpay
    plan_name = "FroncyBot Pro (Early Adopter)" if is_early_adopter else "FroncyBot Pro (Regular)"
    amount_paise = amount * 100
    
    logger.info(f"Creating Razorpay plan dynamically: {plan_name} for ₹{amount}")
    razorpay_plan = client.plan.create({
        "item": {
            "name": plan_name,
            "amount": amount_paise,
            "currency": "INR",
            "description": f"Automated recurring subscription for {plan_name}"
        },
        "period": "monthly",
        "interval": 1
    })
    
    plan_id = razorpay_plan["id"]
    
    # Save it to DB
    await db_pool.execute(f"UPDATE pricing_config SET {plan_col} = $1", plan_id)
    return plan_id


async def create_subscription_link(
    plan: str,
    telegram_id: int,
    db_pool,
    amount: int | None = None,
    is_early_adopter: bool = False,
) -> str | None:
    """
    Create a Razorpay Subscription link.
    """
    if plan not in PLAN_PRICES and amount is None:
        logger.error(f"Invalid plan: {plan}")
        return None

    plan_info = PLAN_PRICES.get(plan, {"name": "Pro"})
    amount_val = amount if amount else (plan_info.get("amount", 9900) // 100)
    display_price = f"₹{amount_val}"

    try:
        client = _get_client()
        
        # 1. Ensure user has a razorpay_customer_id (if required, though subscriptions can just be created without it to let user fill it. 
        # But for easier tracking, it's better to just create the subscription. Razorpay subscription creation does not STRICTLY require customer_id if we want them to checkout as guest, BUT it does require customer_notify: 1)
        
        # 2. Get the proper plan ID
        plan_id = await _get_or_create_plan(client, db_pool, is_early_adopter, amount_val)

        # 3. Create Subscription
        subscription = client.subscription.create({
            "plan_id": plan_id,
            "total_count": 12, # Auto-renews for up to 1 year, then requires new authorization
            "customer_notify": 1,
            "notes": {
                "telegram_id": str(telegram_id),
                "plan": plan,
                "is_early_adopter": "true" if is_early_adopter else "false",
            }
        })

        url = subscription.get("short_url")
        sub_id = subscription.get("id")
        
        logger.info(f"Subscription link created for user {telegram_id}: {url}")
        return url

    except Exception as e:
        logger.error(f"Failed to create subscription link: {e}")
        return None


async def cancel_user_subscription(telegram_id: int, db_pool) -> bool:
    """Cancel active subscription at cycle end."""
    user = await db_pool.fetchrow("SELECT razorpay_subscription_id FROM users WHERE telegram_id = $1", telegram_id)
    if not user or not user.get("razorpay_subscription_id"):
        return False
        
    sub_id = user["razorpay_subscription_id"]
    try:
        client = _get_client()
        client.subscription.cancel(sub_id, {"cancel_at_cycle_end": 1})
        await db_pool.execute("UPDATE users SET subscription_status = 'cancelling' WHERE telegram_id = $1", telegram_id)
        return True
    except Exception as e:
        logger.error(f"Failed to cancel subscription {sub_id}: {e}")
        return False


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Razorpay webhook signature using HMAC-SHA256.
    Returns False (reject) if secret is not configured — never silently passes.
    """
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not set — rejecting all webhooks for safety")
        return False
    try:
        client = _get_client()
        client.utility.verify_webhook_signature(
            payload.decode("utf-8"),
            signature,
            settings.RAZORPAY_WEBHOOK_SECRET,
        )
        return True
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return False


def extract_payment_info(webhook_data: dict) -> dict | None:
    """
    Extract telegram_id and plan from Razorpay webhook payload for subscriptions.
    """
    try:
        # For subscription events (subscription.charged)
        entity = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
        notes = entity.get("notes", {})
        telegram_id = int(notes.get("telegram_id", 0))
        plan = notes.get("plan", "")
        sub_id = entity.get("id", "")
        customer_id = entity.get("customer_id", "")

        if telegram_id and plan in PLAN_PRICES:
            return {
                "telegram_id": telegram_id, 
                "plan": plan, 
                "sub_id": sub_id, 
                "customer_id": customer_id
            }

        # Alternate path if payment event is used
        payment = webhook_data.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        telegram_id = int(notes.get("telegram_id", 0))
        plan = notes.get("plan", "")
        
        if telegram_id and plan in PLAN_PRICES:
            return {"telegram_id": telegram_id, "plan": plan}

    except Exception as e:
        logger.error(f"Failed to extract payment info: {e}")

    return None
