-- Supplier Radar schema
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    city TEXT NOT NULL,
    status TEXT NOT NULL,             -- pending|running|done|error
    created_at TEXT NOT NULL,
    finished_at TEXT,
    stats TEXT                        -- JSON: engines, pages, llm_calls, cost
);

CREATE TABLE IF NOT EXISTS serp_cache (
    engine TEXT NOT NULL,
    query_norm TEXT NOT NULL,
    html TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (engine, query_norm)
);

CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY,
    html TEXT,
    status_code INTEGER,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    identity_key TEXT PRIMARY KEY,
    card_json TEXT NOT NULL,          -- merged SupplierCard
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_suppliers (
    job_id TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    PRIMARY KEY (job_id, identity_key)
);

CREATE INDEX IF NOT EXISTS idx_serp_fetched ON serp_cache(fetched_at);
CREATE INDEX IF NOT EXISTS idx_page_fetched ON page_cache(fetched_at);
