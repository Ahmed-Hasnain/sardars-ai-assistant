"""Password hashing and opaque bearer-token helpers."""

import hashlib
import hmac
import re
import secrets


SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 5
SCRYPT_MAXMEM = 64 * 1024 * 1024
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Enter a valid email address")
    return email


def validate_password(password: str) -> None:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError("Password must contain 12 to 128 characters")
    if len(password.encode("utf-8")) > 1024:
        raise ValueError("Password is too long")


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
        p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32,
    )


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = (encoded or "").split("$")
        if (algorithm, n, r, p) != (
            "scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P)
        ):
            raise ValueError("Unsupported password hash")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError("Invalid password hash")
    except ValueError:
        # Keep unknown users and malformed hashes on the same expensive path.
        _derive(password, bytes(16))
        return False
    return hmac.compare_digest(_derive(password, salt), expected)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()
