"""Store immutable review result export snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0007_review_exports"
down_revision = "0006_price_reference_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "review_exports" not in inspector.get_table_names():
        op.create_table(
            "review_exports",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("requested_by", sa.String(length=36), nullable=True),
            sa.Column("review_run_id", sa.String(length=100), nullable=True),
            sa.Column("export_type", sa.String(length=40), nullable=False, server_default="review_bundle"),
            sa.Column("filter_snapshot", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("approval_snapshot", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("rule_version", sa.String(length=100), nullable=True),
            sa.Column("input_hash", sa.String(length=64), nullable=True),
            sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
            sa.Column("bundle_path", sa.Text(), nullable=True),
            sa.Column("xlsx_path", sa.Text(), nullable=True),
            sa.Column("pdf_path", sa.Text(), nullable=True),
            sa.Column("manifest_path", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("review_exports")}
    for name, column in (("ix_review_exports_project_id", "project_id"), ("ix_review_exports_review_run_id", "review_run_id"), ("ix_review_exports_input_hash", "input_hash"), ("ix_review_exports_status", "status")):
        if name not in indexes:
            op.create_index(name, "review_exports", [column], unique=False)


def downgrade() -> None:
    op.drop_table("review_exports")
