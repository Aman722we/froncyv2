import asyncio
import os
import sys

# Add project root to path so config.settings works
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

# Users who experienced the Apply Smart bug
USER_IDS = [
    6022653906, # Karanjit
    725566153   # Chirag
]

async def notify_users():
    text = (
        "⚠️ *Oops! We had a temporary server hiccup.*\n\n"
        "Hey! We noticed that your *Apply Smart* kit generation failed recently due to a server upgrade we were running in the background.\n\n"
        "The issue has been fully resolved, and we've made sure your usage limit was not consumed. We sincerely apologize for the inconvenience!\n\n"
        "You can now head back into the jobs menu to safely generate your kit. 🚀"
    )
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Explore Jobs", callback_data="menu_jobs")]
    ])
    
    for uid in USER_IDS:
        try:
            await bot.send_message(
                chat_id=uid,
                text=text,
                parse_mode="Markdown",
                reply_markup=markup
            )
            print(f"✅ Successfully notified {uid}")
        except Exception as e:
            print(f"❌ Failed to notify {uid}: {e}")

if __name__ == "__main__":
    asyncio.run(notify_users())
