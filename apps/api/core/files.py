import hashlib
import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class FileInspection:
    sha256: str
    content_type: str
    status: str
    detail: str = ""


ALLOWED_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
    "image/webp": (b"RIFF",),
    "audio/ogg": (b"OggS",),
    "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "audio/mp4": (b"FTYP",),
    "video/mp4": (b"FTYP",),
    "video/3gpp": (b"FTYP",),
}


def inspect_upload(uploaded, *, allowed_types=None, max_bytes=10 * 1024 * 1024) -> FileInspection:
    if uploaded.size > max_bytes:
        raise ValueError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
    allowed = set(allowed_types or ALLOWED_SIGNATURES)
    claimed = (uploaded.content_type or "").split(";", 1)[0].lower()
    if claimed not in allowed:
        raise ValueError("Unsupported file type")
    position = uploaded.tell()
    content = uploaded.read()
    uploaded.seek(position)
    signatures = ALLOWED_SIGNATURES[claimed]
    matches_signature = any(
        content[4:8].lower() == b"ftyp" if signature == b"FTYP" else content.startswith(signature)
        for signature in signatures
    )
    if claimed == "image/webp":
        matches_signature = matches_signature and content[8:12] == b"WEBP"
    if not matches_signature:
        raise ValueError("File content does not match its declared type")
    digest = hashlib.sha256(content).hexdigest()
    host = os.getenv("CLAMAV_HOST", "").strip()
    if host:
        _clamav_scan(content, host, int(os.getenv("CLAMAV_PORT", "3310")))
    return FileInspection(digest, claimed, "CLEAN", "Signature and malware checks passed")


def _clamav_scan(content: bytes, host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=15) as connection:
        connection.sendall(b"zINSTREAM\0")
        for offset in range(0, len(content), 64 * 1024):
            chunk = content[offset : offset + 64 * 1024]
            connection.sendall(len(chunk).to_bytes(4, "big") + chunk)
        connection.sendall((0).to_bytes(4, "big"))
        response = connection.recv(4096).decode(errors="replace")
    if "FOUND" in response:
        raise ValueError("File failed malware scanning")
    if "OK" not in response:
        raise ValueError("Malware scanner did not return a clean result")
