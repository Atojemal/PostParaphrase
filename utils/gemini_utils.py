# gemini_utils.py (removed shortening logic)
import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import google.generativeai as genai

from utils import helpers

from telegram import Bot
from telegram import Update as TgUpdate
from telegram.error import Conflict

logger = logging.getLogger(__name__)

# Manager singleton
gemini_manager = None

def init_gemini_manager_from_env():
    """
    Initialize the GeminiManager singleton with keys from GEMINI_APIS env.
    GEMINI_APIS is expected to be a JSON mapping or array.
    """
    global gemini_manager
    raw = os.getenv("GEMINI_APIS", "[]")
    try:
        parsed = json.loads(raw)
        # parsed could be dict or list
        if isinstance(parsed, dict):
            keys = list(parsed.values())
        elif isinstance(parsed, list):
            keys = parsed
        else:
            keys = []
    except Exception:
        keys = []
    if not keys:
        logger.warning("No Gemini API keys found in GEMINI_APIS")
    gemini_manager = GeminiManager(keys)


class GeminiManager:
    """
    Manages a list of Gemini API keys and rotates when needed.
    Provides an async generate_paraphrases API.
    """

    def __init__(self, keys):
        self.keys = keys or []
        self.index = 0
        self.api_key = self.keys[self.index] if self.keys else None
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
            except Exception:
                # best-effort: continue without crashing
                logger.exception("Failed to configure genai with provided key")
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2)

        # Model configuration
        # Keep a commonly available model; adjust if needed for your account.
        self.model_name = "gemini-2.0-flash-lite"

    async def maybe_rotate_key(self):
        """
        Rotate to next API key if current one fails or per external triggers.
        """
        async with self._lock:
            if len(self.keys) <= 1:
                return False  # No rotation possible

            self.index = (self.index + 1) % len(self.keys)
            self.api_key = self.keys[self.index]
            try:
                genai.configure(api_key=self.api_key)
            except Exception:
                logger.exception("Failed to configure genai during rotation")
            logger.info(f"Rotated to Gemini API key index: {self.index}")
            return True

    async def generate_paraphrases(self, text: str, count: int):
        """
        Generate 'count' paraphrases for 'text' using Gemini API.
        Runs blocking SDK calls in a ThreadPoolExecutor to keep async loop responsive.
        """
        if not self.api_key:
            logger.error("No Gemini API keys available")
            return [helpers.fallback_paraphrase(text, idx + 1) for idx in range(count)]

        # Use an explicit separator token so parsing becomes reliable
        separator = "###PARAPHRASE_SEPARATOR###"

        prompt = (
            "Paraphrase the following post carefully.\n"
            "Your job is to rewrite the text using different wording while keeping the same meaning.\n"
            "\n"
            "Rules:\n"
            "- Keep the original language."
            "- Do NOT translate anything.\n"
            "- Maintain emojis, formatting, line breaks, bullet points, and spacing.\n"
            "- Keep numbers, symbols, and special characters unchanged.\n"
            "- The paraphrased result should sound natural and have about the same length as the original.\n"
            "- Do not remove links, usernames, or emojis.\n"
            f"\nPost:\n{text}\n\n"
            f"Provide {count} distinct paraphrased versions. Separate each version using the exact token: {separator}\n"
            "Do not add extra numbering or commentary outside the paraphrased text blocks."
        )

        # Run the blocking call in executor
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._call_gemini, prompt, count)

    def _call_gemini(self, prompt, count, max_retries=2):
        """
        Blocking call to Google Generative API with retry logic.
        """
        separator = "###PARAPHRASE_SEPARATOR###"
        for attempt in range(max_retries + 1):
            try:
                # Ensure genai is configured with current key
                if self.api_key:
                    try:
                        genai.configure(api_key=self.api_key)
                    except Exception:
                        logger.exception("Failed to configure genai with api_key before call")

                # Use GenerativeModel interface
                model = genai.GenerativeModel(self.model_name)

                generation_config = {
                    "temperature": 0.7,
                    "max_output_tokens": 800,
                }

                response = model.generate_content(prompt, generation_config=generation_config)

                # Extract generated text
                text_out = getattr(response, "text", None)
                if not text_out:
                    text_out = str(response)

                # If separator token present, split on it
                if separator in text_out:
                    parts = [p.strip() for p in text_out.split(separator) if p.strip()]
                    if len(parts) >= count:
                        return parts[:count]
                    # If fewer parts returned, supplement with fallback paraphrases
                    supplemented = parts + [helpers.fallback_paraphrase(prompt, idx + 1) for idx in range(len(parts), count)]
                    return supplemented

                # Otherwise use helper splitting heuristics
                paraphrases = helpers.split_paraphrases(text_out, expected=count)
                if len(paraphrases) >= count:
                    return paraphrases[:count]

                # If we didn't get enough, supplement with fallback
                supplemented = paraphrases + [helpers.fallback_paraphrase(prompt, idx + 1) for idx in range(len(paraphrases), count)]
                return supplemented

            except Exception as e:
                logger.error(f"Gemini API call failed (attempt {attempt + 1}): {e}")

                # Try rotating key and retry if possible
                if attempt < max_retries and len(self.keys) > 1:
                    try:
                        # rotate synchronously (blocking) since we're in threadpool
                        self.index = (self.index + 1) % len(self.keys)
                        self.api_key = self.keys[self.index]
                        genai.configure(api_key=self.api_key)
                        logger.info(f"Rotated to next key (attempt retry), index={self.index}")
                        continue
                    except Exception:
                        logger.exception("Rotation during retry failed")
                        continue

                # Final fallback
                if attempt == max_retries:
                    logger.error("All Gemini API attempts failed, using fallback")
                    return [helpers.fallback_paraphrase(prompt, idx + 1) for idx in range(count)]

    async def test_connection(self):
        """
        Test if current API key is working
        """
        if not self.api_key:
            return False

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._executor,
                self._test_gemini_connection
            )
            return result
        except Exception as e:
            logger.error(f"Gemini connection test failed: {e}")
            return False

    def _test_gemini_connection(self):
        """
        Test Gemini API connection
        """
        try:
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content("Say 'Hello' in one word.")
            return getattr(response, "text", None) is not None
        except Exception as e:
            logger.error(f"Gemini connection test error: {e}")
            return False


# Utility function to get the manager
def get_gemini_manager():
    global gemini_manager
    if gemini_manager is None:
        init_gemini_manager_from_env()
    return gemini_manager