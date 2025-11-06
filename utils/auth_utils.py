import bcrypt


def verify_password(plain_text_password: str, hashed: str) -> bool:
    """
    Verify a password against a bcrypt hash (stored as string).
    """
    try:
        return bcrypt.checkpw(plain_text_password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False