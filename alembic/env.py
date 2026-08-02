from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.database import Base, DATABASE_URL
from modules.drivers.models import Driver  # noqa: F401
from modules.kyc.models import KYCApplication, KYCDocument, KYCReview  # noqa: F401
from modules.payments.models import (  # noqa: F401
    DriverEarning,
    IdempotencyRecord,
    PaymentAuditLog,
    PlatformCommissionRule,
    ReconciliationReport,
    Refund,
    RidePayment,
    Transaction,
    Wallet,
)
from modules.rides.models import Ride  # noqa: F401
from modules.safety.models import EmergencyAlert, SafetyReport, TripShareToken  # noqa: F401
from modules.students.models import Student, StudentFavouriteLocation  # noqa: F401
from modules.users.models import UserProfile  # noqa: F401
from modules.vehicles.models import Vehicle  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    # Added "verification", "account", and "session" to your existing "user" exception
    ignored_tables = {"user", "verification", "account", "session"}
    return not (type_ == "table" and name in ignored_tables)


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
