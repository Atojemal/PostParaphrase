# main.py (updated with Flask webhook integration for Render, compatible with python-telegram-bot==13.7)
import asyncio
import json
import logging
import os
import threading
from dotenv import load_dotenv
from datetime import datetime, timedelta

from flask import Flask, request, Response
from telegram import Bot, Update as TgUpdate

# Local modules
from handlers import user_handler, admin_handler
from utils import firebase_utils, gemini_utils

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_UNIQUE_STRING = os.getenv("ADMIN_UNIQUE_STRING", "")
CLEANUP_INTERVAL = 60 * 10  # periodic tasks interval
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://your-service.onrender.com/webhook

app = Flask(__name__)
bot = None  # Global bot instance

class SimpleContext:
    def __init__(self, bot: Bot, args=None):
        self.bot = bot
        self.args = args or []

async def periodic_tasks(bot: Bot):
    logger.info("Starting periodic background tasks")
    while True:
        try:
            await firebase_utils.cleanup_expired_verification_messages(bot)
            gm = getattr(gemini_utils, "gemini_manager", None)
            if gm:
                await gm.maybe_rotate_key()
        except Exception:
            logger.exception("Error during periodic tasks")
        await asyncio.sleep(CLEANUP_INTERVAL)

async def process_update(update_json):
    global bot
    update = TgUpdate.de_json(update_json, bot)
    if not update:
        logger.warning("Invalid update received")
        return
    context = SimpleContext(bot)

    try:
        if update.message:
            msg = update.message
            text = (msg.text or "").strip()

            if text.startswith("/start"):
                parts = text.split(maxsplit=1)
                context.args = [parts[1]] if len(parts) > 1 else []
                await user_handler.start_command(update, context)
                await admin_handler.catch_admin_password(update, context)
                return

            if ADMIN_UNIQUE_STRING and (text == ADMIN_UNIQUE_STRING or text == f"/{ADMIN_UNIQUE_STRING}"):
                await admin_handler.admin_entry(update, context)
                return

            await user_handler.text_message(update, context)
            await admin_handler.catch_admin_password(update, context)
            return

        if update.callback_query:
            await user_handler.callback_query_handler(update, context)
            return
    except Exception as e:
        logger.exception(f"Error processing update: {e}")

@app.route('/')
def home():
    return "bot is alive"

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    update_json = request.get_json()
    if update_json:
        asyncio.create_task(process_update(update_json))
    return Response(status=200)

async def set_webhook(bot: Bot):
    if WEBHOOK_URL:
        try:
            await bot.set_webhook(url=WEBHOOK_URL + WEBHOOK_PATH)
            logger.info(f"Webhook set to {WEBHOOK_URL + WEBHOOK_PATH}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    else:
        logger.error("WEBHOOK_URL not set; cannot set webhook")

async def main_loop(bot: Bot):
    await set_webhook(bot)
    asyncio.create_task(admin_handler.daily_report_loop(bot))
    asyncio.create_task(periodic_tasks(bot))
    while True:
        await asyncio.sleep(3600)  # Keep async loop alive

def main():
    global bot
    firebase_utils.init_firebase_from_env()
    gemini_utils.init_gemini_manager_from_env()

    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment")
        return

    bot = Bot(token=TELEGRAM_TOKEN)

    # Start Flask (which also handles webhook updates)
    port = int(os.getenv("PORT", 5000))
    logger.info(f"Starting Flask on port {port}")

    # Start async tasks in a separate thread
    loop_thread = threading.Thread(target=asyncio.run, args=(main_loop(bot),), daemon=True)
    loop_thread.start()

    # Run Flask in the main thread
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()