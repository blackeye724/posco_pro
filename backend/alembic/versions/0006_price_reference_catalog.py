"""Store reusable reference unit prices for selective re-review."""

from alembic import op
import sqlalchemy as sa


revision = "0006_price_reference_catalog"
down_revision = "0005_preprocessing_retry_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "price_reference_catalog" not in inspector.get_table_names():
        op.create_table(
            "price_reference_catalog",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("source_file_id", sa.String(length=36), nullable=True),
            sa.Column("source_scope", sa.String(length=50), nullable=False, server_default="other_building_reference"),
            sa.Column("original_item", sa.String(length=500), nullable=True),
            sa.Column("standard_item", sa.String(length=500), nullable=True),
            sa.Column("specification", sa.Text(), nullable=True),
            sa.Column("unit", sa.String(length=30), nullable=True),
            sa.Column("building_label", sa.String(length=100), nullable=True),
            sa.Column("price", sa.Numeric(18, 2), nullable=True),
            sa.Column("reference_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provenance", sa.Text(), nullable=True),
            sa.Column("restriction", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
        )
    for name, column in (
        ("ix_price_reference_catalog_project_id", "project_id"),
        ("ix_price_reference_catalog_source_file_id", "source_file_id"),
        ("ix_price_reference_catalog_original_item", "original_item"),
        ("ix_price_reference_catalog_standard_item", "standard_item"),
        ("ix_price_reference_catalog_is_active", "is_active"),
    ):
        if name not in {index["name"] for index in sa.inspect(bind).get_indexes("price_reference_catalog")}:
            op.create_index(name, "price_reference_catalog", [column], unique=False)


def downgrade() -> None:
    op.drop_table("price_reference_catalog")
