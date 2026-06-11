from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.reminder import ReminderEvent
from app.repos.reminder_repo import reminder_repository
from app.services.settings_service import settings_service

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    body: str


class NotificationProvider:
    channel: str

    def is_configured(self) -> bool:
        raise NotImplementedError

    def send(self, message: NotificationMessage) -> bool:
        raise NotImplementedError


class PushDeerProvider(NotificationProvider):
    channel = "pushdeer"

    def is_configured(self) -> bool:
        return bool(settings.pushdeer_pushkey)

    def send(self, message: NotificationMessage) -> bool:
        payload = urllib.parse.urlencode(
            {
                "pushkey": settings.pushdeer_pushkey,
                "text": message.title,
                "desp": message.body,
                "type": "markdown",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            settings.pushdeer_endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return _post_request(request, provider_name="PushDeer")


class WeComWebhookProvider(NotificationProvider):
    channel = "wecom"

    def is_configured(self) -> bool:
        return bool(settings.wecom_webhook_url)

    def send(self, message: NotificationMessage) -> bool:
        payload = json.dumps(
            {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"**{message.title}**\n\n{message.body}",
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            settings.wecom_webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return _post_request(request, provider_name="WeCom webhook")


class ServerChanProvider(NotificationProvider):
    channel = "serverchan"

    def is_configured(self) -> bool:
        return bool(settings.serverchan_sendkey)

    def send(self, message: NotificationMessage) -> bool:
        endpoint_base = settings.serverchan_endpoint_base.rstrip("/")
        request = urllib.request.Request(
            f"{endpoint_base}/{settings.serverchan_sendkey}.send",
            data=urllib.parse.urlencode(
                {
                    "title": message.title,
                    "desp": message.body,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return _post_request(request, provider_name="ServerChan")


def _post_request(request: urllib.request.Request, *, provider_name: str) -> bool:
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.reminder_notification_timeout_seconds,
        ) as response:
            if 200 <= response.status < 300:
                return True
            logger.warning("%s notification returned HTTP %s", provider_name, response.status)
            return False
    except urllib.error.HTTPError as exc:
        logger.warning("%s notification failed with HTTP %s", provider_name, exc.code)
        return False
    except urllib.error.URLError as exc:
        logger.warning("%s notification failed: %s", provider_name, exc.reason)
        return False


class ReminderNotificationService:
    def __init__(self) -> None:
        self._providers: list[NotificationProvider] = [
            PushDeerProvider(),
            WeComWebhookProvider(),
            ServerChanProvider(),
        ]

    def provider_statuses(self) -> list[dict]:
        return [
            {"channel": provider.channel, "configured": provider.is_configured()}
            for provider in self._providers
        ]

    def send_test(self, channel: str) -> bool:
        provider = self._get_provider(channel)
        if provider is None or not provider.is_configured():
            return False
        return provider.send(
            NotificationMessage(
                title="MindMemo notification test",
                body="This is a one-time test message from MindMemo.",
            )
        )

    def dispatch_pending(self, db: Session, limit: int = 20) -> int:
        if not settings.reminder_notification_enabled:
            return 0

        configured_providers = [provider for provider in self._providers if provider.is_configured()]
        if not configured_providers:
            return 0

        sent_count = 0
        for reminder in reminder_repository.list_pending_delivery(db, limit=limit):
            message = self._build_message(reminder)
            delivered = False
            for provider in configured_providers:
                if not settings_service.user_allows_notify_channel(db, reminder.user_id, provider.channel):
                    continue
                delivered = provider.send(message) or delivered

            if delivered:
                reminder_repository.mark_sent(db, reminder, utcnow())
                sent_count += 1

        if sent_count > 0:
            db.commit()
        return sent_count

    def _build_message(self, reminder: ReminderEvent) -> NotificationMessage:
        body = reminder.message
        if reminder.due_at is not None:
            body = f"{body}\n\nDue at: {reminder.due_at.isoformat()}"
        return NotificationMessage(
            title=f"MindMemo reminder: {reminder.title}",
            body=body,
        )

    def _get_provider(self, channel: str) -> NotificationProvider | None:
        for provider in self._providers:
            if provider.channel == channel:
                return provider
        return None


reminder_notification_service = ReminderNotificationService()
