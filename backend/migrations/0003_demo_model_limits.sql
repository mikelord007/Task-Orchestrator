-- 0003_demo_model_limits: persistent counters for the anonymous public demo.
-- Store only a keyed hash of the client address; never persist raw addresses.

CREATE TABLE demo_model_actions (
  id          INTEGER PRIMARY KEY,
  ts          TEXT NOT NULL,
  client_hash TEXT NOT NULL,
  action      TEXT NOT NULL
);

CREATE INDEX idx_demo_actions_ts ON demo_model_actions (ts);
CREATE INDEX idx_demo_actions_client_ts ON demo_model_actions (client_hash, ts);

CREATE TABLE demo_model_usage (
  id         INTEGER PRIMARY KEY,
  ts         TEXT NOT NULL,
  model      TEXT NOT NULL,
  tokens_in  INTEGER NOT NULL CHECK (tokens_in >= 0),
  tokens_out INTEGER NOT NULL CHECK (tokens_out >= 0)
);

CREATE INDEX idx_demo_usage_ts ON demo_model_usage (ts);
