import json
import logging
import os
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# Import utils and the paraphrase handler from the handlers package (not utils)
from utils import firebase_utils, helpers, gemini_utils
from handlers import paraphrase_handler

logger = logging.getLogger(__name__)

# In-memory map for awaiting special replies (e.g., admin password). Keys: user_id -> state
pending_password = {}  # Used by admin handler; kept here for visibility
# In-memory session for last message and last choice
user_sessions = {}  # user_id -> {"text": str, "last_choice": int}


# ...existing code...
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start
    If started with a payload (referral), record referral.
    Ask user to send a message to paraphrase.
    """
    user = update.effective_user
    args = context.args or []

    # Check for referral payload in /start payload (Telegram sends as argument)
    if args:
        invite_code = args[0]
        try:
            credited, inviter_id = await firebase_utils.apply_referral(user.id, invite_code)
            if credited and inviter_id:
                # Notify inviter about earned credits
                try:
                    await context.bot.send_message(
                        chat_id=int(inviter_id),
                        text=f"✅ You earned 20 paraphrase credits for inviting {user.username or user.full_name}."
                    )
                except Exception:
                    logger.exception("Failed to notify inviter about referral credit")
        except Exception:
            logger.exception("Error applying referral")

    # Save user record in DB
    await firebase_utils.create_or_get_user(user.id, user.username, user.full_name)

    await update.message.reply_text("Welcome! Send your message.")
# ...existing code...

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle regular text messages:
    - If user was in admin password flow, delegate to admin handler
    - Otherwise treat it as the message to paraphrase and ask how many versions (2 or 4)
    """
    user = update.effective_user
    text = update.message.text.strip()
    user_id = user.id

    # Save the original message in session (in-memory and DB)
    user_sessions[user_id] = {"text": text, "last_choice": None}
    await firebase_utils.save_user_session(user_id, text)

    # Ask how many paraphrases
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("2", callback_data=json.dumps({"action": "choose", "count": 2})),
                InlineKeyboardButton("4", callback_data=json.dumps({"action": "choose", "count": 4})),
            ]
        ]
    )
    await update.message.reply_text("How many paraphrased versions do you want?", reply_markup=keyboard)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Central callback query handler (2 / 4 / Add More / New Message / Try Again)
    """
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = user.id

    data_raw = query.data
    try:
        data = json.loads(data_raw)
    except Exception:
        logger.exception("Failed to parse callback data: %s", data_raw)
        return

    action = data.get("action")
    if action == "choose":
        count = int(data.get("count", 2))
        # Save last choice in session
        session = user_sessions.get(user_id) or {"text": None}
        session["last_choice"] = count
        user_sessions[user_id] = session
        await firebase_utils.save_user_last_choice(user_id, count)

        # Trigger paraphrase action
        await paraphrase_handler.handle_paraphrase_request(
            context.bot, user_id, session.get("text"), count, query.message
        )

    elif action == "add_more":
        # Get last choice and text from session or DB
        session = user_sessions.get(user_id)
        if not session or not session.get("text"):
            # Try DB
            session = await firebase_utils.get_user_session(user_id)
        count = session.get("last_choice", 2)
        await paraphrase_handler.handle_paraphrase_request(
            context.bot, user_id, session.get("text"), count, query.message
        )

    elif action == "new_message":
        # Reset session and ask for new message
        user_sessions.pop(user_id, None)
        await firebase_utils.clear_user_session(user_id)
        await query.message.reply_text("Send your new message.")

    elif action == "try_invite":
        """
        Try Again flow:
        - Check Firebase for new referrals that haven't been acknowledged
        - If found, acknowledge them, apply credits and inform the user
        - If none found, inform the user and re-show Share / Try Again buttons
        """
        try:
            # This function will return how many new referrals were acknowledged
            acknowledged_count = await firebase_utils.acknowledge_referrals_and_apply_credits(str(user_id))
            if acknowledged_count and acknowledged_count > 0:
                earned = acknowledged_count * 20
                await query.message.reply_text(
                    f"✅ You have invited {acknowledged_count} person(s). You’ve earned {earned} credits. Send your message to continue paraphrasing."
                )
            else:
                # No new referrals found - re-show share + try again buttons
                bot_info = await context.bot.get_me()
                bot_username = bot_info.username if bot_info else "ParaphraseBot"
                invite_code = await firebase_utils.ensure_invite_code(user_id)
                invite_link = f"https://t.me/{bot_username}?start={invite_code}"
                share_text = f"✨ Your friend invited you to use the Paraphrase Bot!\nStart here: {invite_link}"
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("Share", switch_inline_query=share_text),
                            InlineKeyboardButton("Try Again", callback_data=json.dumps({"action": "try_invite"})),
                        ]
                    ]
                )
                await query.message.reply_text(
                    "❌ No new invited users found. Please invite more friends and click “Try Again” again.",
                    reply_markup=keyboard,
                )
        except Exception:
            logger.exception("Error handling try_invite")
            await query.message.reply_text("An error occurred checking invites. Please try again later.")


# Provide these names for imports in main
__all__ = ["start_command", "text_message", "callback_query_handler", "user_sessions"]