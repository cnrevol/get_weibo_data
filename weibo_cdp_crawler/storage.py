from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.out_dir / "raw_responses"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.out_dir / "weibo.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        self.posts_jsonl = (self.out_dir / "posts.jsonl").open("a", encoding="utf-8")
        self.comments_jsonl = (self.out_dir / "comments.jsonl").open("a", encoding="utf-8")

    def close(self):
        self.posts_jsonl.close()
        self.comments_jsonl.close()
        self.conn.close()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              target_url TEXT,
              config_json TEXT NOT NULL,
              status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS posts (
              post_id TEXT PRIMARY KEY,
              run_id INTEGER NOT NULL,
              mblogid TEXT,
              user_id TEXT,
              screen_name TEXT,
              created_at TEXT,
              created_at_iso TEXT,
              text TEXT,
              list_text TEXT,
              full_text TEXT,
              text_source TEXT,
              is_long_text INTEGER,
              source TEXT,
              reposts_count INTEGER,
              comments_count INTEGER,
              attitudes_count INTEGER,
              detail_url TEXT,
              source_url TEXT,
              raw_json TEXT NOT NULL,
              fulltext_raw_json TEXT,
              first_seen_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS comments (
              comment_id TEXT PRIMARY KEY,
              run_id INTEGER NOT NULL,
              post_id TEXT,
              root_id TEXT,
              parent_id TEXT,
              user_id TEXT,
              screen_name TEXT,
              created_at TEXT,
              text TEXT,
              like_count INTEGER,
              source TEXT,
              source_url TEXT,
              raw_json TEXT NOT NULL,
              first_seen_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS raw_responses (
              response_id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id INTEGER NOT NULL,
              captured_at TEXT NOT NULL,
              kind TEXT NOT NULL,
              url TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              body_path TEXT NOT NULL,
              UNIQUE(sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
            CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts(user_id);
            """
        )
        self._migrate_schema()
        self.conn.commit()

    def _migrate_schema(self):
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(posts)").fetchall()}
        migrations = {
            "list_text": "ALTER TABLE posts ADD COLUMN list_text TEXT",
            "full_text": "ALTER TABLE posts ADD COLUMN full_text TEXT",
            "text_source": "ALTER TABLE posts ADD COLUMN text_source TEXT",
            "is_long_text": "ALTER TABLE posts ADD COLUMN is_long_text INTEGER",
            "fulltext_raw_json": "ALTER TABLE posts ADD COLUMN fulltext_raw_json TEXT",
            "created_at_iso": "ALTER TABLE posts ADD COLUMN created_at_iso TEXT",
        }
        for column, sql in migrations.items():
            if column not in existing:
                self.conn.execute(sql)

    def create_run(self, target_url: str | None, config: dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(started_at, target_url, config_json, status) VALUES (?, ?, ?, ?)",
            (utc_now(), target_url, json.dumps(config, ensure_ascii=False, sort_keys=True), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str):
        self.conn.execute("UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id))
        self.conn.commit()

    def save_raw_response(self, run_id: int, kind: str, url: str, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        path = self.raw_dir / f"{digest}.json"
        if not path.exists():
            path.write_text(body, encoding="utf-8")
        self.conn.execute(
            """
            INSERT OR IGNORE INTO raw_responses(run_id, captured_at, kind, url, sha256, body_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, utc_now(), kind, url, digest, str(path.relative_to(self.out_dir))),
        )
        self.conn.commit()

    def save_post(self, run_id: int, post: dict[str, Any]) -> bool:
        post_id = post.get("post_id")
        if not post_id:
            return False
        now = utc_now()
        raw = json.dumps(post.get("raw", {}), ensure_ascii=False, sort_keys=True)
        fulltext_raw = post.get("fulltext_raw")
        fulltext_raw_json = (
            json.dumps(fulltext_raw, ensure_ascii=False, sort_keys=True)
            if fulltext_raw is not None
            else None
        )
        before = self.conn.total_changes
        self.conn.execute(
            """
            INSERT INTO posts(
              post_id, run_id, mblogid, user_id, screen_name, created_at, created_at_iso, text, source,
              list_text, full_text, text_source, is_long_text,
              reposts_count, comments_count, attitudes_count, detail_url, source_url,
              raw_json, fulltext_raw_json, first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
              mblogid=COALESCE(NULLIF(excluded.mblogid, ''), posts.mblogid),
              user_id=COALESCE(NULLIF(excluded.user_id, ''), posts.user_id),
              screen_name=COALESCE(NULLIF(excluded.screen_name, ''), posts.screen_name),
              created_at=COALESCE(NULLIF(excluded.created_at, ''), posts.created_at),
              created_at_iso=COALESCE(NULLIF(excluded.created_at_iso, ''), posts.created_at_iso),
              text=CASE
                WHEN NULLIF(excluded.full_text, '') IS NOT NULL THEN excluded.text
                WHEN NULLIF(posts.full_text, '') IS NOT NULL THEN posts.text
                ELSE excluded.text
              END,
              list_text=COALESCE(excluded.list_text, posts.list_text),
              full_text=COALESCE(NULLIF(excluded.full_text, ''), posts.full_text),
              text_source=CASE
                WHEN NULLIF(excluded.full_text, '') IS NOT NULL THEN excluded.text_source
                WHEN NULLIF(posts.full_text, '') IS NOT NULL THEN posts.text_source
                ELSE excluded.text_source
              END,
              is_long_text=CASE
                WHEN excluded.is_long_text = 1 OR posts.is_long_text = 1 THEN 1
                ELSE 0
              END,
              source=COALESCE(NULLIF(excluded.source, ''), posts.source),
              reposts_count=COALESCE(excluded.reposts_count, posts.reposts_count),
              comments_count=COALESCE(excluded.comments_count, posts.comments_count),
              attitudes_count=COALESCE(excluded.attitudes_count, posts.attitudes_count),
              detail_url=COALESCE(NULLIF(excluded.detail_url, ''), posts.detail_url),
              source_url=COALESCE(NULLIF(excluded.source_url, ''), posts.source_url),
              raw_json=CASE
                WHEN excluded.raw_json = '{}' THEN posts.raw_json
                ELSE excluded.raw_json
              END,
              fulltext_raw_json=COALESCE(excluded.fulltext_raw_json, posts.fulltext_raw_json),
              updated_at=excluded.updated_at
            """,
            (
                post_id,
                run_id,
                post.get("mblogid"),
                post.get("user_id"),
                post.get("screen_name"),
                post.get("created_at"),
                post.get("created_at_iso"),
                post.get("text"),
                post.get("source"),
                post.get("list_text"),
                post.get("full_text"),
                post.get("text_source"),
                1 if post.get("is_long_text") else 0,
                post.get("reposts_count"),
                post.get("comments_count"),
                post.get("attitudes_count"),
                post.get("detail_url") if isinstance(post.get("detail_url"), str) else None,
                post.get("source_url"),
                raw,
                fulltext_raw_json,
                now,
                now,
            ),
        )
        self.conn.commit()
        changed = self.conn.total_changes > before
        if changed:
            self.posts_jsonl.write(json.dumps({k: v for k, v in post.items() if k != "raw"}, ensure_ascii=False) + "\n")
            self.posts_jsonl.flush()
        return changed

    def save_comment(self, run_id: int, comment: dict[str, Any]) -> bool:
        comment_id = comment.get("comment_id")
        if not comment_id:
            return False
        now = utc_now()
        raw = json.dumps(comment.get("raw", {}), ensure_ascii=False, sort_keys=True)
        before = self.conn.total_changes
        self.conn.execute(
            """
            INSERT INTO comments(
              comment_id, run_id, post_id, root_id, parent_id, user_id, screen_name,
              created_at, text, like_count, source, source_url, raw_json, first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(comment_id) DO UPDATE SET
              post_id=excluded.post_id,
              root_id=excluded.root_id,
              parent_id=excluded.parent_id,
              user_id=excluded.user_id,
              screen_name=excluded.screen_name,
              created_at=excluded.created_at,
              text=excluded.text,
              like_count=excluded.like_count,
              source=excluded.source,
              source_url=excluded.source_url,
              raw_json=excluded.raw_json,
              updated_at=excluded.updated_at
            """,
            (
                comment_id,
                run_id,
                comment.get("post_id"),
                comment.get("root_id"),
                comment.get("parent_id"),
                comment.get("user_id"),
                comment.get("screen_name"),
                comment.get("created_at"),
                comment.get("text"),
                comment.get("like_count"),
                comment.get("source"),
                comment.get("source_url"),
                raw,
                now,
                now,
            ),
        )
        self.conn.commit()
        changed = self.conn.total_changes > before
        if changed:
            self.comments_jsonl.write(json.dumps({k: v for k, v in comment.items() if k != "raw"}, ensure_ascii=False) + "\n")
            self.comments_jsonl.flush()
        return changed

    def list_posts(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT post_id, mblogid, user_id, screen_name, created_at, text,
                   created_at_iso, list_text, full_text, text_source, is_long_text, source,
                   reposts_count, comments_count, attitudes_count, detail_url, source_url
            FROM posts
            ORDER BY rowid
        """
        params: tuple[Any, ...] = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "post_id": row[0],
                "mblogid": row[1],
                "user_id": row[2],
                "screen_name": row[3],
                "created_at": row[4],
                "text": row[5],
                "created_at_iso": row[6],
                "list_text": row[7],
                "full_text": row[8],
                "text_source": row[9],
                "is_long_text": bool(row[10]),
                "source": row[11],
                "reposts_count": row[12],
                "comments_count": row[13],
                "attitudes_count": row[14],
                "detail_url": row[15],
                "source_url": row[16],
            }
            for row in rows
        ]
