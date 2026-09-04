import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def provisioning_uri(*, secret: str, username: str, issuer: str) -> str:
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


def _code(secret: str, counter: int) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_code(secret: str, code: str, *, now=None, window=1) -> bool:
    if not code or not code.isdigit() or len(code) != 6:
        return False
    counter = int(now or time.time()) // 30
    return any(hmac.compare_digest(_code(secret, counter + drift), code) for drift in range(-window, window + 1))
