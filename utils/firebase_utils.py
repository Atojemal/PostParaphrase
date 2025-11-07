import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

import bcrypt
import firebase_admin
from firebase_admin import credentials, firestore

from utils import helpers

logger = logging.getLogger(__name__)

# Constants
DAILY_LIMIT = 20  # per README (kept as-is to avoid changing other logic)

# Module-level variables set by init
_db = None
_firestore_client = None
_verification_link = os.getenv("VERIFICATION_LINK", "https://web-telegram-org-verify.onrender.com/")
_admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", "")


def init_firebase_from_env():
    """
    Initialize firebase-admin using the FIREBASE_KEY env var (JSON string).
    Handles values wrapped with quotes in .env.
    Also ensures admin password is initialized in Firestore (only once).
    """
    global _db, _firestore_client, _admin_password_hash
    firebase_json = os.getenv("FIREBASE_KEY")
    if not firebase_json:
        raise RuntimeError("FIREBASE_KEY not set in environment")

    # strip surrounding single quotes if present (common when using .env)
    if firebase_json.startswith("'") and firebase_json.endswith("'"):
        firebase_json = firebase_json[1:-1]

    cred_dict = json.loads(firebase_json)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    _db = firestore.client()
    _firestore_client = _db

    # Ensure admin password is persisted in Firestore (only if missing)
    try:
        _ensure_admin_password_in_firestore()
    except Exception:
        logger.exception("Failed to ensure admin password in Firestore during init")


def _ensure_admin_password_in_firestore():
    """
    Synchronous helper (called during init) that:
    - checks Firestore for an admin password hash document
    - if missing, reads ADMIN_PASSWORD_HASH from env, hashes it if needed, and stores it
    - updates module-level _admin_password_hash variable with the value stored in Firestore
    """
    global _admin_password_hash
    try:
        doc_ref = _firestore_client.collection("config").document("admin_password")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            stored_hash = data.get("hash")
            if stored_hash:
                _admin_password_hash = stored_hash
                logger.info("Loaded admin password hash from Firestore")
                return
            # else continue to initialize from env
        # If we reached here, no stored hash found in Firestore. Initialize from env.
        env_hash = os.getenv("ADMIN_PASSWORD_HASH", "")
        if not env_hash:
            logger.warning("ADMIN_PASSWORD_HASH not set in environment; admin password will not be available until configured")
            _admin_password_hash = ""
            return

        # If env_hash looks like a bcrypt hash (starts with $2a$/$2b$/$2y$), assume it's already hashed.
        if isinstance(env_hash, str) and (env_hash.startswith("$2a$") or env_hash.startswith("$2b$") or env_hash.startswith("$2y$")):
            hashed = env_hash
            logger.info("Using bcrypt hash found in ENV for admin password")
        else:
            # Hash the plain-text password from env
            try:
                hashed = bcrypt.hashpw(env_hash.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                logger.info("Hashed admin password from ENV and storing to Firestore")
            except Exception:
                logger.exception("Failed to hash ADMIN_PASSWORD_HASH from env")
                hashed = env_hash  # fallback (not ideal) but ensures something is stored

        # Store hashed value in Firestore
        try:
            doc_ref.set({"hash": hashed, "created_at": datetime.utcnow()})
            _admin_password_hash = hashed
            logger.info("Admin password hash stored in Firestore (initialized)")
        except Exception:
            logger.exception("Failed to store admin password hash in Firestore")
            _admin_password_hash = hashed  # still set locally
    except Exception:
        logger.exception("Unexpected error initializing admin password in Firestore")
        _admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", "")


async def create_or_get_user(user_id, username=None, full_name=None):
    """
    Ensure a user document exists.
    """
    doc_ref = _firestore_client.collection("users").document(str(user_id))
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set(
            {
                "user_id": str(user_id),
                "username": username,
                "full_name": full_name,
                "paraphrase_total": 0,
                "paraphrase_today": 0,
                "last_paraphrase_date": None,
                "verified": False,
                "invite_code": None,
                "inviter_id": None,
                "invites": 0,
            }
        )
    else:
        # Optionally update username/full_name
        pass
    return await get_user(user_id)


async def get_user(user_id):
    doc_ref = _firestore_client.collection("users").document(str(user_id))
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {}


async def save_user_session(user_id, text):
    """
    Save last message in a small session subcollection for persistence.
    """
    _firestore_client.collection("users").document(str(user_id)).collection("session").document("last").set(
        {"text": text, "updated_at": firestore.SERVER_TIMESTAMP}
    )


async def get_user_session(user_id):
    doc = _firestore_client.collection("users").document(str(user_id)).collection("session").document("last").get()
    if doc.exists:
        return doc.to_dict()
    return {"text": None, "last_choice": None}


async def save_user_last_choice(user_id, count):
    _firestore_client.collection("users").document(str(user_id)).collection("session").document("last").set(
        {"last_choice": count}, merge=True
    )


async def clear_user_session(user_id):
    _firestore_client.collection("users").document(str(user_id)).collection("session").document("last").delete()


def get_verification_link():
    return _verification_link


async def store_verification_message(user_id, chat_id, message_id):
    """
    Store a verification message entry with expiry time (24 hours).
    Periodic cleanup will delete the message then remove the doc.
    """
    expire_at = datetime.utcnow() + timedelta(hours=24)
    _firestore_client.collection("verification_messages").add(
        {
            "user_id": str(user_id),
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "expire_at": expire_at,
            "created_at": datetime.utcnow(),
        }
    )


async def cleanup_expired_verification_messages(application_or_bot=None):
    """
    Find expired verification messages and delete them from chat and Firestore.

    application_or_bot may be:
      - an Application-like object with .bot (use .bot.delete_message)
      - a Bot instance (use bot.delete_message)
      - None (only clean Firestore records)
    """
    now = datetime.utcnow()
    q = _firestore_client.collection("verification_messages").where("expire_at", "<=", now).stream()
    for doc in q:
        data = doc.to_dict()
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")
        try:
            if application_or_bot:
                # choose the proper deleter
                deleter = None
                if hasattr(application_or_bot, "bot"):
                    deleter = application_or_bot.bot
                else:
                    deleter = application_or_bot
                # If deleter has an async delete_message, await it; if sync, call in thread
                delete_coro = None
                if asyncio.iscoroutinefunction(getattr(deleter, "delete_message", None)):
                    delete_coro = deleter.delete_message(chat_id=chat_id, message_id=message_id)
                    await delete_coro
                else:
                    # call sync method in thread to avoid blocking
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: deleter.delete_message(chat_id=chat_id, message_id=message_id))
        except Exception:
            # ignore deletion errors
            pass
        try:
            doc.reference.delete()
        except Exception:
            pass


async def increment_paraphrases(user_id, count):
    """
    Increment counters for the user and record global paraphrase event(s) with timestamp.
    """
    uid = str(user_id)
    user_ref = _firestore_client.collection("users").document(uid)
    txn = _firestore_client.transaction()

    @firestore.transactional
    def update_counts(transaction):
        snapshot = user_ref.get(transaction=transaction)
        if snapshot.exists:
            data = snapshot.to_dict()
            total = data.get("paraphrase_total", 0) + count
            last_date = data.get("last_paraphrase_date")
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            paraphrase_today = data.get("paraphrase_today", 0)
            if last_date != today_str:
                paraphrase_today = count
            else:
                paraphrase_today += count
            transaction.update(user_ref, {"paraphrase_total": total, "paraphrase_today": paraphrase_today, "last_paraphrase_date": today_str})
        else:
            transaction.set(user_ref, {"paraphrase_total": count, "paraphrase_today": count, "last_paraphrase_date": datetime.utcnow().strftime("%Y-%m-%d")})

    update_counts(txn)

    # Log each paraphrase event into a global collection to compute 24h windows
    batch = _firestore_client.batch()
    for _ in range(count):
        doc_ref = _firestore_client.collection("paraphrase_events").document()
        batch.set(doc_ref, {"user_id": uid, "ts": datetime.utcnow()})
    batch.commit()


async def ensure_invite_code(user_id):
    """
    Ensure user has an invite code and return it.
    """
    uid = str(user_id)
    doc_ref = _firestore_client.collection("users").document(uid)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        code = data.get("invite_code")
        if code:
            return code
        # generate one
        code = helpers.make_invite_code(uid)
        doc_ref.update({"invite_code": code})
        return code
    else:
        await create_or_get_user(user_id)
        return await ensure_invite_code(user_id)


async def apply_referral(new_user_id, invite_code):
    """
    When a new user starts with an invite code, credit the inviter with +20 paraphrase credits.
    This function now:
      - checks if the new user already exists (no credits if they do)
      - if new, registers the user, credits the inviter once, and logs the referral (acknowledged=False)
    Returns: (credited: bool, inviter_id: Optional[str])
    """
    uid_new = str(new_user_id)

    # If the new user already exists, do not award credits
    new_user_doc = _firestore_client.collection("users").document(uid_new).get()
    if new_user_doc.exists:
        return (False, None)

    # Find inviter by invite_code
    q = _firestore_client.collection("users").where("invite_code", "==", invite_code).stream()
    inviter_doc = None
    for doc in q:
        inviter_doc = doc
        break

    if not inviter_doc:
        # No valid inviter found
        return (False, None)

    inviter_id = inviter_doc.id

    # Create the new user's record (safe to call; will create fresh user)
    await create_or_get_user(new_user_id)

    # Credit inviter: add 20 to paraphrase_total and increment invites
    inviter_ref = _firestore_client.collection("users").document(inviter_id)
    inviter_ref.update({"paraphrase_total": firestore.Increment(20), "invites": firestore.Increment(1)})

    # Log referral event with acknowledged=False (so Try Again can pick it up)
    _firestore_client.collection("referrals").add(
        {"inviter_id": inviter_id, "new_user_id": uid_new, "ts": datetime.utcnow(), "acknowledged": False}
    )

    return (True, inviter_id)


def get_admin_password_hash():
    """
    Return the cached admin password hash (loaded during init).
    """
    return _admin_password_hash


async def register_admin(user_id, display_name):
    """
    Save admin record in admins collection.
    """
    _firestore_client.collection("admins").document(str(user_id)).set(
        {"user_id": str(user_id), "display_name": display_name, "created_at": datetime.utcnow()}
    )


async def get_admins():
    docs = _firestore_client.collection("admins").stream()
    out = []
    for d in docs:
        out.append(d.to_dict())
    return out


async def get_total_users():
    docs = _firestore_client.collection("users").stream()
    count = sum(1 for _ in docs)
    return count


async def get_paraphrases_count_last_24h():
    """
    Count paraphrase_events in last 24 hours.
    """
    now = datetime.utcnow()
    since = now - timedelta(hours=24)
    q = _firestore_client.collection("paraphrase_events").where("ts", ">=", since).stream()
    count = sum(1 for _ in q)
    return count


# Referral helper functions (unchanged)
async def _fetch_unacknowledged_referrals(inviter_id: str):
    """
    Return list of referral document snapshots where inviter_id matches and acknowledged == False.
    """
    docs = _firestore_client.collection("referrals").where("inviter_id", "==", inviter_id).stream()
    out = []
    for d in docs:
        data = d.to_dict()
        if not data.get("acknowledged", False):
            out.append(d)
    return out


async def acknowledge_referrals_and_apply_credits(inviter_id: str):
    """
    Called when a user clicks 'Try Again'. Finds unacknowledged referrals, marks them acknowledged,
    and applies earned credits so the user can continue paraphrasing.

    Returns the number of newly acknowledged referrals.
    """
    uid = str(inviter_id)
    referrals = await _fetch_unacknowledged_referrals(uid)
    if not referrals:
        return 0

    # Count and acknowledge them in a batch
    count = len(referrals)
    batch = _firestore_client.batch()
    for doc in referrals:
        batch.update(doc.reference, {"acknowledged": True, "ack_ts": datetime.utcnow()})
    batch.commit()

    # Apply credits: each referral grants 20 credits. To allow immediate usage, reduce paraphrase_today by earned credits.
    earned = count * 20
    user_ref = _firestore_client.collection("users").document(uid)
    txn = _firestore_client.transaction()

    @firestore.transactional
    def apply_credit(transaction):
        snapshot = user_ref.get(transaction=transaction)
        if snapshot.exists:
            data = snapshot.to_dict()
            paraphrase_today = data.get("paraphrase_today", 0)
            last_date = data.get("last_paraphrase_date")
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            # If last_paraphrase_date is not today, paraphrase_today counts as 0 for today
            if last_date != today_str:
                paraphrase_today = 0
            # We reduce the paraphrase_today counter so that available allowance increases by 'earned'
            new_paraphrase_today = max(0, paraphrase_today - earned)
            transaction.update(user_ref, {"paraphrase_today": new_paraphrase_today, "paraphrase_total": firestore.Increment(0)})
        else:
            # If user record missing, create minimal record with credits applied (i.e., paraphrase_today = 0)
            transaction.set(user_ref, {"paraphrase_total": 0, "paraphrase_today": 0, "last_paraphrase_date": datetime.utcnow().strftime("%Y-%m-%d")})

    apply_credit(txn)

    return count