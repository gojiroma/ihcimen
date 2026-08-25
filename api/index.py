import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import psycopg2
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB request body cap

SYNC_ID_RE = re.compile(r"^[0-9a-f]{64}$")
CODE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
PUBLISH_ID_RE = re.compile(r"^[0-9a-f]{64}$")
HANDOFF_TTL_SECONDS = 600  # 6桁コードの有効期限(10分)
ICS_FETCH_TIMEOUT_SECONDS = 10
ICS_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap on the fetched ICS body
ICS_PUBLISH_MAX_BYTES = 1 * 1024 * 1024  # 1 MB cap on a published ICS body
ICS_PUBLISH_TTL_SECONDS = 3 * 60 * 60  # 公開URLの有効期限(3時間、一時的な共有リンク)
JST = timezone(timedelta(hours=9))

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

-- 日/週カレンダーの「ICS公開URL」機能用。ここだけは仕様上、意図的に
-- 平文で保存する(標準的なカレンダークライアントはJSを実行せず、
-- URLへの素のHTTP GETでICSテキストをそのまま読むため、サーバー側で
-- 復号なしに配信できる形でなければ購読できない)。publish_idはクライアント
-- が生成するランダムな64桁hexで、同期用のsync_idとは無関係。
CREATE TABLE IF NOT EXISTS published_ics (
    publish_id     TEXT PRIMARY KEY,
    ics_text       TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_published_ics_last_synced_at ON published_ics (last_synced_at);

-- 「その日初めてページを開いたときの自動エクスポート」を、同じsync_idを
-- 共有する端末間で1日1回だけに絞るためのフラグ。sync_idは同期データとは
-- 無関係な専用のinfo文字列から導出されるため、本文/カレンダーの内容は
-- ここには一切含まれない(JST日付文字列のみ)。
CREATE TABLE IF NOT EXISTS export_flags (
    sync_id           TEXT PRIMARY KEY,
    last_export_date  TEXT NOT NULL,
    last_synced_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_export_flags_last_synced_at ON export_flags (last_synced_at);
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


def is_fetchable_url(url):
    # ICSプロキシは任意のURLをサーバー側から取得するため、内部/ループバック
    # アドレスへのSSRFを防ぐ最低限のチェック。ホスト名がどのIPに解決されるか
    # まで見て、プライベート/ループバック/リンクローカルなら拒否する。
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.hostname:
            return False
        for family, _, _, _, sockaddr in socket.getaddrinfo(
            parsed.hostname, None
        ):
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


@app.route("/api/export-flag", methods=["POST"])
def export_flag():
    # その日(JST)最初にページを開いた端末だけが自動エクスポートを実行できる
    # ように、sync_idごとに「最後に自動エクスポートを行った日付」を排他的に
    # 更新する。ON CONFLICT ... WHERE ... RETURNING により、同じ日付へすでに
    # 更新済みの行は0行しか返らない(=このリクエストは「今日はまだ」だと
    # 主張できない)ため、Postgresの行ロックだけで複数端末の同時アクセスに
    # 対しても排他が成立する。
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid JSON body"), 400

    sync_id = body.get("sync_id")
    if not (isinstance(sync_id, str) and SYNC_ID_RE.match(sync_id)):
        return jsonify(error="sync_id must be a 64-character hex string"), 400

    today_jst = datetime.now(JST).strftime("%Y-%m-%d")

    try:
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
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


@app.route("/api/ics-proxy", methods=["GET"])
def ics_proxy():
    # ICSはブラウザから直接fetchするとCORSで弾かれるホストが多いため、
    # サーバー側で代わりに取得してテキストをそのまま返す(自ドメインなので
    # ブラウザ側のCORS制約を受けない)。DBは使わないので同期機能が
    # 未設定でも独立して動く。
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
    # 日/週カレンダーの内容を、外部のカレンダークライアントが購読できる
    # ICSとして公開する機能。ここは意図的にE2E暗号化の対象外(平文保存)。
    # クライアント側でユーザーが明示的に「公開する」を押したときだけ呼ばれる。
    if request.method == "DELETE":
        publish_id = request.args.get("publish_id", "")
        if not PUBLISH_ID_RE.match(publish_id):
            return jsonify(error="publish_id must be a 64-character hex string"), 400
        try:
            conn = get_connection()
        except RuntimeError as err:
            return jsonify(error=str(err)), 500
        try:
            ensure_schema(conn)
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
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
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
        conn = get_connection()
    except RuntimeError as err:
        return jsonify(error=str(err)), 500

    try:
        ensure_schema(conn)
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
            # 一時的な共有リンクとして、最後の更新(発行/再発行/内容変更)から
            # ICS_PUBLISH_TTL_SECONDSが経過したら失効させる。last_synced_at
            # (購読アプリからの定期フェッチ)では延長されない、更新時刻基準の
            # 固定期限。
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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
