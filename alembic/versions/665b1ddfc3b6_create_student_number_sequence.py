"""create_student_number_sequence

Revision ID: 665b1ddfc3b6
Revises: d6f16fd85e7c
Create Date: 2026-08-02 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '665b1ddfc3b6'
down_revision: Union[str, None] = 'd6f16fd85e7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS student_number_seq START 1"))


def downgrade() -> None:
    op.execute(sa.text("DROP SEQUENCE IF EXISTS student_number_seq"))
