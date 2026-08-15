import os
import re
from datetime import datetime, timezone

import psycopg2
from flask import Flask, jsonify, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB request body cap

SYNC_ID_RE = re.compile(r"^[0-9a-f]{64}$")
CODE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
HANDOFF_TTL_SECONDS = 600  # 6桁コードの有効期限(10分)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_blobs (
    sync_id            TEXT PRIMARY KEY,
    ciphertext         TEXT NOT NULL,
    iv                 TEXT NOT NULL,
    content_updated_at TIMESTAMPTZ NOT NULL,
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sync_blobs_last_synced_at ON sync_blobs (last_synced_at);

CREATE TABLE IF NOT EXISTS seed_handoff (
    code_hash  TEXT PRIMARY KEY,
    ciphertext TEXT NOT NULL,
    iv         TEXT NOT NULL,
    salt       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def get_db_url():
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def get_connection():
    db_url = get_db_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL/POSTGRES_URL is not set")
    return psycopg2.connect(db_url)


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def parse_iso8601(value):
    # Accept trailing "Z" (as produced by JS Date#toISOString) which
    # datetime.fromisoformat only started supporting in 3.11+.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_utc_iso8601(dt):
    # psycopg2 returns TIMESTAMPTZ values in the connection's session
    # timezone, not necessarily UTC — normalize before echoing to clients.
    return dt.astimezone(timezone.utc).isoformat()


@app.route("/api/push", methods=["POST", "DELETE"])
def push():
    if request.method == "DELETE":
        sync_id = request.args.get("sync_id", "")
        if not SYNC_ID_RE.match(sync_id):
            return jsonify(error="sync_id must be a 64-character hex string"), 400
        try:
            conn = get_connection()
        except RuntimeError as err:
            return jsonify(error=str(err)), 500
        try:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sync_blobs WHERE sync_id = %s", (sync_id,))
                deleted = cur.rowcount
            conn.commit()
            return jsonify(deleted=deleted)
        finally:
            conn.close()

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid JSON body"), 400

    sync_id = body.get("sync_id")
    ciphertext = body.get("ciphertext")
    iv = body.get("iv")
    updated_at_raw = body.get("updated_at")

    if not (isinstance(sync_id, str) and SYNC_ID_RE.match(sync_id)):
        return jsonify(error="sync_id must be a 64-character hex string"), 400
    if not (isinstance(ciphertext, str) and ciphertext):
        return jsonify(error="ciphertext is required"), 400
    if not (isinstance(iv, str) and iv):
        return jsonify(error="iv is required"), 400
    try:
        updated_at = parse_iso8601(updated_at_raw)
    except (TypeError, ValueError):
        return jsonify(error="updated_at must be an ISO 8601 timestamp"), 400
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    try:
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content_updated_at FROM sync_blobs WHERE sync_id = %s",
                (sync_id,),
            )
            row = cur.fetchone()
            server_updated_at = row[0] if row else None

            if server_updated_at is not None and server_updated_at >= updated_at:
                # Server already has data at least as new — reject the
                # write but still record that this sync_id was touched.
                cur.execute(
                    "UPDATE sync_blobs SET last_synced_at = now() WHERE sync_id = %s",
                    (sync_id,),
                )
                conn.commit()
                return jsonify(
                    applied=False,
                    updated_at=to_utc_iso8601(server_updated_at),
                )

            cur.execute(
                """
                INSERT INTO sync_blobs (sync_id, ciphertext, iv, content_updated_at, last_synced_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (sync_id) DO UPDATE SET
                    ciphertext = EXCLUDED.ciphertext,
                    iv = EXCLUDED.iv,
                    content_updated_at = EXCLUDED.content_updated_at,
                    last_synced_at = now()
                """,
                (sync_id, ciphertext, iv, updated_at),
            )
        conn.commit()
        return jsonify(applied=True, updated_at=to_utc_iso8601(updated_at))
    finally:
        conn.close()


@app.route("/api/pull", methods=["GET"])
def pull():
    sync_id = request.args.get("sync_id", "")
    if not SYNC_ID_RE.match(sync_id):
        return jsonify(error="sync_id must be a 64-character hex string"), 400

    try:
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ciphertext, iv, content_updated_at FROM sync_blobs WHERE sync_id = %s",
                (sync_id,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return jsonify(found=False)

            cur.execute(
                "UPDATE sync_blobs SET last_synced_at = now() WHERE sync_id = %s",
                (sync_id,),
            )
        conn.commit()
        ciphertext, iv, content_updated_at = row
        return jsonify(
            found=True,
            ciphertext=ciphertext,
            iv=iv,
            updated_at=to_utc_iso8601(content_updated_at),
        )
    finally:
        conn.close()


@app.route("/api/handoff", methods=["POST"])
def handoff_push():
    # カメラのない端末同士でシードを引き継ぐための、時間限定コードの発行。
    # サーバーはPIN自体を知らず、PINのハッシュ(code_hash)をキーとして
    # PINから導出した鍵で暗号化されたシードだけを一時保管する。
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid JSON body"), 400

    code_hash = body.get("code_hash")
    ciphertext = body.get("ciphertext")
    iv = body.get("iv")
    salt = body.get("salt")

    if not (isinstance(code_hash, str) and CODE_HASH_RE.match(code_hash)):
        return jsonify(error="code_hash must be a 64-character hex string"), 400
    if not (isinstance(ciphertext, str) and ciphertext):
        return jsonify(error="ciphertext is required"), 400
    if not (isinstance(iv, str) and iv):
        return jsonify(error="iv is required"), 400
    if not (isinstance(salt, str) and salt):
        return jsonify(error="salt is required"), 400

    try:
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM seed_handoff WHERE created_at < now() - interval '{HANDOFF_TTL_SECONDS} seconds'"
            )
            cur.execute(
                """
                INSERT INTO seed_handoff (code_hash, ciphertext, iv, salt, created_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (code_hash) DO UPDATE SET
                    ciphertext = EXCLUDED.ciphertext,
                    iv = EXCLUDED.iv,
                    salt = EXCLUDED.salt,
                    created_at = now()
                """,
                (code_hash, ciphertext, iv, salt),
            )
        conn.commit()
        return jsonify(ok=True, expires_in=HANDOFF_TTL_SECONDS)
    finally:
        conn.close()


@app.route("/api/handoff", methods=["GET"])
def handoff_pull():
    code_hash = request.args.get("code_hash", "")
    if not CODE_HASH_RE.match(code_hash):
        return jsonify(error="code_hash must be a 64-character hex string"), 400

    try:
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ciphertext, iv, salt FROM seed_handoff
                WHERE code_hash = %s
                  AND created_at >= now() - interval '{HANDOFF_TTL_SECONDS} seconds'
                """,
                (code_hash,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return jsonify(found=False)
            # 一度読み出したら使い捨てにする(再利用・総当たり対策)。
            cur.execute("DELETE FROM seed_handoff WHERE code_hash = %s", (code_hash,))
        conn.commit()
        ciphertext, iv, salt = row
        return jsonify(found=True, ciphertext=ciphertext, iv=iv, salt=salt)
    finally:
        conn.close()


@app.route("/api/cleanup", methods=["GET"])
def cleanup():
    cron_secret = os.environ.get("CRON_SECRET")
    if not cron_secret:
        # Safe default: refuse to run unauthenticated cleanup rather than
        # silently allowing anyone to trigger mass deletion.
        return jsonify(error="CRON_SECRET is not configured"), 500

    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {cron_secret}":
        return jsonify(error="unauthorized"), 401

    try:
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sync_blobs WHERE last_synced_at < now() - interval '7 days'"
            )
            deleted = cur.rowcount
            cur.execute(
                f"DELETE FROM seed_handoff WHERE created_at < now() - interval '{HANDOFF_TTL_SECONDS} seconds'"
            )
            deleted_handoffs = cur.rowcount
        conn.commit()
        return jsonify(deleted=deleted, deleted_handoffs=deleted_handoffs)
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
