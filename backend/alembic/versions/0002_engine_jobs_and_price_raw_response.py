"""Add asynchronous rule jobs and stored price lookup response metadata."""

from alembic import op
import sqlalchemy as sa

revision = "0002_engine_jobs_and_price_raw_response"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Alembic creates ``alembic_version.version_num`` as VARCHAR(32) by
    # default, but this revision identifier is longer than 32 characters.
    # PostgreSQL enforces that limit when Alembic records the new revision,
    # so widen it before the migration completes. SQLite does not enforce the
    # declared VARCHAR length and needs no equivalent operation.
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
    # Create the new table from the declarative model, then add the column to
    # databases that already applied 0001.
    from app.database import Base
    Base.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("procurement_price_results")}
    if "raw_response" not in columns:
        op.add_column("procurement_price_results", sa.Column("raw_response", sa.Text(), nullable=True))
    if "review_decisions" in inspector.get_table_names():
        # 이전 MVP의 승인 이력을 새 프로젝트별 이력 테이블로 보존한다.
        op.execute(sa.text("""
            INSERT INTO approval_history
                (id, project_id, source_id, department, decision, comment, reviewer, reviewer_user_id, evidence_ref, created_at, updated_at)
            SELECT id, NULL, source_id, department, decision, comment, reviewer, NULL, evidence_ref, created_at, created_at
            FROM review_decisions old
            WHERE NOT EXISTS (SELECT 1 FROM approval_history current WHERE current.id = old.id)
        """))


def downgrade() -> None:
    op.drop_column("procurement_price_results", "raw_response")
    op.drop_table("rule_run_jobs")
