"""Phone notifications (Web Push). Works on Android, and on iPhone once the app is on the Home Screen."""
import asyncio
import json
import logging

from pywebpush import WebPushException, webpush

from . import db
from .config import get_settings

log = logging.getLogger("upajna.push")


def enabled() -> bool:
    s = get_settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def _send(sub: dict, payload: str) -> None:
    s = get_settings()
    try:
        webpush(subscription_info=sub, data=payload, vapid_private_key=s.vapid_private_key, vapid_claims={"sub": s.vapid_subject})
    except WebPushException as e:
        if e.response is not None and e.response.status_code in (404, 410):
            db.remove_push_sub(sub["endpoint"])
        else:
            log.warning("push failed: %s", e)


async def notify(title: str, body: str, url: str = "/") -> None:
    if not enabled():
        return
    payload = json.dumps({"title": title, "body": body, "url": url})
    await asyncio.gather(*(asyncio.to_thread(_send, sub, payload) for sub in db.list_push_subs()))
