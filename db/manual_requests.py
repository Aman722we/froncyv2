"""
CRUD for manual_requests table.
Acts as the admin fulfillment queue for HR Contact and Resume Review requests.
"""
from loguru import logger
from db.connection import get_pool


async def create_request(
    user_id: int,
    request_type: str,
    job_id: int | None = None,
    notes: str | None = None,
) -> int:
    """Insert a new pending request. Returns the new request ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO manual_requests (user_id, request_type, job_id, notes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            user_id, request_type.upper(), job_id, notes,
        )
        return row["id"]


async def get_pending_requests(request_type: str | None = None) -> list[dict]:
    """Return all PENDING requests, optionally filtered by type."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if request_type:
            rows = await conn.fetch(
                """
                SELECT r.*, u.username, u.first_name
                FROM manual_requests r
                LEFT JOIN users u ON u.telegram_id = r.user_id
                WHERE r.status = 'PENDING' AND r.request_type = $1
                ORDER BY r.created_at ASC
                """,
                request_type.upper(),
            )
        else:
            rows = await conn.fetch(
                """
                SELECT r.*, u.username, u.first_name
                FROM manual_requests r
                LEFT JOIN users u ON u.telegram_id = r.user_id
                WHERE r.status = 'PENDING'
                ORDER BY r.created_at ASC
                """
            )
        return [dict(r) for r in rows]


async def complete_request(request_id: int, admin_reply: str | None = None) -> bool:
    """Mark a request as COMPLETED and optionally store the reply."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE manual_requests SET status = 'COMPLETED', completed_at = NOW(), admin_reply = $2 WHERE id = $1",
            request_id, admin_reply
        )
        return result == "UPDATE 1"


async def has_existing_request(user_id: int, request_type: str, job_id: int | None = None) -> bool:
    """Check if the user already requested this so they don't spam clicks."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if job_id:
            val = await conn.fetchval(
                "SELECT 1 FROM manual_requests WHERE user_id = $1 AND request_type = $2 AND job_id = $3",
                user_id, request_type.upper(), job_id
            )
        else:
            val = await conn.fetchval(
                "SELECT 1 FROM manual_requests WHERE user_id = $1 AND request_type = $2 AND status = 'PENDING'",
                user_id, request_type.upper()
            )
        return val is not None


async def get_completed_request_reply(user_id: int, request_type: str, job_id: int) -> str | None:
    """Get the admin reply for a completed request."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT admin_reply FROM manual_requests WHERE user_id = $1 AND request_type = $2 AND job_id = $3 AND status = 'COMPLETED'",
            user_id, request_type.upper(), job_id
        )


async def is_request_completed(user_id: int, request_type: str, job_id: int) -> bool:
    """Check if a request is already marked as COMPLETED (even if admin_reply is None)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM manual_requests WHERE user_id = $1 AND request_type = $2 AND job_id = $3 AND status = 'COMPLETED'",
            user_id, request_type.upper(), job_id
        )
        return val is not None
async def refund_request(request_id: int, admin_reply: str) -> dict | None:
    """Mark request as REFUNDED and return the request dict if successful."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE manual_requests SET status = 'REFUNDED', completed_at = NOW(), admin_reply = $2 WHERE id = $1 RETURNING *",
            request_id, admin_reply
        )
        return dict(row) if row else None
