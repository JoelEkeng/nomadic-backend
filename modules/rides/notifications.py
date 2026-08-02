from typing import Protocol

from modules.rides.models import Ride


class RideNotificationPublisher(Protocol):
    def ride_requested(self, ride: Ride) -> None:
        pass

    def driver_assigned(self, ride: Ride) -> None:
        pass

    def ride_cancelled(self, ride: Ride) -> None:
        pass

    def ride_accepted(self, ride: Ride) -> None:
        pass

    def ride_started(self, ride: Ride) -> None:
        pass

    def ride_completed(self, ride: Ride) -> None:
        pass


class NoopRideNotificationPublisher:
    def ride_requested(self, ride: Ride) -> None:
        return None

    def driver_assigned(self, ride: Ride) -> None:
        return None

    def ride_cancelled(self, ride: Ride) -> None:
        return None

    def ride_accepted(self, ride: Ride) -> None:
        return None

    def ride_started(self, ride: Ride) -> None:
        return None

    def ride_completed(self, ride: Ride) -> None:
        return None
