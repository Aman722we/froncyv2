with open("handlers/admin.py", "r", encoding="utf-8") as f:
    content = f.read()

func_code = """
async def completerequest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    \"\"\"/completerequest <req_id> <message to user> - Complete a manual request.\"\"\"
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_TELEGRAM_ID:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "<b>Usage:</b> /completerequest &lt;req_id&gt; &lt;message to user...&gt;\\n\\n"
            "<b>Example:</b>\\n"
            "<code>/completerequest 1 Here is the hiring manager: John Doe (john@okta.com)</code>",
            parse_mode="HTML"
        )
        return

    try:
        req_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Request ID must be a number.")
        return

    reply_text = " ".join(args[1:])
    
    from db.connection import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow("SELECT user_id, request_type FROM manual_requests WHERE id = $1", req_id)
        if not req:
            await update.message.reply_text(f"❌ Could not find request #{req_id}.")
            return

        target_user_id = req["user_id"]
        req_type = req["request_type"]
        
        from db.manual_requests import complete_request
        success = await complete_request(req_id)
        if not success:
            await update.message.reply_text("❌ Failed to update request status in DB. Still sending message.")

    try:
        title = "👔 <b>HR Contact Details</b>" if req_type == "HR_CONTACT" else "📄 <b>Resume Review Feedback</b>"
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"{title}\\n\\n{reply_text}",
            parse_mode="HTML"
        )
        await update.message.reply_text(f"✅ Request #{req_id} marked as complete! Message sent to user <code>{target_user_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message to user: {e}")
"""

# Append to handlers/admin.py
with open("handlers/admin.py", "a", encoding="utf-8") as f:
    f.write(func_code)

print("Added completerequest_command")
