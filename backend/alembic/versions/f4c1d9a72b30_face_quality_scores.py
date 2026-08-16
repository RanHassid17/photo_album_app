"""face quality scores

Sharpness and frontality per detected face, so the people filter can show a clear,
front-on portrait instead of whichever crop the query happened to return first.

Revision ID: f4c1d9a72b30
Revises: c262da1734f8
Create Date: 2026-08-15 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f4c1d9a72b30'
down_revision: Union[str, None] = 'c262da1734f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: faces indexed before this migration have no measurement, and an
    # unmeasured face must not be read as a bad one.
    op.add_column('face_embeddings', sa.Column('sharpness', sa.Float(), nullable=True))
    op.add_column('face_embeddings', sa.Column('frontality', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('face_embeddings', 'frontality')
    op.drop_column('face_embeddings', 'sharpness')
