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
