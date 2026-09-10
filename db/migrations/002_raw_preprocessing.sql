-- 원본 파일 기반 전처리 실행·내부 표준화 결과를 위한 확장.
-- 애플리케이션의 SQLAlchemy create_all과 함께 사용할 수 있는 멱등형 보조 마이그레이션이다.

CREATE TABLE IF NOT EXISTS preprocessing_runs (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    requested_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    source_kind VARCHAR(40) NOT NULL DEFAULT 'raw_upload',
    parser_version VARCHAR(40) NOT NULL DEFAULT 'raw-v1',
    input_hash VARCHAR(64) NOT NULL,
    source_file_ids TEXT NOT NULL DEFAULT '[]',
    source_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_preprocessing_runs_project_id ON preprocessing_runs(project_id);
CREATE INDEX IF NOT EXISTS ix_preprocessing_runs_input_hash ON preprocessing_runs(input_hash);

CREATE TABLE IF NOT EXISTS preprocessing_records (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES preprocessing_runs(id) ON DELETE CASCADE,
    source_file_id VARCHAR(36) REFERENCES source_files(id) ON DELETE SET NULL,
    item_kind VARCHAR(40) NOT NULL DEFAULT 'source',
    raw_payload TEXT NOT NULL,
    normalized_payload TEXT NOT NULL,
    source_locator VARCHAR(500),
    status VARCHAR(40) NOT NULL DEFAULT '생성',
    confidence VARCHAR(30) NOT NULL DEFAULT '중간',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_preprocessing_records_run_id ON preprocessing_records(run_id);
CREATE INDEX IF NOT EXISTS ix_preprocessing_records_source_file_id ON preprocessing_records(source_file_id);

CREATE TABLE IF NOT EXISTS preprocessing_artifacts (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES preprocessing_runs(id) ON DELETE CASCADE,
    artifact_type VARCHAR(50) NOT NULL,
    file_path TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_preprocessing_artifacts_run_id ON preprocessing_artifacts(run_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL,
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(80) NOT NULL,
    entity_id VARCHAR(100),
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_project_id ON audit_logs(project_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_entity_id ON audit_logs(entity_id);

ALTER TABLE IF EXISTS source_files ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE IF EXISTS source_files ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE IF EXISTS source_files ADD COLUMN IF NOT EXISTS delete_reason TEXT;

ALTER TABLE IF EXISTS preprocessing_runs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS preprocessing_runs ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 5;
ALTER TABLE IF EXISTS preprocessing_runs ALTER COLUMN max_attempts SET DEFAULT 5;
UPDATE preprocessing_runs SET max_attempts = 5 WHERE status IN ('queued', 'running') AND max_attempts < 5;

ALTER TABLE IF EXISTS approval_history ADD COLUMN IF NOT EXISTS override_sequence BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE IF EXISTS approval_history ADD COLUMN IF NOT EXISTS override_reason TEXT;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
