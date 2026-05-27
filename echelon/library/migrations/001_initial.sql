-- =============================================================================
-- Echelon V14 初始迁移 — 统一论文库 DDL
-- 文件: 001_initial.sql
-- 适用: SQLite Pilot(可直接 cat 到 SQLite)
-- Postgres 切换: 参见注释标有 [POSTGRES] 的行
-- =============================================================================

-- [NOTE] SQLite 不支持 JSONB,用 TEXT 存储 JSON 字符串
-- [NOTE] SQLite 不支持 TIMESTAMPTZ,用 TEXT 存储 UTC ISO8601
-- [NOTE] ULID 主键用 TEXT(26 字符 Crockford base32)

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- -----------------------------------------------------------------------------
-- 主表: papers
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS papers (
    id                      TEXT PRIMARY KEY,           -- ULID 内部 ID
    openalex_id             TEXT UNIQUE,                -- W4392199370
    doi                     TEXT UNIQUE,                -- 10.xxxx/xxxx(已规范化)
    arxiv_id                TEXT UNIQUE,                -- 2401.12345
    pmid                    INTEGER UNIQUE,             -- PubMed ID(future)
    title                   TEXT NOT NULL,
    abstract                TEXT,
    publication_date        TEXT NOT NULL,              -- YYYY-MM-DD
    n_authors               INTEGER,
    cited_by_count          INTEGER,
    primary_topic_id        TEXT,                       -- T10245
    primary_subfield_id     TEXT,                       -- S3107
    primary_field_id        TEXT,                       -- F22
    primary_domain_id       TEXT,                       -- D3
    venue_id                TEXT,                       -- V21034
    is_retracted            INTEGER DEFAULT 0,          -- BOOLEAN(0/1)
    is_paratext             INTEGER DEFAULT 0,
    language                TEXT,
    open_access             TEXT,                       -- JSON TEXT [POSTGRES: JSONB]
    raw_jsonb               TEXT,                       -- 完整原始 JSON [POSTGRES: JSONB]
    first_ingested_at       TEXT,                       -- TIMESTAMPTZ
    last_refreshed_at       TEXT,
    source_provider         TEXT,                       -- 'openalex'|'arxiv'|'biorxiv'|'crossref'
    ingestion_job_id        TEXT                        -- ULID -> ingestion_jobs.job_id
);

CREATE INDEX IF NOT EXISTS idx_papers_topic        ON papers(primary_topic_id);
CREATE INDEX IF NOT EXISTS idx_papers_date         ON papers(publication_date);
CREATE INDEX IF NOT EXISTS idx_papers_field        ON papers(primary_field_id);
CREATE INDEX IF NOT EXISTS idx_papers_provider     ON papers(source_provider);
CREATE INDEX IF NOT EXISTS idx_papers_retracted    ON papers(is_retracted)
    WHERE is_retracted = 1;                             -- [POSTGRES: WHERE is_retracted = TRUE]

-- [POSTGRES 补充索引]:
-- CREATE INDEX CONCURRENTLY idx_papers_raw_jsonb ON papers USING GIN(raw_jsonb);
-- CREATE INDEX CONCURRENTLY idx_papers_title_fts
--     ON papers USING GIN(to_tsvector('english', title));

-- -----------------------------------------------------------------------------
-- 引用关系: paper_references (AUDIT-053 独立纵表)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_references (
    citing_paper_id         TEXT NOT NULL,              -- ULID -> papers.id
    cited_paper_id_external TEXT NOT NULL,              -- W ID 字符串(可能不在 papers 表)
    cited_paper_id_internal TEXT,                       -- ULID(若 papers 表里有则填)
    PRIMARY KEY (citing_paper_id, cited_paper_id_external)
);

CREATE INDEX IF NOT EXISTS idx_paper_refs_citing   ON paper_references(citing_paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_refs_cited_ext ON paper_references(cited_paper_id_external);
CREATE INDEX IF NOT EXISTS idx_paper_refs_cited_int ON paper_references(cited_paper_id_internal)
    WHERE cited_paper_id_internal IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 作者: authors
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS authors (
    id                      TEXT PRIMARY KEY,           -- ULID
    openalex_id             TEXT UNIQUE,
    orcid                   TEXT,
    display_name            TEXT,
    h_index                 INTEGER,
    works_count             INTEGER
);

CREATE INDEX IF NOT EXISTS idx_authors_openalex    ON authors(openalex_id);
CREATE INDEX IF NOT EXISTS idx_authors_name        ON authors(display_name);

-- -----------------------------------------------------------------------------
-- 论文-作者关联: paper_authors
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id                TEXT NOT NULL,              -- ULID -> papers.id
    author_id               TEXT NOT NULL,              -- ULID -> authors.id
    author_position         INTEGER DEFAULT 0,          -- 0-indexed
    affiliation_id          TEXT,                       -- ULID -> affiliations.id
    PRIMARY KEY (paper_id, author_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_authors_paper  ON paper_authors(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_authors_author ON paper_authors(author_id);

-- -----------------------------------------------------------------------------
-- 机构: affiliations
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS affiliations (
    id                      TEXT PRIMARY KEY,           -- ULID
    openalex_id             TEXT UNIQUE,
    display_name            TEXT,
    country_code            TEXT,
    ror_id                  TEXT
);

-- -----------------------------------------------------------------------------
-- 学科层级: topics_hierarchy (AUDIT-024 完整 4 级)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS topics_hierarchy (
    topic_id                TEXT PRIMARY KEY,           -- T10245
    topic_name              TEXT,
    subfield_id             TEXT,
    subfield_name           TEXT,
    field_id                TEXT,
    field_name              TEXT,
    domain_id               TEXT,
    domain_name             TEXT,
    works_count             INTEGER,
    last_synced_at          TEXT                        -- TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_topics_field         ON topics_hierarchy(field_id);
CREATE INDEX IF NOT EXISTS idx_topics_domain        ON topics_hierarchy(domain_id);

-- -----------------------------------------------------------------------------
-- PDF 库: pdfs
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pdfs (
    paper_id                TEXT PRIMARY KEY,           -- ULID -> papers.id
    storage_uri             TEXT NOT NULL,              -- s3://... 或本地路径
    source_url              TEXT,
    license                 TEXT,                       -- 'cc-by'|'cc-by-nc'|'restricted'
    size_bytes              INTEGER,
    sha256                  TEXT,
    downloaded_at           TEXT,                       -- TIMESTAMPTZ
    parser_compat_hash      TEXT                        -- AUDIT-032
);

CREATE INDEX IF NOT EXISTS idx_pdfs_sha256          ON pdfs(sha256)
    WHERE sha256 IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 撤稿监控: retractions
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retractions (
    paper_id                TEXT PRIMARY KEY,           -- ULID -> papers.id
    retracted_at            TEXT,                       -- DATE
    reason                  TEXT,
    source                  TEXT,                       -- 'retraction_watch'|'crossref'
    detected_at             TEXT                        -- TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- 摄入任务: ingestion_jobs (Outbox 模式 + 状态追踪)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id                  TEXT PRIMARY KEY,           -- ULID
    provider                TEXT NOT NULL,              -- 'openalex'|'arxiv'|...
    query_params            TEXT,                       -- JSON TEXT [POSTGRES: JSONB]
    status                  TEXT DEFAULT 'pending',     -- 'pending'|'running'|'done'|'failed'
    started_at              TEXT,                       -- TIMESTAMPTZ
    finished_at             TEXT,
    papers_ingested         INTEGER DEFAULT 0,
    papers_skipped_duplicate INTEGER DEFAULT 0,
    error_log               TEXT,
    parent_job_id           TEXT                        -- ULID -> ingestion_jobs.job_id
);

CREATE INDEX IF NOT EXISTS idx_jobs_status          ON ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_provider        ON ingestion_jobs(provider);
CREATE INDEX IF NOT EXISTS idx_jobs_started         ON ingestion_jobs(started_at);

-- -----------------------------------------------------------------------------
-- 摄入高水位: ingestion_hwm (继承 V13 hwm.py)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_hwm (
    provider                TEXT NOT NULL,
    topic_id                TEXT NOT NULL DEFAULT '',
    last_processed_date     TEXT,                       -- DATE
    last_cursor             TEXT,                       -- OAI-PMH resumptionToken 或 cursor
    updated_at              TEXT,                       -- TIMESTAMPTZ
    PRIMARY KEY (provider, topic_id)
);

-- =============================================================================
-- [POSTGRES 切换 checklist]:
-- 1. 将 TEXT 类型的 JSON 字段改为 JSONB
-- 2. 将 INTEGER BOOLEAN 改为 BOOLEAN
-- 3. 将 TEXT 日期字段改为 DATE / TIMESTAMPTZ
-- 4. 移除 WHERE 条件索引(SQLite 语法),改用 Postgres 部分索引语法
-- 5. 添加 CONCURRENTLY 关键字重建索引(生产环境不阻塞写)
-- 6. 添加全文检索索引(tsvector + GIN)
-- 7. 启用 pg_cron 或 Celery beat 替代 threading.Thread 调度
-- =============================================================================
