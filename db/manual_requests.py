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


async def complete_request(request_id: int) -> bool:
    """Mark a request as COMPLETED."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE manual_requests SET status = 'COMPLETED', completed_at = NOW() WHERE id = $1",
            request_id,
        )
        return result == "UPDATE 1"
