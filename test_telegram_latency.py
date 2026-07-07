import asyncio
import time
from telegram import Bot
from config import settings

async def main():
    bot = Bot(settings.TELEGRAM_BOT_TOKEN)
    user_id = 1165801115
    
    print("Testing Telegram API Latency...")
    
    start = time.time()
    try:
        msg = await bot.send_message(chat_id=user_id, text="Latency test")
        print(f"send_message took: {time.time() - start:.3f}s")
        
        start = time.time()
        await bot.edit_message_text(chat_id=user_id, message_id=msg.message_id, text="Latency test 2")
        print(f"edit_message_text took: {time.time() - start:.3f}s")
        
        await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
