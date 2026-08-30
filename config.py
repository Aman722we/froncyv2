import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_URL: str = ""  # Only needed in production
    ADMIN_TELEGRAM_ID: int = 0  # Your personal Telegram ID for admin alerts

    # Database (Supabase PostgreSQL)
    DATABASE_URL: str

    # AI — NVIDIA NIM API
    NVIDIA_BASE_URL: str = "https://api.groq.com/openai/v1"
    NVIDIA_API_KEY_70B: str
    NVIDIA_API_KEY_8B: str
    NVIDIA_MODEL_70B: str = "openai/gpt-oss-120b"
    NVIDIA_MODEL_8B: str = "openai/gpt-oss-20b"

    # Payments — Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""  # Separate secret you set in Razorpay webhook config

    # App Config
    ENVIRONMENT: str = "development"
    MAX_COVER_LETTERS_FREE: int = 3

    # Development Overrides
    DEV_TELEGRAM_BOT_TOKEN: str = ""
    DEV_DATABASE_URL: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.ENVIRONMENT == "development":
            if self.DEV_TELEGRAM_BOT_TOKEN:
                self.TELEGRAM_BOT_TOKEN = self.DEV_TELEGRAM_BOT_TOKEN
            if self.DEV_DATABASE_URL:
                self.DATABASE_URL = self.DEV_DATABASE_URL


# Singleton settings instance
settings = Settings()
