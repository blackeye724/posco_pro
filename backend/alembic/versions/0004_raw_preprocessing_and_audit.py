"""Add raw-upload preprocessing run tables and logical-delete audit metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0004_raw_preprocessing_and_audit"
down_revision = "0003_drawing_source_metadata"
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector, table: str, name: str) -> bool:
    return any(column["name"] == name for column in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "preprocessing_runs"):
        op.create_table(
            "preprocessing_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_kind", sa.String(length=40), nullable=False, server_default="raw_upload"),
            sa.Column("parser_version", sa.String(length=40), nullable=False, server_default="raw-v1"),
            sa.Column("input_hash", sa.String(length=64), nullable=False),
            sa.Column("source_file_ids", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_preprocessing_runs_project_id", "preprocessing_runs", ["project_id"])
        op.create_index("ix_preprocessing_runs_input_hash", "preprocessing_runs", ["input_hash"])
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "preprocessing_records"):
        op.create_table(
            "preprocessing_records",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("preprocessing_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_file_id", sa.String(length=36), sa.ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True),
            sa.Column("item_kind", sa.String(length=40), nullable=False, server_default="source"),
            sa.Column("raw_payload", sa.Text(), nullable=False),
            sa.Column("normalized_payload", sa.Text(), nullable=False),
            sa.Column("source_locator", sa.String(length=500), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="생성"),
            sa.Column("confidence", sa.String(length=30), nullable=False, server_default="중간"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_preprocessing_records_run_id", "preprocessing_records", ["run_id"])
        op.create_index("ix_preprocessing_records_source_file_id", "preprocessing_records", ["source_file_id"])
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "preprocessing_artifacts"):
        op.create_table(
            "preprocessing_artifacts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("preprocessing_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("artifact_type", sa.String(length=50), nullable=False),
            sa.Column("file_path", sa.Text(), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_preprocessing_artifacts_run_id", "preprocessing_artifacts", ["run_id"])
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("entity_type", sa.String(length=80), nullable=False),
            sa.Column("entity_id", sa.String(length=100), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
        op.create_index("ix_audit_logs_project_id", "audit_logs", ["project_id"])
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
        op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    inspector = sa.inspect(bind)
    for name, column in {
        "deleted_at": sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        "deleted_by": sa.Column("deleted_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        "delete_reason": sa.Column("delete_reason", sa.Text(), nullable=True),
    }.items():
        if not _has_column(inspector, "source_files", name):
            op.add_column("source_files", column)
    inspector = sa.inspect(bind)
    for name, column in {
        "override_sequence": sa.Column("override_sequence", sa.Boolean(), nullable=False, server_default=sa.false()),
        "override_reason": sa.Column("override_reason", sa.Text(), nullable=True),
    }.items():
        if not _has_column(inspector, "approval_history", name):
            op.add_column("approval_history", column)
    inspector = sa.inspect(bind)
    for name, column in {
        "password_hash": sa.Column("password_hash", sa.Text(), nullable=True),
        "must_change_password": sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.true()),
    }.items():
        if not _has_column(inspector, "users", name):
            op.add_column("users", column)
    inspector = sa.inspect(bind)
    for name, column in {
        "attempt_count": sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        "max_attempts": sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
    }.items():
        if not _has_column(inspector, "preprocessing_runs", name):
            op.add_column("preprocessing_runs", column)


def downgrade() -> None:
    op.drop_column("source_files", "delete_reason")
    op.drop_column("source_files", "deleted_by")
    op.drop_column("source_files", "deleted_at")
    op.drop_table("audit_logs")
    op.drop_table("preprocessing_artifacts")
    op.drop_table("preprocessing_records")
    op.drop_table("preprocessing_runs")
