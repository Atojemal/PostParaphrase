import asyncio
import json
import logging
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

from telegram import Bot
from telegram import Update as TgUpdate

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


async def poll_updates_loop(bot: Bot):
    """
    A simple long-polling loop using Bot.get_updates executed directly as coroutine.
    This avoids depending on the python-telegram-bot Application/Updater API surface,
    which can vary between installations.
    """
    logger.info("Starting updates poll loop")
    offset = None

    # Start background admin daily report task (accepts bot or application)
    asyncio.create_task(admin_handler.daily_report_loop(bot))

    # Start periodic maintenance
    asyncio.create_task(periodic_tasks(bot))

    while True:
        try:
            # Bot.get_updates is an async coroutine in some installs; await it directly.
            updates = await bot.get_updates(offset=offset, limit=100, timeout=GET_UPDATES_TIMEOUT, allowed_updates=None)
            if not updates:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for upd in updates:
                # Advance offset to acknowledge update
                try:
                    offset = (upd.update_id or 0) + 1
                except Exception:
                    pass

                # Build a minimal context per update
                context = SimpleContext(bot)

                # Messages
                if getattr(upd, "message", None):
                    msg = upd.message
                    text = (msg.text or "").strip()

                    # If /start command (may have payload)
                    if text.startswith("/start"):
                        parts = text.split(maxsplit=1)
                        if len(parts) > 1:
                            context.args = [parts[1]]
                        else:
                            context.args = []
                        asyncio.create_task(user_handler.start_command(upd, context))
                        asyncio.create_task(admin_handler.catch_admin_password(upd, context))
                        continue

                    # If exact admin unique string as plain message or /<unique>
                    if ADMIN_UNIQUE_STRING and (text == ADMIN_UNIQUE_STRING or text == f"/{ADMIN_UNIQUE_STRING}"):
                        asyncio.create_task(admin_handler.admin_entry(upd, context))
                        continue

                    # Normal text -> user text handler and also admin password catcher
                    asyncio.create_task(user_handler.text_message(upd, context))
                    asyncio.create_task(admin_handler.catch_admin_password(upd, context))
                    continue

                # Callback queries (inline buttons)
                if getattr(upd, "callback_query", None):
                    asyncio.create_task(user_handler.callback_query_handler(upd, context))
                    continue

                # Ignore other update types for now
        except Exception:
            logger.exception("Error in poll_updates_loop; continuing")
            # small backoff
            await asyncio.sleep(2)


def main():
    # Initialize Firebase and Gemini manager
    firebase_utils.init_firebase_from_env()
    gemini_utils.init_gemini_manager_from_env()

    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment")
        return

    bot = Bot(token=TELEGRAM_TOKEN)

    # Run asyncio event loop and start polling
    try:
        asyncio.run(poll_updates_loop(bot))
    except KeyboardInterrupt:
        logger.info("Shutting down (keyboard interrupt)")
    except Exception:
        logger.exception("Unexpected error in main")


if __name__ == "__main__":
    main()