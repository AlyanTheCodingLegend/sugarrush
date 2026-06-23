from __future__ import annotations
import logging
import time

import requests

from app.config import WA_TOKEN, WA_PHONE_NUMBER_ID

logger = logging.getLogger(__name__)

MAX_CHUNK = 1500
_GRAPH_URL = "https://graph.facebook.com/v20.0/{phone_number_id}/messages"


def chunk(text: str, size: int = MAX_CHUNK) -> list[str]:
    """Split text into ≤size char chunks on line/sentence boundaries."""
    if len(text) <= size:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= size:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, size)
        if cut <= 0:
            cut = remaining.rfind(". ", 0, size)
            if cut <= 0:
                cut = size
            else:
                cut += 1
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [p for p in parts if p]


def send_whatsapp(to: str, text: str) -> None:
    if not (WA_TOKEN and WA_PHONE_NUMBER_ID):
        logger.warning("Meta WhatsApp not configured — cannot send message")
        return

    # Meta expects bare E.164 number, no "whatsapp:" prefix
    recipient = to.replace("whatsapp:", "").lstrip("+")
    url = _GRAPH_URL.format(phone_number_id=WA_PHONE_NUMBER_ID)
    headers = {
        "Authorization": f"Bearer {WA_TOKEN}",
        "Content-Type": "application/json",
    }

    chunks = chunk(text)
    logger.info("Sending %d chunk(s) to %s", len(chunks), to)

    for i, part in enumerate(chunks):
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": part},
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            r.raise_for_status()
            msg_id = r.json().get("messages", [{}])[0].get("id", "?")
            logger.info("Sent chunk %d/%d: message_id=%s", i + 1, len(chunks), msg_id)
        except Exception as exc:
            logger.error("Failed to send chunk %d: %s. Retrying once.", i + 1, exc)
            try:
                time.sleep(2)
                r = requests.post(url, json=payload, headers=headers, timeout=10)
                r.raise_for_status()
            except Exception as exc2:
                logger.error("Retry also failed for chunk %d: %s", i + 1, exc2)
        if i < len(chunks) - 1:
            time.sleep(0.5)
