from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session, selectinload

from modules.students.models import Student, StudentFavouriteLocation, student_number_seq


class StudentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: str) -> Student | None:
        return (
            self.db.query(Student)
            .filter(Student.user_id == user_id)
            .one_or_none()
        )

    def get_by_user_id_with_favourites(self, user_id: str) -> Student | None:
        return (
            self.db.query(Student)
            .options(selectinload(Student.favourite_locations))
            .filter(Student.user_id == user_id)
            .one_or_none()
        )

    def generate_student_number(self) -> str:
        """Generate a unique student number in the form NMD-YYYY-NNNNN.

        Uses a PostgreSQL sequence in production for concurrency safety.
        Falls back to a count-based number for SQLite (test) environments.
        """
        year = datetime.now().year
        dialect_name = self.db.get_bind().dialect.name

        if dialect_name == "postgresql":
            try:
                next_value = self.db.scalar(select(func.next_value(student_number_seq)))
            except NoResultFound:
                next_value = 1
            return f"NMD-{year}-{int(next_value):05d}"

        # SQLite fallback for tests: not concurrency-safe, but sufficient for in-memory tests.
        count = self.db.scalar(select(func.count()).select_from(Student)) or 0
        return f"NMD-{year}-{count + 1:05d}"

    def create(self, user_id: str, data: dict[str, Any]) -> Student:
        payload = dict(data)
        if not payload.get("student_number"):
            payload["student_number"] = self.generate_student_number()
        student = Student(user_id=user_id, **payload)
        self.db.add(student)
        self.db.commit()
        self.db.refresh(student)
        return student

    def update(self, student: Student, data: dict[str, Any]) -> Student:
        for field, value in data.items():
            setattr(student, field, value)
        self.db.commit()
        self.db.refresh(student)
        return student

    def add_favourite_location(
        self, student: Student, data: dict[str, Any]
    ) -> StudentFavouriteLocation:
        location = StudentFavouriteLocation(student_id=student.id, **data)
        self.db.add(location)
        self.db.commit()
        self.db.refresh(location)
        return location

    def list_favourite_locations(self, student_id: str) -> list[StudentFavouriteLocation]:
        return (
            self.db.query(StudentFavouriteLocation)
            .filter(StudentFavouriteLocation.student_id == student_id)
            .order_by(StudentFavouriteLocation.created_at.desc())
            .all()
        )

    def get_favourite_location(
        self, student_id: str, location_id: str
    ) -> StudentFavouriteLocation | None:
        return (
            self.db.query(StudentFavouriteLocation)
            .filter(
                StudentFavouriteLocation.student_id == student_id,
                StudentFavouriteLocation.id == location_id,
            )
            .one_or_none()
        )

    def update_favourite_location(
        self, location: StudentFavouriteLocation, data: dict[str, Any]
    ) -> StudentFavouriteLocation:
        for field, value in data.items():
            setattr(location, field, value)
        self.db.commit()
        self.db.refresh(location)
        return location

    def delete_favourite_location(self, location: StudentFavouriteLocation) -> None:
        self.db.delete(location)
        self.db.commit()

    def get_ride_history(
        self, student: Student, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        bind = self.db.get_bind()
        inspector = inspect(bind)
        if not inspector.has_table("rides"):
            return []

        rides = Table("rides", MetaData(), autoload_with=bind)
        filter_column = self._ride_student_filter_column(rides)
        if filter_column is None:
            return []

        filter_value = student.id if filter_column.name == "student_id" else student.user_id
        query = select(rides).where(filter_column == filter_value).limit(limit).offset(offset)

        order_column = self._ride_order_column(rides)
        if order_column is not None:
            query = query.order_by(order_column.desc())

        result = self.db.execute(query)
        return [dict(row._mapping) for row in result]

    def _ride_student_filter_column(self, rides: Table):
        for column_name in ("student_id", "rider_user_id", "user_id"):
            if column_name in rides.c:
                return rides.c[column_name]
        return None

    def _ride_order_column(self, rides: Table):
        for column_name in ("requested_at", "created_at", "updated_at"):
            if column_name in rides.c:
                return rides.c[column_name]
        return None
