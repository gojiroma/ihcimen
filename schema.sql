-- Reference copy of the schema. Not required to run manually — the Flask
-- backend calls this same DDL (via ensure_schema()) on every request, so
-- the table is created automatically the first time the API is hit after
-- the Neon integration is linked in Vercel.

CREATE TABLE IF NOT EXISTS sync_blobs (
    sync_id            TEXT PRIMARY KEY,       -- server-safe ID derived from the client seed (SHA-256 hex), never the raw seed
    ciphertext         TEXT NOT NULL,           -- base64 AES-GCM ciphertext of the whole synced dataset
    iv                 TEXT NOT NULL,           -- base64 12-byte AES-GCM nonce
    content_updated_at TIMESTAMPTZ NOT NULL,    -- client-supplied timestamp; drives last-write-wins conflict resolution
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now() -- bumped on every push or pull; drives the 7-day inactivity cleanup
);

CREATE INDEX IF NOT EXISTS idx_sync_blobs_last_synced_at ON sync_blobs (last_synced_at);

-- Short-lived table for the camera-less "6-digit code" seed handoff.
-- The server never sees the PIN itself, only a hash of it (code_hash) and
-- the seed encrypted with a PIN-derived key. Rows expire after
-- HANDOFF_TTL_SECONDS (10 minutes) and are deleted immediately after a
-- successful single read.
CREATE TABLE IF NOT EXISTS seed_handoff (
    code_hash  TEXT PRIMARY KEY,
    ciphertext TEXT NOT NULL,
    iv         TEXT NOT NULL,
    salt       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backs the "publish an ICS URL" feature for the day/week calendars. Unlike
-- every other table here, this one is intentionally plaintext: standard
-- calendar clients (Apple/Google Calendar, etc.) fetch the URL with a plain
-- HTTP GET and expect readable iCalendar text, so there is no way to keep
-- this data end-to-end encrypted and still have it work as a subscribable
-- feed. publish_id is a random client-generated 64-hex ID, unrelated to any
-- sync_id, created only when the user explicitly enables publishing.
CREATE TABLE IF NOT EXISTS published_ics (
    publish_id     TEXT PRIMARY KEY,
    ics_text       TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now() -- bumped on every publish or client fetch; drives the 7-day inactivity cleanup
);

CREATE INDEX IF NOT EXISTS idx_published_ics_last_synced_at ON published_ics (last_synced_at);

-- Backs the "first open of the day (JST) triggers an automatic export"
-- feature. sync_id here is derived from a dedicated info string, unrelated
-- to the entries/calendar sync_ids, so this table never carries any note
-- content — only a JST calendar-date string per sync_id. A device claims
-- the day's export by successfully changing last_export_date; Postgres's
-- row-level locking on the UPSERT ensures only one device sharing the same
-- seed can claim a given day, even if several open the app at once.
CREATE TABLE IF NOT EXISTS export_flags (
    sync_id           TEXT PRIMARY KEY,
    last_export_date  TEXT NOT NULL,
    last_synced_at    TIMESTAMPTZ NOT NULL DEFAULT now() -- bumped on every check; drives the 7-day inactivity cleanup
);

CREATE INDEX IF NOT EXISTS idx_export_flags_last_synced_at ON export_flags (last_synced_at);
