import httpx
from config import settings
from loguru import logger

async def upload_resume(user_id: int, filename: str, file_bytes: bytes) -> str | None:
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        logger.error("Supabase URL or Key not configured.")
        return None
        
    url = f"{settings.SUPABASE_URL}/storage/v1/object/resumes/{user_id}/{filename}"
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "apikey": settings.SUPABASE_KEY,
        "Content-Type": "application/pdf",
        # Upsert allows overwriting if the user uploads a new resume with the same name
        "x-upsert": "true" 
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, content=file_bytes)
        
    if resp.status_code in (200, 201):
        public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/resumes/{user_id}/{filename}"
        return public_url
    else:
        logger.error(f"Failed to upload resume to Supabase: {resp.status_code} - {resp.text}")
        return None
