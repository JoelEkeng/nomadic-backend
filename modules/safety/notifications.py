"""Notification abstractions for the Safety module.

Designed for future integration with SMS, WhatsApp, Push, and Email providers.
Currently uses a Noop implementation that logs events for development.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EmergencyNotification:
    user_id: str
    user_name: str | None
    alert_id: str
    alert_type: str
    latitude: float | None
    longitude: float | None
    ride_id: str | None
    message: str | None


@dataclass
class TripShareNotification:
    user_id: str
    share_url: str
    ride_id: str


class SafetyNotificationService(ABC):
    """Abstract base for safety notifications."""

    @abstractmethod
    def notify_emergency(self, notification: EmergencyNotification) -> None:
        """Notify admins and emergency contacts about an emergency alert."""
        ...

    @abstractmethod
    def notify_emergency_contacts(self, notification: EmergencyNotification, contacts: list[str]) -> None:
        """Send emergency alert to user's emergency contacts via SMS/WhatsApp/Push."""
        ...

    @abstractmethod
    def notify_report_received(self, report_id: str, user_id: str) -> None:
        """Confirm to user that their safety report was received."""
        ...


class NoopSafetyNotificationService(SafetyNotificationService):
    """Development/logging implementation."""

    def notify_emergency(self, notification: EmergencyNotification) -> None:
        logger.warning(
            "EMERGENCY ALERT [%s] user=%s type=%s ride=%s lat=%s lng=%s msg=%s",
            notification.alert_id,
            notification.user_id,
            notification.alert_type,
            notification.ride_id,
            notification.latitude,
            notification.longitude,
            notification.message,
        )

    def notify_emergency_contacts(self, notification: EmergencyNotification, contacts: list[str]) -> None:
        logger.warning(
            "EMERGENCY CONTACTS NOTIFIED [%s] user=%s contacts=%s",
            notification.alert_id,
            notification.user_id,
            contacts,
        )

    def notify_report_received(self, report_id: str, user_id: str) -> None:
        logger.info(
            "SAFETY REPORT RECEIVED [%s] user=%s",
            report_id,
            user_id,
        )
