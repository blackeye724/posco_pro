"""Persist review context for changed-material price candidates."""

from alembic import op
import sqlalchemy as sa


revision = "0009_price_result_review_context"
down_revision = "0008_source_reference_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("procurement_price_results")}
    additions = (
        ("source_set", sa.String(length=50)),
        ("work_package", sa.String(length=100)),
        ("baseline_quantity", sa.String(length=100)),
        ("changed_quantity", sa.String(length=100)),
        ("difference", sa.String(length=100)),
        ("evidence", sa.Text()),
    )
    for name, column_type in additions:
        if name not in columns:
            op.add_column("procurement_price_results", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in ("evidence", "difference", "changed_quantity", "baseline_quantity", "work_package", "source_set"):
        op.drop_column("procurement_price_results", name)
