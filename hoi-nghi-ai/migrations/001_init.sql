-- ============================================================================
-- Script tạo bảng — Hệ thống quản lý hội nghị khoa học có tích hợp AI
-- Dùng cho MySQL 8 / PostgreSQL. Với SQLite, SQLAlchemy tự tạo bảng khi khởi động.
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTO_INCREMENT,
    email               VARCHAR(255) NOT NULL UNIQUE,
    password_hash       VARCHAR(255) NOT NULL,
    full_name           VARCHAR(150) NOT NULL,
    role                VARCHAR(20)  NOT NULL DEFAULT 'author',   -- organizer | author | reviewer
    status              VARCHAR(20)  NOT NULL DEFAULT 'active',   -- active | locked
    failed_login_count  INTEGER      NOT NULL DEFAULT 0,
    locked_until        DATETIME     NULL,
    created_at          DATETIME     NULL
);

CREATE TABLE IF NOT EXISTS conferences (
    id                     INTEGER PRIMARY KEY AUTO_INCREMENT,
    name                   VARCHAR(200) NOT NULL,
    year                   INTEGER      NOT NULL,
    location               VARCHAR(200) DEFAULT '',
    description            TEXT,
    submission_deadline    DATE NOT NULL,
    review_deadline        DATE NOT NULL,
    notification_date      DATE NOT NULL,
    camera_ready_deadline  DATE NULL,
    status                 VARCHAR(20) NOT NULL DEFAULT 'open',
    created_by             INTEGER NULL,
    created_at             DATETIME NULL,
    CONSTRAINT fk_conf_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS expertise_fields (
    id          INTEGER PRIMARY KEY AUTO_INCREMENT,
    name        VARCHAR(150) NOT NULL UNIQUE,
    description VARCHAR(300) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS papers (
    id              INTEGER PRIMARY KEY AUTO_INCREMENT,
    conference_id   INTEGER NOT NULL,
    submitted_by    INTEGER NOT NULL,
    title           VARCHAR(400) NOT NULL,
    abstract        TEXT NOT NULL,
    file_path       VARCHAR(500) NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'submitted',
    submitted_at    DATETIME NULL,
    CONSTRAINT fk_paper_conf FOREIGN KEY (conference_id) REFERENCES conferences(id) ON DELETE CASCADE,
    CONSTRAINT fk_paper_user FOREIGN KEY (submitted_by)  REFERENCES users(id)       ON DELETE CASCADE,
    INDEX ix_paper_conf_status (conference_id, status)
);

CREATE TABLE IF NOT EXISTS paper_authors (
    id               INTEGER PRIMARY KEY AUTO_INCREMENT,
    paper_id         INTEGER NOT NULL,
    full_name        VARCHAR(150) NOT NULL,
    email            VARCHAR(255) NOT NULL,
    organization     VARCHAR(200) DEFAULT '',
    is_corresponding BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_pa_paper FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS paper_keywords (
    id       INTEGER PRIMARY KEY AUTO_INCREMENT,
    paper_id INTEGER NOT NULL,
    keyword  VARCHAR(120) NOT NULL,
    CONSTRAINT fk_pk_paper FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    CONSTRAINT uq_paper_keyword UNIQUE (paper_id, keyword)
);

CREATE TABLE IF NOT EXISTS paper_topics (
    id       INTEGER PRIMARY KEY AUTO_INCREMENT,
    paper_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    CONSTRAINT fk_pt_paper FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    CONSTRAINT fk_pt_field FOREIGN KEY (field_id) REFERENCES expertise_fields(id) ON DELETE CASCADE,
    CONSTRAINT uq_paper_topic UNIQUE (paper_id, field_id)
);

CREATE TABLE IF NOT EXISTS reviewer_profiles (
    id           INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id      INTEGER NOT NULL UNIQUE,
    degree       VARCHAR(50)  DEFAULT '',
    organization VARCHAR(200) DEFAULT '',
    max_load     INTEGER NOT NULL DEFAULT 5,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_rp_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reviewer_expertise (
    id                  INTEGER PRIMARY KEY AUTO_INCREMENT,
    reviewer_profile_id INTEGER NOT NULL,
    field_id            INTEGER NOT NULL,
    CONSTRAINT fk_re_profile FOREIGN KEY (reviewer_profile_id) REFERENCES reviewer_profiles(id) ON DELETE CASCADE,
    CONSTRAINT fk_re_field   FOREIGN KEY (field_id)            REFERENCES expertise_fields(id)   ON DELETE CASCADE,
    CONSTRAINT uq_reviewer_field UNIQUE (reviewer_profile_id, field_id)
);

CREATE TABLE IF NOT EXISTS assignments (
    id                  INTEGER PRIMARY KEY AUTO_INCREMENT,
    paper_id            INTEGER NOT NULL,
    reviewer_profile_id INTEGER NOT NULL,
    assigned_by         INTEGER NULL,
    due_date            DATE NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'assigned',
    created_at          DATETIME NULL,
    CONSTRAINT fk_as_paper    FOREIGN KEY (paper_id)            REFERENCES papers(id)            ON DELETE CASCADE,
    CONSTRAINT fk_as_reviewer FOREIGN KEY (reviewer_profile_id) REFERENCES reviewer_profiles(id) ON DELETE CASCADE,
    CONSTRAINT fk_as_user     FOREIGN KEY (assigned_by)         REFERENCES users(id)             ON DELETE SET NULL,
    CONSTRAINT uq_assignment_paper_reviewer UNIQUE (paper_id, reviewer_profile_id),
    INDEX ix_assignment_reviewer_status (reviewer_profile_id, status)
);

CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTO_INCREMENT,
    assignment_id   INTEGER NOT NULL UNIQUE,
    score           DOUBLE NOT NULL,
    recommendation  VARCHAR(20) NOT NULL,
    comment         TEXT NOT NULL,
    internal_note   TEXT,
    created_at      DATETIME NULL,
    CONSTRAINT fk_rv_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTO_INCREMENT,
    conference_id INTEGER NOT NULL,
    title         VARCHAR(200) NOT NULL,
    session_date  DATE NULL,
    start_time    TIME NULL,
    end_time      TIME NULL,
    room          VARCHAR(100) DEFAULT '',
    chair         VARCHAR(150) DEFAULT '',
    CONSTRAINT fk_ss_conf FOREIGN KEY (conference_id) REFERENCES conferences(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_papers (
    id          INTEGER PRIMARY KEY AUTO_INCREMENT,
    session_id  INTEGER NOT NULL,
    paper_id    INTEGER NOT NULL,
    order_index INTEGER DEFAULT 0,
    CONSTRAINT fk_sp_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    CONSTRAINT fk_sp_paper   FOREIGN KEY (paper_id)   REFERENCES papers(id)   ON DELETE CASCADE,
    CONSTRAINT uq_session_paper UNIQUE (session_id, paper_id)
);

CREATE TABLE IF NOT EXISTS registrations (
    id                INTEGER PRIMARY KEY AUTO_INCREMENT,
    conference_id     INTEGER NOT NULL,
    user_id           INTEGER NOT NULL,
    registration_type VARCHAR(20) NOT NULL DEFAULT 'listener',
    note              VARCHAR(300) DEFAULT '',
    created_at        DATETIME NULL,
    CONSTRAINT fk_rg_conf FOREIGN KEY (conference_id) REFERENCES conferences(id) ON DELETE CASCADE,
    CONSTRAINT fk_rg_user FOREIGN KEY (user_id)       REFERENCES users(id)       ON DELETE CASCADE,
    CONSTRAINT uq_registration_conf_user UNIQUE (conference_id, user_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id    INTEGER NOT NULL,
    kind       VARCHAR(30) NOT NULL DEFAULT 'assignment',
    title      VARCHAR(200) NOT NULL,
    message    TEXT NOT NULL,
    is_read    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NULL,
    CONSTRAINT fk_nt_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS email_templates (
    id               INTEGER PRIMARY KEY AUTO_INCREMENT,
    conference_id    INTEGER NOT NULL,
    kind             VARCHAR(30) NOT NULL,
    subject_template VARCHAR(300) NOT NULL,
    body_template    TEXT NOT NULL,
    signer           VARCHAR(150) DEFAULT 'Ban tổ chức hội nghị',
    CONSTRAINT fk_et_conf FOREIGN KEY (conference_id) REFERENCES conferences(id) ON DELETE CASCADE,
    CONSTRAINT uq_email_template_kind UNIQUE (conference_id, kind)
);

CREATE TABLE IF NOT EXISTS email_drafts (
    id             INTEGER PRIMARY KEY AUTO_INCREMENT,
    conference_id  INTEGER NOT NULL,
    paper_id       INTEGER NULL,
    assignment_id  INTEGER NULL,
    kind           VARCHAR(30) NOT NULL,
    subject        VARCHAR(300) NOT NULL,
    body           TEXT NOT NULL,
    missing_fields VARCHAR(300) DEFAULT '',
    source         VARCHAR(20) NOT NULL DEFAULT 'ai',
    status         VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_by     INTEGER NOT NULL,
    created_at     DATETIME NULL,
    CONSTRAINT fk_ed_conf FOREIGN KEY (conference_id) REFERENCES conferences(id) ON DELETE CASCADE,
    CONSTRAINT fk_ed_paper FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL,
    CONSTRAINT fk_ed_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_logs (
    id            INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id       INTEGER NOT NULL,
    kind          VARCHAR(30) NOT NULL,
    paper_id      INTEGER NULL,
    provider      VARCHAR(30) DEFAULT 'mock',
    model         VARCHAR(80) DEFAULT '',
    latency_ms    INTEGER DEFAULT 0,
    success       BOOLEAN NOT NULL DEFAULT TRUE,
    error_type    VARCHAR(40) NULL,
    error_message VARCHAR(500) NULL,
    created_at    DATETIME NULL,
    CONSTRAINT fk_al_user  FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    CONSTRAINT fk_al_paper FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ai_generations (
    id         INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id    INTEGER NOT NULL,
    paper_id   INTEGER NULL,
    kind       VARCHAR(30) NOT NULL,
    scope_key  VARCHAR(80) NOT NULL DEFAULT 'default',
    content    TEXT NOT NULL,
    source     VARCHAR(20) NOT NULL DEFAULT 'ai',
    bias_note  VARCHAR(500) DEFAULT '',
    created_at DATETIME NULL,
    updated_at DATETIME NULL,
    CONSTRAINT fk_ag_user  FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    CONSTRAINT fk_ag_paper FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    CONSTRAINT uq_ai_generation_scope UNIQUE (paper_id, kind, scope_key)
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id         INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id    INTEGER NOT NULL,
    token_hash VARCHAR(128) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    used_at    DATETIME NULL,
    created_at DATETIME NULL,
    CONSTRAINT fk_prt_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_logs (
    id         INTEGER PRIMARY KEY AUTO_INCREMENT,
    level      VARCHAR(20) DEFAULT 'error',
    source     VARCHAR(100) NULL,
    message    TEXT NOT NULL,
    created_at DATETIME NULL
);
