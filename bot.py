"""
Application builder for python-telegram-bot.
Assembles all handlers and returns the bot Application instance.
"""
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from loguru import logger
from config import settings

from handlers.start import get_start_handler
from handlers.menu import menu_command, back_to_menu
from handlers.jobs import view_jobs, view_job_detail, save_job_callback, unsave_job_callback, save_manual_job_callback, unsave_manual_job_callback, jobs_filter_menu, handle_filter_toggle, daily_feed_command
from handlers.cover_letter import generate_cover_letter_callback, copy_cover_letter, coverletter_menu_handler
from handlers.resume import view_resume, ats_analyze_prompt, ats_analyze_result, ats_analyze_job_callback, replace_resume_prompt, replace_resume_receive
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
from handlers.admin import get_addjob_handler
from handlers.feedback import get_feedback_handler
from handlers.analytics import (
    analytics_command, users_command, user_detail_command, users_page_callback,
    deleted_users_command, deleted_users_page_callback
)
from handlers.refer import refer_command, refer_callback

from utils.messages import help_message


async def help_command(update, context):
    """Handle /help."""
    await update.message.reply_text(help_message(), parse_mode="MarkdownV2")


def build_bot() -> Application:
    """Build and configure the Telegram bot application."""
    logger.info("Building Telegram bot application...")
    
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Onboarding Flow (ConversationHandler)
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
    app.add_handler(CallbackQueryHandler(users_page_callback, pattern="^adm_users_\\d+$"))
    app.add_handler(CallbackQueryHandler(deleted_users_page_callback, pattern="^adm_delusers_\\d+$"))

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

    # Cover Letter Callbacks
    app.add_handler(CallbackQueryHandler(copy_cover_letter, pattern="^cl_copy_"))
    app.add_handler(CallbackQueryHandler(generate_cover_letter_callback, pattern="^(manual_)?cl_(generate|regen|tone)_"))



    # Resume/ATS Callbacks
    app.add_handler(CallbackQueryHandler(replace_resume_prompt, pattern="^resume_upload$"))
    app.add_handler(CallbackQueryHandler(ats_analyze_prompt, pattern="^ats_analyze$"))
    app.add_handler(CallbackQueryHandler(ats_analyze_job_callback, pattern="^(manual_)?ats_job_"))
    app.add_handler(MessageHandler(filters.Document.PDF, replace_resume_receive))
    async def text_router(update, context):
        if context.user_data.get("awaiting_settings_custom_skill"):
            await settings_custom_skill_receive(update, context)
        else:
            await ats_analyze_result(update, context)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Tracker & Analytics
    app.add_handler(CallbackQueryHandler(mark_applied_callback, pattern="^applied_"))
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

    logger.info("Bot application built successfully.")
    return app
