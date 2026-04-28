"""
db.py — Supabase PostgreSQL (free tier)
Replaces BOTH Firestore (submissions) AND AlloyDB (vector search).
One DB, zero cost, no GCP billing needed.

SETUP (5 mins, free, no card):
1. supabase.com → Sign up with GitHub
2. New Project → name: ngo-adapter → region: Southeast Asia → set password
3. Wait ~2 mins
4. Settings → Database → copy Host + Password into .env
5. SQL Editor → run setup_schema() below once OR paste the SQL manually
"""

import os
import json
import uuid
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

DB_CONFIG = {
    "host":     os.environ.get("SUPABASE_HOST"),
    "port":     int(os.environ.get("SUPABASE_PORT", 5432)),
    "dbname":   os.environ.get("SUPABASE_DBNAME", "postgres"),
    "user":     os.environ.get("SUPABASE_USER", "postgres"),
    "password": os.environ.get("SUPABASE_PASSWORD"),
    "sslmode":  "require",
}

_connected = None


def _conn():
    return psycopg2.connect(**DB_CONFIG)


def check_connection() -> bool:
    global _connected
    if _connected is not None:
        return _connected
    try:
        if not DB_CONFIG["host"] or not DB_CONFIG["password"]:
            _connected = False
            return False
        c = _conn()
        c.close()
        _connected = True
        print("[db] Supabase connected")
        return True
    except Exception as e:
        print(f"[db] Cannot connect: {e}")
        _connected = False
        return False


def setup_schema():
    """Run once to create tables. Called on app startup automatically."""
    if not check_connection():
        print("[db] Skipping schema — not connected.")
        return
    sql = """
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT DEFAULT 'worker',  -- 'worker' or 'admin'
            created_at    TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id            TEXT PRIMARY KEY,
            raw_input     TEXT,
            location      TEXT,
            worker_name   TEXT,
            translated    JSONB,
            resources     JSONB,
            similar_crises JSONB DEFAULT '[]',
            resolved      BOOLEAN DEFAULT FALSE,
            resolution_notes TEXT,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            resolved_at   TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS crisis_embeddings (
            id               TEXT PRIMARY KEY,
            summary          TEXT NOT NULL,
            crisis_tags      JSONB,
            resolution_notes TEXT,
            embedding        VECTOR(768),
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            resolved_at      TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS crisis_embedding_idx
            ON crisis_embeddings
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10);
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql)
        c.commit()
        cur.close()
        c.close()
        print("[db] Schema ready")
        
        # Create default users if they don't exist
        create_user('admin', 'admin123', 'admin')
        create_user('worker', 'worker123', 'worker')
    except Exception as e:
        print(f"[db] Schema error: {e}")


# ── SUBMISSIONS ──────────────────────────────────────────────

def save_submission(data: dict) -> str:
    doc_id = str(uuid.uuid4())
    if not check_connection():
        return doc_id  # graceful fallback
    sql = """
        INSERT INTO submissions
            (id, raw_input, location, worker_name, translated, resources, similar_crises)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, (
            doc_id,
            data.get("raw_input", ""),
            data.get("location", ""),
            data.get("worker_name", ""),
            json.dumps(data.get("translated", {})),
            json.dumps(data.get("resources", [])),
            json.dumps(data.get("similar", [])),
        ))
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        print(f"[db] save_submission error: {e}")
    return doc_id


def get_all_submissions(limit: int = 50) -> list:
    if not check_connection():
        return []
    sql = """
        SELECT id, raw_input, location, worker_name,
               translated, resources, similar_crises,
               resolved, resolution_notes,
               created_at, resolved_at
        FROM submissions
        ORDER BY created_at DESC
        LIMIT %s
    """
    try:
        c = _conn()
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, (limit,))
        rows = cur.fetchall()
        cur.close()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            d["similar"] = d.pop("similar_crises")  # rename key for API compatibility
            for key in ("translated", "resources", "similar"):
                if isinstance(d[key], str):
                    d[key] = json.loads(d[key])
            for key in ("created_at", "resolved_at"):
                if d[key]:
                    d[key] = d[key].isoformat()
            result.append(d)
        return result
    except Exception as e:
        print(f"[db] get_all_submissions error: {e}")
        return []


def get_gap_stats() -> dict:
    if not check_connection():
        return {"total": 0, "resolved": 0, "unresolved": 0, "gap_frequencies": {}}
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM submissions")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM submissions WHERE resolved=TRUE")
        resolved = cur.fetchone()[0]
        cur.execute("SELECT translated FROM submissions")
        rows = cur.fetchall()
        cur.close()
        c.close()
        gap_freq = {}
        for (t,) in rows:
            data = t if isinstance(t, dict) else json.loads(t)
            for tag in data.get("crisis_tags", []):
                gap_freq[tag] = gap_freq.get(tag, 0) + 1
        return {
            "total": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "gap_frequencies": dict(
                sorted(gap_freq.items(), key=lambda x: x[1], reverse=True)
            ),
        }
    except Exception as e:
        print(f"[db] get_gap_stats error: {e}")
        return {"total": 0, "resolved": 0, "unresolved": 0, "gap_frequencies": {}}


def resolve_submission(doc_id: str, notes: str = ""):
    if not check_connection():
        return
    sql = """
        UPDATE submissions
        SET resolved=TRUE, resolution_notes=%s, resolved_at=NOW()
        WHERE id=%s
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, (notes, doc_id))
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        print(f"[db] resolve error: {e}")


# ── VECTOR SEARCH ────────────────────────────────────────────

def find_similar_crises(embedding: list) -> list:
    if not check_connection():
        return []
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    sql = """
        SELECT id, summary, crisis_tags, resolution_notes, resolved_at,
               1 - (embedding <=> %s::vector) AS similarity
        FROM crisis_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT 5
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, (vec_str, vec_str))
        rows = cur.fetchall()
        cur.close()
        c.close()
        return [
            {
                "id": r[0], "summary": r[1],
                "crisis_tags": r[2], "resolution_notes": r[3],
                "resolved_at": r[4].isoformat() if r[4] else None,
                "similarity": round(float(r[5]), 4),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] vector search error: {e}")
        return []


def upsert_embedding(doc_id: str, summary: str, tags: list,
                     embedding: list, notes: str = None):
    if not check_connection():
        return
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    sql = """
        INSERT INTO crisis_embeddings
            (id, summary, crisis_tags, resolution_notes, embedding)
        VALUES (%s, %s, %s, %s, %s::vector)
        ON CONFLICT (id) DO UPDATE
            SET summary=EXCLUDED.summary,
                resolution_notes=EXCLUDED.resolution_notes,
                embedding=EXCLUDED.embedding,
                resolved_at=NOW()
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, (doc_id, summary, json.dumps(tags), notes, vec_str))
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        print(f"[db] upsert_embedding error: {e}")


# ── USER MANAGEMENT ──────────────────────────────────────────

def create_user(username: str, password: str, role: str = 'worker') -> bool:
    if not check_connection():
        return False
    password_hash = generate_password_hash(password)
    sql = """
        INSERT INTO users (username, password_hash, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, (username, password_hash, role))
        c.commit()
        cur.close()
        c.close()
        return True
    except Exception as e:
        print(f"[db] create_user error: {e}")
        return False


def get_user_by_id(user_id: int) -> dict:
    if not check_connection():
        return {}
    sql = "SELECT id, username, role FROM users WHERE id = %s"
    try:
        c = _conn()
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, (user_id,))
        user = cur.fetchone()
        cur.close()
        c.close()
        return dict(user) if user else {}
    except Exception as e:
        print(f"[db] get_user_by_id error: {e}")
        return {}


def authenticate_user(username: str, password: str) -> dict:
    if not check_connection():
        return {}
    sql = "SELECT id, username, password_hash, role FROM users WHERE username = %s"
    try:
        c = _conn()
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, (username,))
        user = cur.fetchone()
        cur.close()
        c.close()
        if user and check_password_hash(user['password_hash'], password):
            return dict(user)
        return {}
    except Exception as e:
        print(f"[db] authenticate_user error: {e}")
        return {}
