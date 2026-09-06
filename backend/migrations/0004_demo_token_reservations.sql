-- 0004_demo_token_reservations: reserve bounded provider capacity atomically.

CREATE TABLE demo_model_token_reservations (
  reservation_id TEXT PRIMARY KEY,
  ts             TEXT NOT NULL,
  reserved_tokens INTEGER NOT NULL CHECK (reserved_tokens > 0)
);

CREATE INDEX idx_demo_token_reservations_ts
  ON demo_model_token_reservations (ts);
