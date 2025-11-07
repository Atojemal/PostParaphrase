# paraphrase_handler.py (no major changes needed, but added validation for count=1)
import json
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils import firebase_utils, gemini_utils, helpers

logger = logging.getLogger(__name__)

async def handle_paraphrase_request(bot, user_id: int, text: str, count: int, reply_message):
    """
    Core flow for handling a paraphrase request:
    - Check verification threshold (first 10 paraphrases free)
    - Check daily limit (20/day)
    - If blocked, send interactive invite UI (Share / Try Again)
    - Otherwise call Gemini and send paraphrased messages, updating counters.
    """
    if not text:
        await reply_message.reply_text("No message found. Send a message first using /start.")
        return

    # Validate count (now supports 1,2,4)
    if count not in [1, 2, 4]:
        await reply_message.reply_text("Invalid number of paraphrases selected. Please try again.")
        return

    # Fetch user record
    user = await firebase_utils.get_user(user_id)
    verified = user.get("verified", False)
    total_paraphrases = user.get("paraphrase_total", 0)
    paraphrases_today = user.get("paraphrase_today", 0)

    # If user unverified and already used 20 paraphrases, send verification prompt
    if not verified and total_paraphrases >= 20:
        v_link = firebase_utils.get_verification_link()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Verify", url=v_link)]]
        )
        msg = await reply_message.reply_text("Please verify your account.", reply_markup=keyboard)
        # Store for 24-hour deletion
        await firebase_utils.store_verification_message(user_id, msg.chat.id, msg.message_id)
        return

    # Daily limit check
    if paraphrases_today + count > firebase_utils.DAILY_LIMIT:
        # Interactive invite UI: Share (opens inline share) and Try Again (callback)
        bot_info = await bot.get_me()
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
        await reply_message.reply_text(
            "You’ve reached your daily limit! Invite others to continue.",
            reply_markup=keyboard,
        )
        return

    # Generate paraphrases
    try:
        paraphrases = await gemini_utils.gemini_manager.generate_paraphrases(text, count)
    except Exception as e:
        logger.exception("Gemini paraphrase error: %s", e)
        await reply_message.reply_text("Failed to generate paraphrases. Please try again later.")
        return

    # Send paraphrased messages; each as its own message. The last message includes Add More / New Message buttons.
    for idx, p in enumerate(paraphrases, start=1):
        wrapped_text = f"<pre>{p}</pre>"
        reply_markup = None
        if idx == len(paraphrases):
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Add More", callback_data=json.dumps({"action": "add_more"})),
                        InlineKeyboardButton("New Message", callback_data=json.dumps({"action": "new_message"})),
                    ]
                ]
            )
        await reply_message.reply_text(wrapped_text, parse_mode='HTML', reply_markup=reply_markup)

    # Update counters in Firebase and global event log
    await firebase_utils.increment_paraphrases(user_id, count)