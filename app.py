import csv
import hmac
import io
import ipaddress
import os
import re
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from io import BytesIO

import psycopg2

from flask import Flask, Response, jsonify, redirect, request, render_template, send_from_directory
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Response as WerkzeugResponse

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB request body cap

# Environment configuration
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
CRON_SECRET = os.environ.get("CRON_SECRET")

# Constants for ihcimen (sync/calendar functionality)
SYNC_ID_RE = re.compile(r"^[0-9a-f]{64}$")
CODE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
PUBLISH_ID_RE = re.compile(r"^[0-9a-f]{64}$")
HANDOFF_TTL_SECONDS = 600
HANDOFF_MIN_TTL_SECONDS = 60
HANDOFF_MAX_TTL_SECONDS = 24 * 60 * 60
ICS_FETCH_TIMEOUT_SECONDS = 10
ICS_MAX_BYTES = 5 * 1024 * 1024
ICS_PUBLISH_MAX_BYTES = 1 * 1024 * 1024
ICS_PUBLISH_TTL_SECONDS = 3 * 60 * 60
JST = timezone(timedelta(hours=9))

# Constants for memo/vitals functionality
GUEST_LINK_DEFAULT_HOURS = 24
GUEST_LINK_MAX_HOURS = 24 * 30  # 30 days
HISTORY_MIN_INTERVAL_SECONDS = 600

# Schema for ihcimen (sync/calendar)
IHCIMEN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_blobs (
    sync_id            TEXT PRIMARY KEY,
    ciphertext         TEXT NOT NULL,
    iv                 TEXT NOT NULL,
    content_updated_at TIMESTAMPTZ NOT NULL,
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sync_blobs_last_synced_at ON sync_blobs (last_synced_at);

CREATE TABLE IF NOT EXISTS seed_handoff (
    code_hash   TEXT PRIMARY KEY,
    ciphertext  TEXT NOT NULL,
    iv          TEXT NOT NULL,
    salt        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_seconds INTEGER NOT NULL DEFAULT 600
);
ALTER TABLE seed_handoff ADD COLUMN IF NOT EXISTS ttl_seconds INTEGER NOT NULL DEFAULT 600;

CREATE TABLE IF NOT EXISTS published_ics (
    publish_id     TEXT PRIMARY KEY,
    ics_text       TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_published_ics_last_synced_at ON published_ics (last_synced_at);

CREATE TABLE IF NOT EXISTS export_flags (
    sync_id           TEXT PRIMARY KEY,
    last_export_date  TEXT NOT NULL,
    last_synced_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_export_flags_last_synced_at ON export_flags (last_synced_at);
"""

# Schema for memo/vitals
MEMO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memos (
    id            SERIAL PRIMARY KEY,
    date          DATE NOT NULL,
    summary       TEXT,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memo_history (
    id            SERIAL PRIMARY KEY,
    memo_id       INTEGER NOT NULL REFERENCES memos(id),
    date          DATE NOT NULL,
    summary       TEXT,
    content       TEXT NOT NULL,
    archived_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS guest_links (
    id           SERIAL PRIMARY KEY,
    token        TEXT NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS memo_search_history (
    query         TEXT PRIMARY KEY,
    searched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sleep_data (
    date         DATE PRIMARY KEY,
    duration     INTEGER,
    score        INTEGER
);

CREATE TABLE IF NOT EXISTS steps_data (
    date         DATE PRIMARY KEY,
    steps        INTEGER
);
"""


# ============================================================================
# Database utilities
# ============================================================================

def get_conn():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    raise RuntimeError("DATABASE_URL is not set")


def ensure_ihcimen_schema(conn):
    with conn.cursor() as cur:
        cur.execute(IHCIMEN_SCHEMA_SQL)
    conn.commit()


def ensure_memo_schema(conn):
    with conn.cursor() as cur:
        cur.execute(MEMO_SCHEMA_SQL)
    conn.commit()


def init_db():
    """Initialize both schemas"""
    try:
        with get_conn() as conn:
            ensure_ihcimen_schema(conn)
            ensure_memo_schema(conn)
    except Exception as e:
        print(f"[init_db] schema initialization failed: {e}")


if DATABASE_URL:
    try:
        init_db()
    except Exception as e:
        print(f"[init_db] schema initialization failed: {e}")


# ============================================================================
# Authentication utilities for memo/vitals
# ============================================================================

def is_valid_guest_token(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM guest_links WHERE token = %s AND revoked_at IS NULL AND expires_at > now()",
                (token,),
            )
            return cur.fetchone() is not None


def classify_token(token):
    if not token:
        return None
    if ADMIN_TOKEN and hmac.compare_digest(token, ADMIN_TOKEN):
        return "admin"
    if is_valid_guest_token(token):
        return "guest"
    return None


def require_access(admin_only=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not ADMIN_TOKEN:
                return jsonify({"error": "server not configured: ADMIN_TOKEN is not set"}), 503
            supplied = request.headers.get("X-Access-Token") or request.args.get("token") or ""
            role = classify_token(supplied)
            if role is None:
                return jsonify({"error": "access token required"}), 401
            if admin_only and role != "admin":
                return jsonify({"error": "admin token required"}), 403
            request.access_role = role
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ============================================================================
# Utility functions for ihcimen
# ============================================================================

def parse_iso8601(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_utc_iso8601(dt):
    return dt.astimezone(timezone.utc).isoformat()


def is_fetchable_url(url):
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.hostname:
            return False
        for family, _, _, _, sockaddr in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                return False
        return True
    except Exception:
        return False


# ============================================================================
# Frontend routes
# ============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/edit")
def edit_redirect():
    return redirect("/")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(app.static_folder, "manifest.json", mimetype="application/manifest+json")


@app.route("/manual")
@require_access(admin_only=True)
def manual_page():
    return render_template("manual_entries.html")


@app.route("/icons/<path:filename>")
def serve_icons(filename):
    return send_from_directory(os.path.join(app.static_folder, "icons"), filename)


# ============================================================================
# ihcimen API endpoints (sync/calendar)
# ============================================================================

@app.route("/api/push", methods=["POST", "DELETE"])
def push():
    if request.method == "DELETE":
        sync_id = request.args.get("sync_id", "")
        if not SYNC_ID_RE.match(sync_id):
            return jsonify(error="sync_id must be a 64-character hex string"), 400
        try:
            conn = get_conn()
        except RuntimeError as err:
            return jsonify(error=str(err)), 500
        try:
            ensure_ihcimen_schema(conn)
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
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content_updated_at FROM sync_blobs WHERE sync_id = %s",
                (sync_id,),
            )
            row = cur.fetchone()
            server_updated_at = row[0] if row else None

            if server_updated_at is not None and server_updated_at >= updated_at:
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
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
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


@app.route("/api/export-flag", methods=["POST"])
def export_flag():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid JSON body"), 400

    sync_id = body.get("sync_id")
    if not (isinstance(sync_id, str) and SYNC_ID_RE.match(sync_id)):
        return jsonify(error="sync_id must be a 64-character hex string"), 400

    today_jst = datetime.now(JST).strftime("%Y-%m-%d")

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO export_flags (sync_id, last_export_date, last_synced_at)
                VALUES (%s, %s, now())
                ON CONFLICT (sync_id) DO UPDATE SET
                    last_export_date = EXCLUDED.last_export_date,
                    last_synced_at = now()
                WHERE export_flags.last_export_date IS DISTINCT FROM EXCLUDED.last_export_date
                RETURNING last_export_date
                """,
                (sync_id, today_jst),
            )
            claimed = cur.fetchone() is not None
        conn.commit()
        return jsonify(claimed=claimed, date=today_jst)
    finally:
        conn.close()


@app.route("/api/handoff", methods=["POST"])
def handoff_push():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid JSON body"), 400

    code_hash = body.get("code_hash")
    ciphertext = body.get("ciphertext")
    iv = body.get("iv")
    salt = body.get("salt")
    ttl_seconds = body.get("ttl_seconds", HANDOFF_TTL_SECONDS)

    if not (isinstance(code_hash, str) and CODE_HASH_RE.match(code_hash)):
        return jsonify(error="code_hash must be a 64-character hex string"), 400
    if not (isinstance(ciphertext, str) and ciphertext):
        return jsonify(error="ciphertext is required"), 400
    if not (isinstance(iv, str) and iv):
        return jsonify(error="iv is required"), 400
    if not (isinstance(salt, str) and salt):
        return jsonify(error="salt is required"), 400
    if not (
        isinstance(ttl_seconds, int)
        and not isinstance(ttl_seconds, bool)
        and HANDOFF_MIN_TTL_SECONDS <= ttl_seconds <= HANDOFF_MAX_TTL_SECONDS
    ):
        return (
            jsonify(
                error=f"ttl_seconds must be an integer between {HANDOFF_MIN_TTL_SECONDS} and {HANDOFF_MAX_TTL_SECONDS}"
            ),
            400,
        )

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM seed_handoff WHERE created_at + ttl_seconds * interval '1 second' < now()"
            )
            cur.execute(
                """
                INSERT INTO seed_handoff (code_hash, ciphertext, iv, salt, created_at, ttl_seconds)
                VALUES (%s, %s, %s, %s, now(), %s)
                ON CONFLICT (code_hash) DO UPDATE SET
                    ciphertext = EXCLUDED.ciphertext,
                    iv = EXCLUDED.iv,
                    salt = EXCLUDED.salt,
                    created_at = now(),
                    ttl_seconds = EXCLUDED.ttl_seconds
                """,
                (code_hash, ciphertext, iv, salt, ttl_seconds),
            )
        conn.commit()
        return jsonify(ok=True, expires_in=ttl_seconds)
    finally:
        conn.close()


@app.route("/api/handoff", methods=["GET"])
def handoff_pull():
    code_hash = request.args.get("code_hash", "")
    if not CODE_HASH_RE.match(code_hash):
        return jsonify(error="code_hash must be a 64-character hex string"), 400

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ciphertext, iv, salt FROM seed_handoff
                WHERE code_hash = %s
                  AND created_at + ttl_seconds * interval '1 second' >= now()
                """,
                (code_hash,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return jsonify(found=False)
            cur.execute("DELETE FROM seed_handoff WHERE code_hash = %s", (code_hash,))
        conn.commit()
        ciphertext, iv, salt = row
        return jsonify(found=True, ciphertext=ciphertext, iv=iv, salt=salt)
    finally:
        conn.close()


@app.route("/api/handoff", methods=["DELETE"])
def handoff_delete():
    code_hash = request.args.get("code_hash", "")
    if not CODE_HASH_RE.match(code_hash):
        return jsonify(error="code_hash must be a 64-character hex string"), 400

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM seed_handoff WHERE code_hash = %s", (code_hash,)
            )
            deleted = cur.rowcount
        conn.commit()
        return jsonify(deleted=deleted)
    finally:
        conn.close()


@app.route("/api/ics-proxy", methods=["GET"])
def ics_proxy():
    url = request.args.get("url", "")
    if not url:
        return jsonify(error="url is required"), 400
    if not is_fetchable_url(url):
        return jsonify(error="url is not fetchable"), 400

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ihcimen-ics-proxy/1.0"}
        )
        with urllib.request.urlopen(
            req, timeout=ICS_FETCH_TIMEOUT_SECONDS
        ) as resp:
            body = resp.read(ICS_MAX_BYTES + 1)
        if len(body) > ICS_MAX_BYTES:
            return jsonify(error="ICS file too large"), 413
        text = body.decode("utf-8", errors="replace")
        return jsonify(ics=text)
    except urllib.error.URLError as err:
        return jsonify(error=f"failed to fetch: {err}"), 502
    except Exception as err:
        return jsonify(error=f"failed to fetch: {err}"), 502


@app.route("/api/ics-publish", methods=["POST", "DELETE"])
def ics_publish():
    if request.method == "DELETE":
        publish_id = request.args.get("publish_id", "")
        if not PUBLISH_ID_RE.match(publish_id):
            return jsonify(error="publish_id must be a 64-character hex string"), 400
        try:
            conn = get_conn()
        except RuntimeError as err:
            return jsonify(error=str(err)), 500
        try:
            ensure_ihcimen_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM published_ics WHERE publish_id = %s", (publish_id,)
                )
                deleted = cur.rowcount
            conn.commit()
            return jsonify(deleted=deleted)
        finally:
            conn.close()

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid JSON body"), 400

    publish_id = body.get("publish_id")
    ics_text = body.get("ics_text")

    if not (isinstance(publish_id, str) and PUBLISH_ID_RE.match(publish_id)):
        return jsonify(error="publish_id must be a 64-character hex string"), 400
    if not (isinstance(ics_text, str) and ics_text):
        return jsonify(error="ics_text is required"), 400
    if len(ics_text.encode("utf-8")) > ICS_PUBLISH_MAX_BYTES:
        return jsonify(error="ics_text too large"), 413

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO published_ics (publish_id, ics_text, updated_at, last_synced_at)
                VALUES (%s, %s, now(), now())
                ON CONFLICT (publish_id) DO UPDATE SET
                    ics_text = EXCLUDED.ics_text,
                    updated_at = now(),
                    last_synced_at = now()
                """,
                (publish_id, ics_text),
            )
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


@app.route("/api/ics/<publish_id>", methods=["GET"])
def ics_serve(publish_id):
    if publish_id.endswith(".ics"):
        publish_id = publish_id[: -len(".ics")]
    if not PUBLISH_ID_RE.match(publish_id):
        return jsonify(error="publish_id must be a 64-character hex string"), 400

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ics_text, updated_at FROM published_ics WHERE publish_id = %s",
                (publish_id,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return jsonify(error="not found"), 404
            ics_text, updated_at = row
            age = datetime.now(timezone.utc) - updated_at
            if age.total_seconds() > ICS_PUBLISH_TTL_SECONDS:
                cur.execute(
                    "DELETE FROM published_ics WHERE publish_id = %s", (publish_id,)
                )
                conn.commit()
                return jsonify(error="this share link has expired"), 410
            cur.execute(
                "UPDATE published_ics SET last_synced_at = now() WHERE publish_id = %s",
                (publish_id,),
            )
        conn.commit()
        return Response(ics_text, mimetype="text/calendar")
    finally:
        conn.close()


@app.route("/api/cleanup", methods=["GET"])
def cleanup():
    if not CRON_SECRET:
        return jsonify(error="CRON_SECRET is not configured"), 500

    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {CRON_SECRET}":
        return jsonify(error="unauthorized"), 401

    try:
        conn = get_conn()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_ihcimen_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sync_blobs WHERE last_synced_at < now() - interval '7 days'"
            )
            deleted = cur.rowcount
            cur.execute(
                "DELETE FROM seed_handoff WHERE created_at + ttl_seconds * interval '1 second' < now()"
            )
            deleted_handoffs = cur.rowcount
            cur.execute(
                "DELETE FROM published_ics WHERE last_synced_at < now() - interval '7 days'"
                f" OR updated_at < now() - interval '{ICS_PUBLISH_TTL_SECONDS} seconds'"
            )
            deleted_published_ics = cur.rowcount
            cur.execute(
                "DELETE FROM export_flags WHERE last_synced_at < now() - interval '7 days'"
            )
            deleted_export_flags = cur.rowcount
        conn.commit()
        return jsonify(
            deleted=deleted,
            deleted_handoffs=deleted_handoffs,
            deleted_published_ics=deleted_published_ics,
            deleted_export_flags=deleted_export_flags,
        )
    finally:
        conn.close()


# ============================================================================
# Memo API endpoints
# ============================================================================

def row_to_memo(row):
    return {
        "id": str(row["id"]),
        "date": row["date"].isoformat(),
        "is_clinic_day": True,
        "summary": row["summary"],
        "content": row["content"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


@app.route("/api/auth/check", methods=["GET"])
@require_access()
def auth_check():
    return jsonify({"ok": True, "role": request.access_role})


@app.route("/api/memo", methods=["GET"])
@require_access()
def list_memos():
    qdate = request.args.get("date")
    limit = min(int(request.args.get("limit", 200)), 5000)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if qdate:
                cur.execute("SELECT * FROM memos WHERE date = %s", (qdate,))
            else:
                cur.execute("SELECT * FROM memos ORDER BY date DESC LIMIT %s", (limit,))
            rows = cur.fetchall()

    return jsonify([row_to_memo(r) for r in rows])


@app.route("/api/memo", methods=["POST"])
@require_access(admin_only=True)
def upsert_memo():
    data = request.get_json(force=True, silent=True) or {}
    memo_date = data.get("date")
    if not memo_date:
        return jsonify({"error": "date is required"}), 400

    summary = data.get("summary")
    content = data.get("content")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM memos WHERE date = %s FOR UPDATE", (memo_date,))
            existing = cur.fetchone()

            if existing and existing["content"] != content:
                age = (datetime.now(timezone.utc) - existing["updated_at"]).total_seconds()
                if age > HISTORY_MIN_INTERVAL_SECONDS:
                    try:
                        cur.execute("SAVEPOINT memo_history_checkpoint")
                        cur.execute(
                            """
                            INSERT INTO memo_history (memo_id, date, summary, content, archived_at)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (existing["id"], existing["date"], existing["summary"], existing["content"], existing["updated_at"]),
                        )
                        cur.execute("RELEASE SAVEPOINT memo_history_checkpoint")
                    except psycopg2.Error as e:
                        cur.execute("ROLLBACK TO SAVEPOINT memo_history_checkpoint")
                        print(f"[memo_history] checkpoint failed, continuing without it: {e}")

            cur.execute(
                """
                INSERT INTO memos (date, summary, content)
                VALUES (%s, %s, %s)
                ON CONFLICT (date) DO UPDATE
                SET summary = EXCLUDED.summary,
                    content = EXCLUDED.content,
                    updated_at = now()
                RETURNING *
                """,
                (memo_date, summary, content),
            )
            row = cur.fetchone()
        conn.commit()

    return jsonify(row_to_memo(row)), 201


@app.route("/api/memo/<memo_id>/history", methods=["GET"])
@require_access()
def get_memo_history(memo_id):
    limit = min(int(request.args.get("limit", 50)), 200)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, memo_id, date, summary, content, archived_at
                FROM memo_history
                WHERE memo_id = %s
                ORDER BY archived_at DESC
                LIMIT %s
                """,
                (memo_id, limit),
            )
            rows = cur.fetchall()

    return jsonify([
        {
            "id": str(r["id"]),
            "memo_id": str(r["memo_id"]),
            "date": r["date"].isoformat(),
            "summary": r["summary"],
            "content": r["content"],
            "archived_at": r["archived_at"].isoformat(),
        }
        for r in rows
    ])


@app.route("/api/memo/<memo_id>", methods=["GET"])
@require_access()
def get_memo(memo_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM memos WHERE id = %s", (memo_id,))
            row = cur.fetchone()

    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row_to_memo(row))


@app.route("/api/memo/<memo_id>", methods=["PUT"])
@require_access(admin_only=True)
def update_memo(memo_id):
    data = request.get_json(force=True, silent=True) or {}
    fields = []
    values = []
    if "date" in data:
        fields.append("date = %s")
        values.append(data["date"])
    if "summary" in data:
        fields.append("summary = %s")
        values.append(data["summary"])
    if "content" in data:
        fields.append("content = %s")
        values.append(data["content"])
    if not fields:
        return jsonify({"error": "no fields to update"}), 400
    fields.append("updated_at = now()")
    values.append(memo_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE memos SET {', '.join(fields)} WHERE id = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row_to_memo(row))


@app.route("/api/memo/<memo_id>", methods=["DELETE"])
@require_access(admin_only=True)
def delete_memo(memo_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM memos WHERE id = %s RETURNING id", (memo_id,))
            deleted = cur.fetchone()
        conn.commit()

    if not deleted:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ============================================================================
# Guest links endpoints
# ============================================================================

def row_to_guest_link(row):
    return {
        "id": str(row["id"]),
        "token": row["token"],
        "created_at": row["created_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "revoked": row["revoked_at"] is not None,
        "expired": row["expires_at"] <= datetime.now(timezone.utc),
    }


@app.route("/api/guest-links", methods=["GET"])
@require_access(admin_only=True)
def list_guest_links():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM guest_links ORDER BY created_at DESC LIMIT 100")
            rows = cur.fetchall()
    return jsonify([row_to_guest_link(r) for r in rows])


@app.route("/api/guest-links", methods=["POST"])
@require_access(admin_only=True)
def create_guest_link():
    data = request.get_json(force=True, silent=True) or {}
    hours = data.get("hours", GUEST_LINK_DEFAULT_HOURS)
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return jsonify({"error": "hours must be a number"}), 400
    if not (0 < hours <= GUEST_LINK_MAX_HOURS):
        return jsonify({"error": f"hours must be between 0 and {GUEST_LINK_MAX_HOURS}"}), 400
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO guest_links (token, expires_at) VALUES (%s, %s) RETURNING *",
                (token, expires_at),
            )
            row = cur.fetchone()
        conn.commit()
    return jsonify(row_to_guest_link(row)), 201


@app.route("/api/guest-links/<link_id>", methods=["DELETE"])
@require_access(admin_only=True)
def revoke_guest_link(link_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE guest_links SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING id",
                (link_id,),
            )
            updated = cur.fetchone()
        conn.commit()
    if not updated:
        return jsonify({"error": "not found or already revoked"}), 404
    return jsonify({"ok": True})


# ============================================================================
# Search history endpoints
# ============================================================================

@app.route("/api/search-history", methods=["GET"])
@require_access()
def list_search_history():
    limit = min(int(request.args.get("limit", 20)), 100)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT query FROM memo_search_history ORDER BY searched_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
    return jsonify([r["query"] for r in rows])


@app.route("/api/search-history", methods=["POST"])
@require_access(admin_only=True)
def save_search_history():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memo_search_history (query) VALUES (%s)
                ON CONFLICT (query) DO UPDATE SET searched_at = now()
                """,
                (query,),
            )
        conn.commit()
    return jsonify({"ok": True}), 201


# ============================================================================
# Vitals endpoints
# ============================================================================

@app.route("/api/vitals", methods=["GET"])
@require_access()
def get_vitals():
    end = request.args.get("end") or date.today().isoformat()
    start = request.args.get("start") or (date.fromisoformat(end) - timedelta(days=49)).isoformat()
    where = "WHERE date BETWEEN %s AND %s"
    params = (start, end)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT date, duration, score FROM sleep_data {where} ORDER BY date", params)
            sleep_rows = cur.fetchall()
            cur.execute(f"SELECT date, steps FROM steps_data {where} ORDER BY date", params)
            steps_rows = cur.fetchall()
    return jsonify({
        "sleep": [
            {"date": r["date"].isoformat(), "duration": r["duration"], "score": r["score"]}
            for r in sleep_rows
        ],
        "steps": [{"date": r["date"].isoformat(), "steps": r["steps"]} for r in steps_rows],
    })


# ============================================================================
# Manual entries endpoints
# ============================================================================

@app.route("/api/manual/steps", methods=["POST"])
@require_access(admin_only=True)
def manual_steps():
    data = request.get_json(force=True, silent=True) or {}
    entries = data.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "entries must be a non-empty list"}), 400
    rows = []
    errors = []
    for i, e in enumerate(entries):
        d = e.get("date")
        try:
            date.fromisoformat(d)
        except Exception:
            errors.append({"index": i, "error": "invalid date", "date": d})
            continue
        try:
            steps = int(e.get("steps") or 0)
            if steps < 0:
                raise ValueError()
        except Exception:
            errors.append({"index": i, "error": "invalid steps", "steps": e.get("steps")})
            continue
        rows.append((d, steps))
    if not rows:
        return jsonify({"ok": False, "errors": errors}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO steps_data (date, steps) VALUES (%s, %s)
                    ON CONFLICT (date) DO UPDATE SET steps = EXCLUDED.steps
                    """,
                    row,
                )
        conn.commit()
    return jsonify({"ok": True, "imported": len(rows), "errors": errors, "message": "歩数データを保存しました"})


@app.route("/api/manual/sleep", methods=["POST"])
@require_access(admin_only=True)
def manual_sleep():
    data = request.get_json(force=True, silent=True) or {}
    entries = data.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "entries must be a non-empty list"}), 400
    rows_duration = []
    rows_score = []
    errors = []
    for i, e in enumerate(entries):
        d = e.get("date")
        try:
            date.fromisoformat(d)
        except Exception:
            errors.append({"index": i, "error": "invalid date", "date": d})
            continue
        duration = e.get("duration")
        score = e.get("score")
        used = False
        if duration not in (None, ''):
            try:
                dur = int(duration)
                rows_duration.append((d, dur))
                used = True
            except Exception:
                errors.append({"index": i, "error": "invalid duration", "duration": duration})
                continue
        if score not in (None, ''):
            try:
                sc = int(score)
                rows_score.append((d, sc))
                used = True
            except Exception:
                errors.append({"index": i, "error": "invalid score", "score": score})
                continue
        if not used:
            errors.append({"index": i, "error": "no duration or score provided"})
    if not rows_duration and not rows_score:
        return jsonify({"ok": False, "errors": errors}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            if rows_duration:
                for row in rows_duration:
                    cur.execute(
                        """
                        INSERT INTO sleep_data (date, duration) VALUES (%s, %s)
                        ON CONFLICT (date) DO UPDATE SET duration = EXCLUDED.duration
                        """,
                        row,
                    )
            if rows_score:
                for row in rows_score:
                    cur.execute(
                        """
                        INSERT INTO sleep_data (date, score) VALUES (%s, %s)
                        ON CONFLICT (date) DO UPDATE SET score = EXCLUDED.score
                        """,
                        row,
                    )
        conn.commit()
    return jsonify({
        "ok": True,
        "imported_duration": len(rows_duration),
        "imported_score": len(rows_score),
        "errors": errors,
        "message": "睡眠データを保存しました"
    })


# ============================================================================
# Vercel Serverless Function handler
# ============================================================================

def handler(request):
    """Vercel Serverless Function entry point."""
    try:
        path = request.path or "/"
        method = request.method or "GET"

        # Strip /api prefix to match Flask routes
        if path.startswith("/api/"):
            path = "/" + path[5:]  # Remove '/api/' prefix and keep leading slash
        elif path == "/api":
            path = "/"

        # Handle legacy /index.py requests
        if path == "/index.py" or path == "/api/index.py":
            query_params = request.query or {}
            if method == "GET" and "sync_id" in query_params:
                path = "/api/pull"
            elif method == "DELETE" and "sync_id" in query_params:
                path = "/api/push"
            elif method == "POST":
                path = "/api/push"
            else:
                return WerkzeugResponse(
                    b'{"error":"Unknown legacy endpoint"}',
                    status=400,
                    headers=[("Content-Type", "application/json")]
                )

        # Reconstruct query string
        query_string = ""
        if request.query:
            query_parts = []
            for key, values in request.query.items():
                if isinstance(values, list):
                    for value in values:
                        query_parts.append(f"{key}={value}")
                else:
                    query_parts.append(f"{key}={values}")
            query_string = "&".join(query_parts)

        # Get request body
        body = request.body if hasattr(request, "body") else b""
        if isinstance(body, str):
            body = body.encode("utf-8")

        # Build WSGI environ
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query_string,
            "SERVER_NAME": request.headers.get("Host", "localhost").split(":")[0],
            "SERVER_PORT": "443",
            "wsgi.url_scheme": "https",
            "wsgi.input": BytesIO(body),
            "wsgi.errors": BytesIO(),
        }

        # Add headers to environ
        for key, value in request.headers.items():
            key_upper = key.upper().replace("-", "_")
            if key_upper not in ("HOST", "CONTENT_LENGTH", "CONTENT_TYPE"):
                environ[f"HTTP_{key_upper}"] = value

        # Set content headers
        if body:
            environ["CONTENT_LENGTH"] = str(len(body))
            content_type = request.headers.get("Content-Type", "application/octet-stream")
            environ["CONTENT_TYPE"] = content_type
        else:
            environ["CONTENT_LENGTH"] = "0"

        # Dispatch to Flask app
        response = app(environ, lambda status, headers: None)

        # Collect response data
        response_data = b""
        for chunk in response:
            response_data += chunk

        # Build status code and headers
        status_code = 200
        headers = []

        # Try to extract headers from Flask response using test client
        try:
            with app.test_client() as client:
                if method == "GET":
                    resp = client.get(path + ("?" + query_string if query_string else ""), headers=dict(request.headers))
                elif method == "POST":
                    resp = client.post(path + ("?" + query_string if query_string else ""),
                                     data=body if body else None,
                                     headers=dict(request.headers))
                elif method == "DELETE":
                    resp = client.delete(path + ("?" + query_string if query_string else ""),
                                       headers=dict(request.headers))
                else:
                    resp = client.open(path + ("?" + query_string if query_string else ""),
                                      method=method, data=body if body else None,
                                      headers=dict(request.headers))
                status_code = resp.status_code
                headers = list(resp.headers.items())
                response_data = resp.get_data()
        except Exception:
            status_code = 200
            headers = [("Content-Type", "application/json")]

        return WerkzeugResponse(
            response_data,
            status=status_code,
            headers=headers
        )
    except Exception as e:
        import traceback
        error_msg = f"Internal error: {str(e)}\n{traceback.format_exc()}"
        return WerkzeugResponse(
            error_msg.encode("utf-8"),
            status=500,
            headers=[("Content-Type", "text/plain")]
        )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
