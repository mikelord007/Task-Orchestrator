-- 0002_playbook_scan_cursor: processing watermark for accepted-fix lesson scans.
-- This is an operational cursor, not derived agent or evaluation status.
CREATE TABLE playbook_scan_cursors (
  stream        TEXT PRIMARY KEY,
  last_event_id INTEGER NOT NULL CHECK (last_event_id >= 0)
);
