"""Raise the preprocessing automatic retry policy from two to five attempts."""

from alembic import op
import sqlalchemy as sa


revision = "0005_preprocessing_retry_policy"
down_revision = "0004_raw_preprocessing_and_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("preprocessing_runs")}
    if "max_attempts" not in columns:
        op.add_column("preprocessing_runs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"))
    if bind.dialect.name == "postgresql":
        op.alter_column("preprocessing_runs", "max_attempts", server_default="5")
    op.execute(sa.text("UPDATE preprocessing_runs SET max_attempts = 5 WHERE status IN ('queued', 'running') AND max_attempts < 5"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("preprocessing_runs", "max_attempts", server_default="2")
