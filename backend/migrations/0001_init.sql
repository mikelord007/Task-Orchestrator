-- 0001_init: ledger + the four supporting tables (PLAN.md sections 4.1, 4.2, 5).
-- Migrations are never edited after merge. Add a new numbered file instead.

-- Append-only event ledger. Never UPDATE, never DELETE. Display status is
-- derived from these rows, never stored.
CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,        -- ISO8601 UTC
  kind          TEXT NOT NULL,
  agent_id      TEXT,
  agent_version INTEGER,
  run_id        TEXT,
  lever         TEXT,                 -- prompt | tools | memory | orchestration | routing
  payload       TEXT NOT NULL         -- JSON
);

CREATE INDEX idx_events_agent ON events (agent_id, id);
CREATE INDEX idx_events_kind ON events (kind, id);
CREATE INDEX idx_events_run ON events (run_id, id);

-- current_version is the only mutable pointer in the system (section 4.2).
CREATE TABLE agents (
  agent_id        TEXT PRIMARY KEY,
  goal            TEXT NOT NULL,
  domain          TEXT NOT NULL,
  evaluator_id    TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 0,
  created_ts      TEXT NOT NULL
);

-- screenshot_path is retained for shape compatibility but unused: screenshot
-- upload is dropped in section 0.4 (text-only issues).
CREATE TABLE issues (
  id                TEXT PRIMARY KEY,
  agent_id          TEXT NOT NULL,
  title             TEXT NOT NULL,
  body              TEXT NOT NULL DEFAULT '',
  screenshot_path   TEXT,
  source            TEXT NOT NULL DEFAULT 'human',   -- human | auto
  status            TEXT NOT NULL DEFAULT 'open',    -- open | closed
  failure_signature TEXT,
  created_ts        TEXT NOT NULL,
  fixed_version     INTEGER
);

CREATE INDEX idx_issues_agent ON issues (agent_id, created_ts);

-- Mirror of playbook/lessons.jsonl for querying. The jsonl file stays the
-- source of truth the architect reads (contracts/playbook.md).
CREATE TABLE lessons (
  id              TEXT PRIMARY KEY,
  lever           TEXT NOT NULL,
  "trigger"       TEXT NOT NULL,
  lesson          TEXT NOT NULL,
  domain_tags     TEXT NOT NULL DEFAULT '[]',        -- JSON array
  source_agent_id TEXT,
  source_issue_id TEXT,
  ts              TEXT NOT NULL
);

-- Background jobs for POST /agents/{id}/improve and POST /agents/{id}/run.
CREATE TABLE improve_jobs (
  job_id       TEXT PRIMARY KEY,
  agent_id     TEXT NOT NULL,
  kind         TEXT NOT NULL DEFAULT 'improve',      -- improve | run
  status       TEXT NOT NULL DEFAULT 'queued',       -- queued | running | done | error
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  issue_id     TEXT,
  current_step TEXT,
  result       TEXT,                                 -- JSON
  error        TEXT,
  created_ts   TEXT NOT NULL,
  updated_ts   TEXT NOT NULL
);

CREATE INDEX idx_jobs_agent ON improve_jobs (agent_id, created_ts);
