from typing import Any

from sqlalchemy.orm import Session

from modules.drivers.models import Driver


class DriverRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: str) -> Driver | None:
        return self.db.query(Driver).filter(Driver.user_id == user_id).one_or_none()

    def get_by_id(self, driver_id: str) -> Driver | None:
        return self.db.query(Driver).filter(Driver.id == driver_id).one_or_none()

    def get_available_online_drivers(self, limit: int = 100) -> list[Driver]:
        return (
            self.db.query(Driver)
            .filter(
                Driver.verification_status.in_(("verified", "approved")),
                Driver.availability_status == "available",
                Driver.online_status.is_(True),
            )
            .order_by(Driver.rating.desc(), Driver.acceptance_rate.desc())
            .limit(limit)
            .all()
        )

    def create(self, user_id: str, data: dict[str, Any]) -> Driver:
        driver = Driver(user_id=user_id, **data)
        self.db.add(driver)
        self.db.commit()
        self.db.refresh(driver)
        return driver

    def update(self, driver: Driver, data: dict[str, Any]) -> Driver:
        for field, value in data.items():
            setattr(driver, field, value)
        self.db.commit()
        self.db.refresh(driver)
        return driver
