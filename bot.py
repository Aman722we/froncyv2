"""
Application builder for python-telegram-bot.
Assembles all handlers and returns the bot Application instance.
"""
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, TypeHandler, filters
from telegram.error import TelegramError
from loguru import logger
from config import settings
from utils.error_alert import send_error_alert

from handlers.start import get_start_handler
from handlers.menu import menu_command, back_to_menu
from handlers.jobs import view_jobs, view_job_detail, save_job_callback, unsave_job_callback, save_manual_job_callback, unsave_manual_job_callback, jobs_filter_menu, handle_filter_toggle, daily_feed_command, remind_me_callback, remind_me_manual_callback, apply_smart_callback, apply_smart_locked_callback
from handlers.cover_letter import generate_cover_letter_callback, copy_cover_letter, coverletter_menu_handler
from handlers.resume import view_resume, ats_analyze_prompt, ats_analyze_result, ats_analyze_job_callback, replace_resume_prompt, replace_resume_receive, generate_ats_pdf_callback, get_latex_code_callback, explore_loading_jobs_callback
from handlers.settings import (
    settings_command, status_command, view_saved_jobs,
    delete_account_prompt, delete_account_confirm,
    settings_edit_skills, settings_skill_toggle, settings_skills_done,
    settings_change_experience, settings_experience_save,
    settings_change_location, settings_location_save,
    settings_edit_role, settings_role_save,
    settings_alert_time, settings_alert_time_save,
    settings_change_batch, settings_batch_save,
    cancel_subscription_prompt, cancel_subscription_confirm,
    settings_add_custom_skill_prompt, settings_custom_skill_receive,
)
from handlers.payments import upgrade_command, checkout_handler
from handlers.tracker import (
    mark_applied_callback, tracker_dashboard, weekly_summary,
    manage_app_callback, update_app_status_callback
)
from handlers.admin import get_addjob_handler, send_message_command, broadcast_command
from handlers.feedback import get_feedback_handler
from handlers.analytics import (
    analytics_command, analytics_page_callback, users_command, user_detail_command, users_page_callback,
    deleted_users_command, deleted_users_page_callback
)
from handlers.refer import refer_command, refer_callback
from db.tracker import log_daily_active

from utils.messages import help_message


async def global_error_handler(update, context) -> None:
    """Catch-all error handler — fires when any Telegram handler raises an exception."""
    error = context.error

    # Build context string for the alert
    extra_parts = []
    if update and update.effective_user:
        extra_parts.append(f"user={update.effective_user.id}")
    if update and update.callback_query:
        extra_parts.append(f"callback={update.callback_query.data}")
    elif update and update.message:
        extra_parts.append(f"msg='{update.message.text or '(non-text)'}'")
    extra = " | ".join(extra_parts)

    logger.error(f"Unhandled exception in handler: {error}", exc_info=error)

    # Don't alert for benign Telegram errors (e.g. message not modified, user blocked bot)
    ignored = ("Message is not modified", "Query is too old", "bot was blocked")
    if isinstance(error, TelegramError) and any(msg in str(error) for msg in ignored):
        return

    try:
        await send_error_alert(
            bot=context.bot,
            source="Telegram Handler",
            error=error,
            extra=extra,
        )
    except Exception:
        pass  # Never let the alert crash the app


async def help_command(update, context):
    """Handle /help."""
    await update.message.reply_text(help_message(), parse_mode="MarkdownV2")



def build_bot() -> Application:
    """Build and configure the Telegram bot application."""
    logger.info("Building Telegram bot application...")
    
    from telegram.request import HTTPXRequest
    
    # Production-grade HTTP connection pool for Telegram API calls.
    # Default connection_pool_size=1 is a MASSIVE bottleneck — every API call
    # (query.answer, edit_message, send_message) queues behind a single TCP connection.
    # Bumping to 100 allows concurrent API calls and eliminates queueing delays.
    telegram_request = HTTPXRequest(
        connection_pool_size=100,
        pool_timeout=5.0,
        connect_timeout=5.0,
        read_timeout=10.0,
    )
    
    builder = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .request(telegram_request)
        .get_updates_request(telegram_request)
    )
    
    # In production we handle webhooks via FastAPI, so the built-in Updater
    # (designed for polling) is dead weight. Disabling it saves memory and
    # removes overhead from process_update().
    if settings.ENVIRONMENT == "production":
        builder = builder.updater(None)
    
    app = builder.build()

    # ── Global Pre-Processor (runs before all other handlers, group=-1) ──
    async def _global_pre_processor(update: Update, context) -> None:
        """Instantly stop loading spinners, and log activity in the background."""
        import asyncio
        
        if update.callback_query:
            pass
                
        # Run DB tracking in the background so it doesn't block the next handler
        if update.effective_user:
            asyncio.create_task(log_daily_active(update.effective_user.id))
            
    app.add_handler(TypeHandler(Update, _global_pre_processor), group=-1)
    app.add_handler(get_start_handler())
    app.add_handler(get_feedback_handler())

    # Main Menu & Core Commands
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("jobs", view_jobs))
    app.add_handler(CommandHandler("daily_feed", daily_feed_command))
    app.add_handler(CommandHandler("coverletter", coverletter_menu_handler))
    app.add_handler(CommandHandler("tracker", tracker_dashboard))
    app.add_handler(CommandHandler("resume", view_resume))
    app.add_handler(CommandHandler("saved", view_saved_jobs))
    app.add_handler(CommandHandler("upgrade", upgrade_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("delete_account", delete_account_prompt))
    app.add_handler(CommandHandler("refer", refer_command))

    # Admin Handlers
    app.add_handler(get_addjob_handler())
    app.add_handler(CommandHandler("analytics", analytics_command))
    app.add_handler(CommandHandler("users",     users_command))
    app.add_handler(CommandHandler("user",      user_detail_command))
    app.add_handler(CommandHandler("deletedusers", deleted_users_command))
    app.add_handler(CommandHandler("send",      send_message_command))

    app.add_handler(CallbackQueryHandler(users_page_callback, pattern="^adm_users_\\d+$"))
    app.add_handler(CallbackQueryHandler(deleted_users_page_callback, pattern="^adm_delusers_\\d+$"))
    app.add_handler(CallbackQueryHandler(analytics_page_callback, pattern="^analytics_page_\\d+$"))
    app.add_handler(CommandHandler("send", send_message_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Navigation Callbacks
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_menu$"))
    app.add_handler(CallbackQueryHandler(view_jobs, pattern="^menu_jobs$"))
    app.add_handler(CallbackQueryHandler(daily_feed_command, pattern="^menu_daily$"))
    app.add_handler(CallbackQueryHandler(view_resume, pattern="^menu_resume$"))
    app.add_handler(CallbackQueryHandler(view_saved_jobs, pattern="^menu_saved$"))
    app.add_handler(CallbackQueryHandler(settings_command, pattern="^menu_settings$"))
    app.add_handler(CallbackQueryHandler(upgrade_command, pattern="^menu_upgrade$"))
    app.add_handler(CallbackQueryHandler(coverletter_menu_handler, pattern="^menu_coverletter$"))
    app.add_handler(CallbackQueryHandler(refer_callback, pattern="^menu_refer$"))
    
    # Jobs Callbacks
    app.add_handler(CallbackQueryHandler(view_job_detail, pattern="^(job|manual)_view_"))
    app.add_handler(CallbackQueryHandler(save_job_callback, pattern="^job_save_"))
    app.add_handler(CallbackQueryHandler(unsave_job_callback, pattern="^job_unsave_"))
    app.add_handler(CallbackQueryHandler(save_manual_job_callback, pattern="^manual_job_save_"))
    app.add_handler(CallbackQueryHandler(unsave_manual_job_callback, pattern="^manual_job_unsave_"))
    app.add_handler(CallbackQueryHandler(view_jobs, pattern="^jobs_page_"))
    app.add_handler(CallbackQueryHandler(jobs_filter_menu, pattern="^jobs_filter_menu$"))
    app.add_handler(CallbackQueryHandler(handle_filter_toggle, pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(view_jobs, pattern="^menu_jobs_filtered$"))
    app.add_handler(CallbackQueryHandler(remind_me_callback, pattern="^remind_job_"))
    app.add_handler(CallbackQueryHandler(remind_me_manual_callback, pattern="^remind_manual_"))
    app.add_handler(CallbackQueryHandler(apply_smart_callback, pattern="^apply_smart_\\d+$"))
    app.add_handler(CallbackQueryHandler(apply_smart_locked_callback, pattern="^apply_smart_locked$"))

    # Cover Letter Callbacks
    app.add_handler(CallbackQueryHandler(copy_cover_letter, pattern="^(manual_)?cl_copy_"))
    app.add_handler(CallbackQueryHandler(generate_cover_letter_callback, pattern="^(manual_)?cl_(generate|regen|tone)_"))



    # Resume/ATS Callbacks
    app.add_handler(CallbackQueryHandler(replace_resume_prompt, pattern="^resume_upload$"))
    app.add_handler(CallbackQueryHandler(ats_analyze_prompt, pattern="^ats_analyze$"))
    app.add_handler(CallbackQueryHandler(ats_analyze_job_callback, pattern="^(manual_)?ats_job_"))
    app.add_handler(CallbackQueryHandler(generate_ats_pdf_callback, pattern="^gen_ats_pdf_"))
    app.add_handler(CallbackQueryHandler(get_latex_code_callback, pattern="^get_latex_"))
    app.add_handler(CallbackQueryHandler(explore_loading_jobs_callback, pattern="^explore_loading_jobs$"))
    app.add_handler(MessageHandler(filters.Document.PDF, replace_resume_receive))
    async def text_router(update, context):
        if context.user_data.get("awaiting_settings_custom_skill"):
            await settings_custom_skill_receive(update, context)
        else:
            await ats_analyze_result(update, context)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Tracker & Analytics
    app.add_handler(CallbackQueryHandler(mark_applied_callback, pattern="^(manual_)?applied_"))
    app.add_handler(CallbackQueryHandler(tracker_dashboard, pattern="^tracker"))
    app.add_handler(CallbackQueryHandler(manage_app_callback, pattern="^manage_app_"))
    app.add_handler(CallbackQueryHandler(update_app_status_callback, pattern="^updapp_"))
    app.add_handler(CallbackQueryHandler(weekly_summary, pattern="^weekly_summary$"))
    
    # Settings Callbacks
    app.add_handler(CallbackQueryHandler(status_command, pattern="^settings_status$"))
    app.add_handler(CallbackQueryHandler(settings_edit_skills, pattern="^settings_skills$"))
    app.add_handler(CallbackQueryHandler(settings_skill_toggle, pattern="^skill_"))
    app.add_handler(CallbackQueryHandler(settings_add_custom_skill_prompt, pattern="^add_custom_skill$"))
    app.add_handler(CallbackQueryHandler(settings_skills_done, pattern="^skills_done$"))
    app.add_handler(CallbackQueryHandler(settings_change_experience, pattern="^settings_experience$"))
    app.add_handler(CallbackQueryHandler(settings_experience_save, pattern="^setexp_"))
    app.add_handler(CallbackQueryHandler(settings_change_location, pattern="^settings_location$"))
    app.add_handler(CallbackQueryHandler(settings_location_save, pattern="^setloc_"))
    app.add_handler(CallbackQueryHandler(settings_edit_role, pattern="^settings_role$"))
    app.add_handler(CallbackQueryHandler(settings_role_save, pattern="^setrole_"))
    app.add_handler(CallbackQueryHandler(settings_alert_time, pattern="^settings_alert_time$"))
    app.add_handler(CallbackQueryHandler(settings_alert_time_save, pattern="^setalert_"))
    app.add_handler(CallbackQueryHandler(settings_change_batch, pattern="^settings_batch$"))
    app.add_handler(CallbackQueryHandler(settings_batch_save, pattern="^setbatch_"))
    app.add_handler(CallbackQueryHandler(delete_account_prompt, pattern="^settings_delete$"))
    app.add_handler(CallbackQueryHandler(delete_account_confirm, pattern="^confirm_delete_yes$"))
    app.add_handler(CallbackQueryHandler(cancel_subscription_prompt, pattern="^settings_cancel_sub$"))
    app.add_handler(CallbackQueryHandler(cancel_subscription_confirm, pattern="^confirm_cancel_sub$"))

    # Upgrade/Payments Callbacks
    app.add_handler(CallbackQueryHandler(checkout_handler, pattern="^upgrade_(pro|proplus|premium)$"))

    # Global error handler — alerts admin on any unhandled exception
    app.add_error_handler(global_error_handler)

    logger.info("Bot application built successfully.")
    return app
