# main.py (updated with Flask integration for Render web service)
import asyncio
import json
import logging
import os
import threading
from dotenv import load_dotenv
from datetime import datetime, timedelta

from flask import Flask
from telegram import Bot
from telegram import Update as TgUpdate
from telegram.error import Conflict

# Local modules (handlers expect telegram.Update and a simple context with .bot and .args)
from handlers import user_handler, admin_handler
from utils import firebase_utils, gemini_utils

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_UNIQUE_STRING = os.getenv("ADMIN_UNIQUE_STRING", "")
POLL_INTERVAL = 1  # seconds between polling when no updates
GET_UPDATES_TIMEOUT = 30  # long-polling timeout seconds
CLEANUP_INTERVAL = 60 * 10  # periodic tasks interval

# Flask app for Render web service
app = Flask(__name__)

@app.route('/')
def home():
    return "bot is alive"

class SimpleContext:
    """
    Very small context object compatible with handler signatures used in this project.
    Handlers expect context.bot and sometimes context.args.
    """
    def __init__(self, bot: Bot, args=None):
        self.bot = bot
        self.args = args or []


async def periodic_tasks(bot: Bot):
    """
    Background loop to run periodic maintenance tasks:
    - cleanup expired verification messages
    - allow gemini manager to rotate key if necessary
    """
    logger.info("Starting periodic background tasks")
    while True:
        try:
            # pass the bot to allow deleting messages
            await firebase_utils.cleanup_expired_verification_messages(bot)
            gm = getattr(gemini_utils, "gemini_manager", None)
            if gm:
                await gm.maybe_rotate_key()
        except Exception:
            logger.exception("Error during periodic tasks")
        await asyncio.sleep(CLEANUP_INTERVAL)


# ...existing code...
async def poll_updates_loop(bot: Bot):
    logger.info("Starting updates poll loop")
    offset = None

    # Start background admin daily report task (accepts bot or application)
    asyncio.create_task(admin_handler.daily_report_loop(bot))

    # Start periodic maintenance
    asyncio.create_task(periodic_tasks(bot))

    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=GET_UPDATES_TIMEOUT)
            for upd in updates:
                if upd.update_id:
                    offset = upd.update_id + 1
                try:
                    context = SimpleContext(bot)
                    # ...existing code...
                except Exception:
                    pass
        except Conflict:
            # Another getUpdates/webhook conflict — attempt to clear webhook and retry
            logger.warning("Conflict: another getUpdates/webhook exists. Deleting webhook and retrying.")
            try:
                # delete_webhook may be sync or async depending on library version; try await first
                try:
                    await bot.delete_webhook(drop_pending_updates=True)
                except TypeError:
                    bot.delete_webhook(drop_pending_updates=True)
                logger.info("Webhook deleted, resuming polling")
            except Exception:
                logger.exception("Failed to delete webhook after Conflict")
            await asyncio.sleep(2)
            continue
        except Exception:
            logger.exception("Error in poll_updates_loop; continuing")
            # small backoff
            await asyncio.sleep(2)
# ...existing code...

def run_flask():
    port = int(os.getenv("PORT", 5000))  # Render sets PORT env var
    logger.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def main():
    # Initialize Firebase and Gemini manager
    firebase_utils.init_firebase_from_env()
    gemini_utils.init_gemini_manager_from_env()

    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment")
        return

    bot = Bot(token=TELEGRAM_TOKEN)

    # Ensure no webhook is set (avoid Conflict when using getUpdates)
    try:
        # drop_pending_updates=True clears any queued updates so the poller starts clean
        bot.delete_webhook(drop_pending_updates=True)
        logger.info("Deleted existing webhook (if any) before starting long-polling")
    except Exception:
        logger.exception("Failed to delete webhook on startup; continuing")

    # Start Flask in a separate thread for Render web service
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Run asyncio event loop and start polling
    try:
        asyncio.run(poll_updates_loop(bot))
    except KeyboardInterrupt:
        logger.info("Shutting down (keyboard interrupt)")
    except Exception:
        logger.exception("Unexpected error in main")
# ...existing code...