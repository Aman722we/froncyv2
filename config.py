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
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # AI — NVIDIA NIM API
    NVIDIA_BASE_URL: str = "https://api.groq.com/openai/v1"
    NVIDIA_API_KEY_70B: str
    NVIDIA_API_KEY_8B: str
    NVIDIA_MODEL_70B: str = "openai/gpt-oss-120b"
    NVIDIA_MODEL_8B: str = "llama-3.1-8b-instant"  # Fast text completion model on Groq — not agentic

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
    DEV_SUPABASE_URL: str = ""
    DEV_SUPABASE_KEY: str = ""

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
        
        # Override with DEV tokens if provided (regardless of ENVIRONMENT so test bots can run anywhere)
        if self.DEV_SUPABASE_URL:
            self.SUPABASE_URL = self.DEV_SUPABASE_URL
        if self.DEV_SUPABASE_KEY:
            self.SUPABASE_KEY = self.DEV_SUPABASE_KEY


# Singleton settings instance
settings = Settings()
