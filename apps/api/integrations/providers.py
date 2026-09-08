import json
import os
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(frozen=True)
class ProviderResult:
    message_id: str
    thread_id: str
    status: str
    metadata: dict | None = None


def request_json(url, *, method="GET", token="", payload=None, headers=None, timeout=20):
    body = json.dumps(payload).encode() if payload is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, data=body, method=method, headers=request_headers), timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"Provider HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Provider connection failed: {exc.reason}") from exc


def download_binary(url, *, token="", max_bytes=10 * 1024 * 1024, timeout=20):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            declared_size = int(response.headers.get("Content-Length", "0") or 0)
            if declared_size > max_bytes:
                raise RuntimeError("Provider media exceeds the 10 MB limit")
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise RuntimeError("Provider media exceeds the 10 MB limit")
            return content, response.headers.get_content_type()
    except HTTPError as exc:
        raise RuntimeError(f"Provider media download failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Provider media download failed: {exc.reason}") from exc


class MessageProvider(ABC):
    @abstractmethod
    def send(self, *, recipient, subject, body, idempotency_key, options=None): ...


class FakeMessageProvider(MessageProvider):
    def __init__(self, channel):
        self.channel = channel

    def send(self, *, recipient, subject, body, idempotency_key, options=None):
        stable = idempotency_key.replace(":", "-")[:80]
        return ProviderResult(
            message_id=f"fake-{self.channel.lower()}-{stable}-{uuid4().hex[:8]}",
            thread_id=f"fake-thread-{stable}",
            status="SENT",
            metadata={
                "template_name": (options or {}).get("template_name", ""),
                "has_document": bool((options or {}).get("document")),
                "quick_reply_count": len((options or {}).get("quick_reply_payloads", [])),
                "url_button_count": len((options or {}).get("url_button_parameters", [])),
            },
        )


class SMTPProvider(MessageProvider):
    def __init__(
        self,
        *,
        host,
        port,
        username="",
        password="",
        from_email="",
        from_name="",
        reply_to="",
        use_tls=True,
        use_ssl=False,
        timeout=20,
    ):
        if not host or not from_email:
            raise RuntimeError("SMTP is disconnected")
        if use_tls and use_ssl:
            raise RuntimeError("SMTP STARTTLS and implicit SSL cannot both be enabled")
        if bool(username) != bool(password):
            raise RuntimeError("SMTP username and password must be configured together")
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = (from_name or "").strip()
        self.reply_to = (reply_to or "").strip()
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = int(timeout)

    def send(self, *, recipient, subject, body, idempotency_key, options=None):
        options = options or {}
        message = EmailMessage()
        message["From"] = (
            formataddr((self.from_name, self.from_email)) if self.from_name else self.from_email
        )
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = make_msgid()
        # A missing Date header costs real spam points with strict filters.
        message["Date"] = formatdate(localtime=True)
        message["Auto-Submitted"] = "auto-generated"
        message["X-Drona-Idempotency-Key"] = idempotency_key
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        message.set_content(body)
        html_body = options.get("html_body")
        if html_body:
            # multipart/alternative: clients that cannot render HTML keep the text part.
            message.add_alternative(html_body, subtype="html")
        client_class = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
        kwargs = {"host": self.host, "port": self.port, "timeout": self.timeout}
        if self.use_ssl:
            kwargs["context"] = ssl.create_default_context()
        try:
            with client_class(**kwargs) as client:
                client.ehlo()
                if self.use_tls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if self.username:
                    client.login(self.username, self.password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise RuntimeError(f"SMTP delivery failed: {exc}") from exc
        return ProviderResult(
            message_id=str(message["Message-ID"]).strip("<>"),
            thread_id="",
            status="SENT",
            metadata={
                "host": self.host,
                "port": self.port,
                "security": "SSL" if self.use_ssl else "STARTTLS" if self.use_tls else "PLAIN",
            },
        )


class WhatsAppProvider(MessageProvider):
    def __init__(self, *, access_token, phone_number_id, api_version="v23.0"):
        if not access_token or not phone_number_id:
            raise RuntimeError("WhatsApp is disconnected")
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version

    def _upload_document(self, document):
        boundary = f"----DronaWhatsApp{uuid4().hex}"
        lines = []
        for name, value in {"messaging_product": "whatsapp", "type": document["content_type"]}.items():
            lines.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ])
        lines.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{document["filename"]}"\r\n'.encode(),
            f'Content-Type: {document["content_type"]}\r\n\r\n'.encode(),
            document["content"],
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        request = Request(
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/media",
            data=b"".join(lines),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode() or "{}")
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1000]
            raise RuntimeError(f"WhatsApp media upload HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"WhatsApp media upload failed: {exc.reason}") from exc
        if not result.get("id"):
            raise RuntimeError("WhatsApp media upload did not return a media ID")
        return result["id"]

    def send(self, *, recipient, subject, body, idempotency_key, options=None):
        options = options or {}
        template = str(options.get("template_name") or os.getenv("WHATSAPP_TEMPLATE_NAME", "")).strip()
        if template:
            components = []
            document = options.get("document")
            if document:
                media_id = self._upload_document(document)
                components.append({
                    "type": "header",
                    "parameters": [{
                        "type": "document",
                        "document": {"id": media_id, "filename": document["filename"]},
                    }],
                })
            parameters = options.get("body_parameters") or [body[:1024]]
            if parameters:
                components.append({
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(value)[:1024]} for value in parameters],
                })
            for index, payload in enumerate(options.get("quick_reply_payloads") or []):
                components.append({
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(index),
                    "parameters": [{"type": "payload", "payload": str(payload)}],
                })
            for index, value in enumerate(options.get("url_button_parameters") or []):
                components.append({
                    "type": "button",
                    "sub_type": "url",
                    "index": str(index),
                    "parameters": [{"type": "text", "text": str(value)[:2000]}],
                })
            # Authentication templates expose their copy-code button as a URL button
            # whose link embeds {{1}} (.../otp/code/?otp_type=COPY_CODE&code=otp{{1}}), so
            # the send MUST carry a matching button component or Meta rejects it with
            # 132000. The sub_type is "url", not "copy_code" - the latter takes a
            # coupon_code parameter and belongs to marketing coupon templates.
            otp_button_type = str(options.get("otp_button_type") or "none").lower()
            if otp_button_type == "url":
                components.append({
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": str(options.get("otp_button_code", ""))}],
                })
            content = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": str(options.get("template_language") or os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en"))},
                    "components": components,
                },
            }
        else:
            # Business-initiated free-form messages are rejected by Meta outside a
            # 24-hour service window, so fail loudly instead of queueing silent failures.
            raise RuntimeError(
                "WhatsApp requires an approved template name; set WHATSAPP_TEMPLATE_NAME or pass template_name"
            )
        result = request_json(
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages",
            method="POST",
            token=self.access_token,
            payload=content,
        )
        message_id = result.get("messages", [{}])[0].get("id", "")
        if not message_id:
            raise RuntimeError("WhatsApp did not return a message ID")
        return ProviderResult(message_id=message_id, thread_id=recipient, status="SENT", metadata=result)
