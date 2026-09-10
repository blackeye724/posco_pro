"""Store drawing source and revision metadata for the review UI."""

from alembic import op
import sqlalchemy as sa

revision = "0003_drawing_source_metadata"
down_revision = "0002_engine_jobs_and_price_raw_response"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("drawing_change_candidates")}
    for name, column in {
        "baseline_file": sa.Column("baseline_file", sa.Text(), nullable=True),
        "changed_file": sa.Column("changed_file", sa.Text(), nullable=True),
        "baseline_revision": sa.Column("baseline_revision", sa.String(length=100), nullable=True),
        "changed_revision": sa.Column("changed_revision", sa.String(length=100), nullable=True),
        "sheet_number": sa.Column("sheet_number", sa.String(length=100), nullable=True),
    }.items():
        if name not in columns:
            op.add_column("drawing_change_candidates", column)


def downgrade() -> None:
    for name in ("sheet_number", "changed_revision", "baseline_revision", "changed_file", "baseline_file"):
        op.drop_column("drawing_change_candidates", name)
