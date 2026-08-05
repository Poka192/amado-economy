"""비밀번호 해시(PBKDF2) + 서명 쿠키 세션."""
import hashlib
import hmac
import os

from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import SECRET_KEY

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="session")


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$")
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000
    ).hex()
    return hmac.compare_digest(calc, digest)


def make_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str, max_age: int = 60 * 60 * 24 * 30):
    """(user_id, None) 또는 예외. 만료 시 BadSignature."""
    try:
        data = _serializer.loads(token, max_age=max_age)
        return data.get("uid")
    except BadSignature:
        return None
