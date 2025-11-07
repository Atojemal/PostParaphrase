import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update, Bot
from telegram.ext import ContextTypes

from utils import firebase_utils, auth_utils

logger = logging.getLogger(__name__)

# Track users currently awaiting admin password (in-memory)
awaiting_admin_password = {}  # user_id -> True


async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point for admin authentication. Triggered by the special unique command.
    Asks the user for the admin password.
    """
    user = update.effective_user
    user_id = user.id
    awaiting_admin_password[user_id] = True
    # reply via message (update may be a MessageUpdate)
    if getattr(update, "message", None):
        await update.message.reply_text("Enter admin password:")
    elif getattr(update, "callback_query", None):
        await update.callback_query.message.reply_text("Enter admin password:")


async def catch_admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Catch messages that may be admin password replies.
    If user is in awaiting_admin_password, validate and register admin.
    """
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    # Some updates may not have .message (ignore)
    if not getattr(update, "message", None):
        return
    text = (update.message.text or "").strip()

    if not awaiting_admin_password.get(user_id):
        return  # Not in password flow

    logger.info("Admin auth attempt from user_id=%s", user_id)

    # Get stored hash from Firebase (initialized during startup)
    stored_hash = firebase_utils.get_admin_password_hash()
    if not stored_hash:
        # This should not happen if init completed correctly, but handle gracefully
        await update.message.reply_text("Admin password not configured.")
        awaiting_admin_password.pop(user_id, None)
        logger.warning("Admin auth failed: no stored password hash for user_id=%s", user_id)
        return

    if auth_utils.verify_password(text, stored_hash):
        # Register admin in Firebase so they don't need to re-authenticate
        await firebase_utils.register_admin(user_id, user.username or user.full_name)
        await update.message.reply_text("Authenticated as admin. You will receive daily reports.")
        logger.info("Admin authenticated: user_id=%s", user_id)
    else:
        await update.message.reply_text("❌ Incorrect password. Try again.")
        logger.warning("Admin authentication failed for user_id=%s", user_id)

    awaiting_admin_password.pop(user_id, None)


async def daily_report_loop(application_or_bot):
    """
    Background loop that runs every 24 hours and sends report to all admins stored in Firebase.

    application_or_bot may be:
      - an Application-like object with .bot
      - a Bot instance
    """
    # Wait a little before first run
    await asyncio.sleep(10)
    while True:
        try:
            admins = await firebase_utils.get_admins()
            if admins:
                total_users = await firebase_utils.get_total_users()
                paraphrases_last_24h = await firebase_utils.get_paraphrases_count_last_24h()
                message = (
                    f"Daily Report\n\nTotal users: {total_users}\nParaphrases in last 24 hours: {paraphrases_last_24h}"
                )
                for admin in admins:
                    try:
                        # Choose right sender
                        if hasattr(application_or_bot, "bot"):
                            # application-like
                            await application_or_bot.bot.send_message(chat_id=int(admin["user_id"]), text=message)
                        elif isinstance(application_or_bot, Bot):
                            await application_or_bot.send_message(chat_id=int(admin["user_id"]), text=message)
                        else:
                            # Best-effort: try to access .send_message
                            send = getattr(application_or_bot, "send_message", None)
                            if asyncio.iscoroutinefunction(send):
                                await send(chat_id=int(admin["user_id"]), text=message)
                            elif send:
                                loop = asyncio.get_running_loop()
                                await loop.run_in_executor(None, lambda: send(chat_id=int(admin["user_id"]), text=message))
                    except Exception:
                        logger.exception("Failed to send admin report to %s", admin.get("user_id"))
        except Exception:
            logger.exception("Error in daily_report_loop")
        # Sleep 24 hours
        await asyncio.sleep(12*3600)