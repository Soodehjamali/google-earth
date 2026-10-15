"""Notification Provider Interface, Registry, and Outbound Safety Lock.

CRITICAL SAFETY REQUIREMENT:
When phenological frost thresholds are unverified (thresholds_verified=False),
outbound dispatch of real notifications (SMS, Telegram, webhook, email) to growers
is strictly BLOCKED by an automated safety lock to prevent false-alarm panics
or spamming farmers with placeholder data. Only Stub/Dry-run delivery is permitted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class NotificationDispatchError(Exception):
    """Base exception for notification dispatch failures."""
    pass


class UnverifiedThresholdsSafetyLockError(NotificationDispatchError):
    """Raised when an attempt is made to dispatch real alerts with unverified thresholds."""
    pass


@dataclass
class NotificationResult:
    """Result of an attempted notification dispatch."""

    success: bool
    status: str                         # "sent", "dry_run", "blocked_unverified", "failed"
    channel: str
    recipient: str
    dispatched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "channel": self.channel,
            "recipient": self.recipient,
            "dispatched_at": self.dispatched_at,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class NotificationProvider(ABC):
    """Abstract interface for multi-channel notification dispatchers."""

    @property
    @abstractmethod
    def is_real_network_provider(self) -> bool:
        """True if this provider makes real external network calls."""
        pass

    @abstractmethod
    async def send_alert(
        self,
        recipient: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        """Dispatch notification alert to the recipient."""
        pass


def mask_recipient(recipient: str) -> str:
    """Mask phone numbers or emails to prevent PII leakage into plain logs."""
    if not recipient:
        return ""
    if "@" in recipient:
        parts = recipient.split("@", 1)
        user = parts[0]
        domain = parts[1]
        masked_user = user[:2] + "***" if len(user) > 2 else "***"
        return f"{masked_user}@{domain}"
    clean = recipient.strip()
    if len(clean) > 6:
        return f"{clean[:4]}***{clean[-2:]}"
    return "***"


class StubNotificationProvider(NotificationProvider):
    """Default stub notification provider.

    Logs message to application logs, never makes external HTTP/network calls,
    and stores sent records in an internal memory list for test verification.
    """

    def __init__(self, channel_name: str = "stub"):
        self.channel_name = channel_name
        self.recorded_dispatches: List[Dict[str, Any]] = []

    @property
    def is_real_network_provider(self) -> bool:
        return False

    async def send_alert(
        self,
        recipient: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        meta = metadata or {}
        record = {
            "recipient": recipient,
            "message": message,
            "channel": self.channel_name,
            "metadata": meta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.recorded_dispatches.append(record)
        logger.info(
            "[STUB NOTIFICATION] channel=%s recipient=%s message_len=%d",
            self.channel_name,
            mask_recipient(recipient),
            len(message),
        )
        return NotificationResult(
            success=True,
            status="dry_run",
            channel=self.channel_name,
            recipient=recipient,
            metadata=meta,
        )


class MockLiveNetworkNotificationProvider(NotificationProvider):
    """Simulated real network provider for testing the outbound safety lock."""

    def __init__(self, channel_name: str = "live_network"):
        self.channel_name = channel_name
        self.sent_count = 0

    @property
    def is_real_network_provider(self) -> bool:
        return True

    async def send_alert(
        self,
        recipient: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        self.sent_count += 1
        return NotificationResult(
            success=True,
            status="sent",
            channel=self.channel_name,
            recipient=recipient,
            metadata=metadata or {},
        )


class NotificationProviderRegistry:
    """Registry managing available notification providers per channel."""

    def __init__(self):
        self._providers: Dict[str, NotificationProvider] = {}
        # Default all channels to safe Stubs
        self.register("sms", StubNotificationProvider("sms"))
        self.register("telegram", StubNotificationProvider("telegram"))
        self.register("webhook", StubNotificationProvider("webhook"))
        self.register("email", StubNotificationProvider("email"))
        self.register("stub", StubNotificationProvider("stub"))

    def register(self, channel: str, provider: NotificationProvider) -> None:
        self._providers[channel.lower()] = provider

    def get(self, channel: str) -> NotificationProvider:
        ch = channel.lower()
        if ch not in self._providers:
            # Fallback to stub for unknown channels
            logger.warning("Unregistered notification channel '%s', falling back to Stub", channel)
            return StubNotificationProvider(channel)
        return self._providers[ch]


default_notification_registry = NotificationProviderRegistry()


async def dispatch_alert_with_safety_lock(
    channel: str,
    recipient: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
    thresholds_verified: bool = False,
    admin_override: bool = False,
    force_dry_run: bool = False,
    registry: Optional[NotificationProviderRegistry] = None,
) -> NotificationResult:
    """Dispatch alert while enforcing the outbound safety lock.

    SAFETY RULES:
    1. If ``thresholds_verified is False`` and ``admin_override is False``:
       - Real network providers are STRICTLY FORBIDDEN from dispatching live alerts.
       - If a real network provider is targeted and ``force_dry_run`` is False,
         an ``UnverifiedThresholdsSafetyLockError`` is raised (or handled to record
         status as ``blocked_unverified``).
       - Stub providers and dry-run dispatches are permitted.
    2. If ``admin_override is True`` or ``thresholds_verified is True``:
       - Real network providers may dispatch live alerts.
    3. If ``force_dry_run is True``:
       - Always dispatches through stub logic or flags status as ``dry_run``.
    """
    reg = registry or default_notification_registry
    provider = reg.get(channel)
    meta = metadata or {}

    # Check Outbound Safety Lock
    if not thresholds_verified and not admin_override:
        if provider.is_real_network_provider and not force_dry_run:
            msg = (
                f"SAFETY LOCK REFUSAL: Cannot dispatch real outbound notification via channel '{channel}' "
                f"to recipient '{mask_recipient(recipient)}' because phenological frost thresholds are UNVERIFIED "
                "(thresholds_verified=False). Only stub/dry-run mode is permitted until an agronomist verifies thresholds, "
                "or explicit admin_override is enabled."
            )
            logger.error(msg)
            raise UnverifiedThresholdsSafetyLockError(msg)

    # If force_dry_run is requested on a real provider, route to safe stub instead
    if force_dry_run and provider.is_real_network_provider:
        stub = StubNotificationProvider(channel)
        res = await stub.send_alert(recipient, message, meta)
        res.status = "dry_run"
        return res

    return await provider.send_alert(recipient, message, meta)
