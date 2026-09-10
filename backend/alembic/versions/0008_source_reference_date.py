"""Store the source document reference date used for review scope."""

from alembic import op
import sqlalchemy as sa


revision = "0008_source_reference_date"
down_revision = "0007_review_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("source_files")}
    if "reference_date" not in columns:
        op.add_column("source_files", sa.Column("reference_date", sa.DateTime(timezone=True), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("source_files")}
    if "ix_source_files_reference_date" not in indexes:
        op.create_index("ix_source_files_reference_date", "source_files", ["reference_date"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("source_files")}
    if "ix_source_files_reference_date" in indexes:
        op.drop_index("ix_source_files_reference_date", table_name="source_files")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("source_files")}
    if "reference_date" in columns:
        op.drop_column("source_files", "reference_date")
