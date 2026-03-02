"""merge_orch_chat_and_guardrail_branches

Revision ID: b2d65b9595aa
Revises: j7k8l9m0n1o2, l9a0b1c2d3e4
Create Date: 2026-02-23 17:27:33.526504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'b2d65b9595aa'
down_revision: Union[str, None] = ('j7k8l9m0n1o2', 'l9a0b1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
