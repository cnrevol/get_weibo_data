from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = html.unescape(text)
    text = TAG_RE.sub("", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_dicts(item)


def url_query(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    raw = parse_qs(parsed.query)
    return {key: values[-1] for key, values in raw.items() if values}


def first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def is_post_candidate(item: dict[str, Any]) -> bool:
    if "mblog" in item and isinstance(item["mblog"], dict):
        return False
    has_id = any(key in item for key in ("id", "idstr", "mid", "mblogid"))
    has_text = any(key in item for key in ("text", "text_raw", "longTextContent"))
    has_post_signal = any(
        key in item
        for key in (
            "reposts_count",
            "comments_count",
            "attitudes_count",
            "visible",
            "mblogtype",
            "bid",
        )
    )
    return has_id and has_text and has_post_signal


def is_comment_candidate(item: dict[str, Any]) -> bool:
    has_id = any(key in item for key in ("id", "idstr"))
    has_text = any(key in item for key in ("text", "text_raw"))
    has_user = isinstance(item.get("user"), dict)
    comment_signal = any(
        key in item
        for key in (
            "like_count",
            "rootid",
            "rootidstr",
            "reply_comment",
            "floor_number",
            "total_number",
        )
    )
    post_signal = any(key in item for key in ("reposts_count", "comments_count", "attitudes_count"))
    return has_id and has_text and has_user and comment_signal and not post_signal


def normalize_user(user: Any) -> dict[str, Any]:
    if not isinstance(user, dict):
        return {"user_id": None, "screen_name": None, "profile_url": None}
    return {
        "user_id": first_present(user, "idstr", "id", "uid"),
        "screen_name": first_present(user, "screen_name", "name"),
        "profile_url": first_present(user, "profile_url", "profile_url_hd", "avatar_hd"),
    }


def normalize_post(item: dict[str, Any], source_url: str | None = None) -> dict[str, Any]:
    if "mblog" in item and isinstance(item["mblog"], dict):
        item = item["mblog"]
    user = normalize_user(item.get("user"))
    post_id = first_present(item, "idstr", "id", "mid")
    text = first_present(item, "text_raw", "longTextContent", "text")
    full_text = extract_long_text(item)
    return {
        "post_id": str(post_id) if post_id is not None else None,
        "mblogid": first_present(item, "mblogid", "bid"),
        "user_id": user["user_id"],
        "screen_name": user["screen_name"],
        "created_at": first_present(item, "created_at", "created_time"),
        "list_text": clean_text(text),
        "full_text": full_text,
        "text": full_text or clean_text(text),
        "text_source": "full_text" if full_text else "list",
        "is_long_text": bool(first_present(item, "isLongText", "is_long_text")) or bool(full_text),
        "source": clean_text(first_present(item, "source", "region_name")),
        "reposts_count": first_present(item, "reposts_count"),
        "comments_count": first_present(item, "comments_count"),
        "attitudes_count": first_present(item, "attitudes_count"),
        "detail_url": first_present(item, "scheme", "url_struct"),
        "source_url": source_url,
        "raw": item,
    }


def normalize_comment(
    item: dict[str, Any],
    source_url: str | None = None,
    fallback_post_id: str | None = None,
) -> dict[str, Any]:
    user = normalize_user(item.get("user"))
    query = url_query(source_url or "")
    post_id = first_present(item, "status_id", "mid", "post_id") or query.get("id") or fallback_post_id
    parent = item.get("reply_comment") if isinstance(item.get("reply_comment"), dict) else {}
    return {
        "comment_id": str(first_present(item, "idstr", "id")),
        "post_id": str(post_id) if post_id is not None else None,
        "root_id": first_present(item, "rootidstr", "rootid"),
        "parent_id": first_present(parent, "idstr", "id"),
        "user_id": user["user_id"],
        "screen_name": user["screen_name"],
        "created_at": first_present(item, "created_at", "created_time"),
        "text": clean_text(first_present(item, "text_raw", "text")),
        "like_count": first_present(item, "like_count"),
        "source": clean_text(first_present(item, "source")),
        "source_url": source_url,
        "raw": item,
    }


def extract_posts(payload: Any, source_url: str | None = None) -> list[dict[str, Any]]:
    posts: dict[str, dict[str, Any]] = {}
    for item in walk_dicts(payload):
        candidates = []
        if "mblog" in item and isinstance(item["mblog"], dict):
            candidates.append(item["mblog"])
        if is_post_candidate(item):
            candidates.append(item)
        for candidate in candidates:
            normalized = normalize_post(candidate, source_url)
            post_id = normalized.get("post_id")
            if post_id:
                posts[post_id] = normalized
    return list(posts.values())


def extract_long_text(payload: Any) -> str:
    candidates: list[str] = []
    for item in walk_dicts(payload):
        for key in ("longTextContent", "fullText", "full_text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(clean_text(value))
        data = item.get("data")
        if isinstance(data, dict):
            value = data.get("longTextContent")
            if isinstance(value, str) and value.strip():
                candidates.append(clean_text(value))
    if not candidates:
        return ""
    return max(candidates, key=len)


def extract_comments(
    payload: Any,
    source_url: str | None = None,
    fallback_post_id: str | None = None,
) -> list[dict[str, Any]]:
    comments: dict[str, dict[str, Any]] = {}
    for item in walk_dicts(payload):
        if is_comment_candidate(item):
            normalized = normalize_comment(item, source_url, fallback_post_id)
            comment_id = normalized.get("comment_id")
            if comment_id:
                comments[comment_id] = normalized
    return list(comments.values())


def classify_url(url: str) -> str:
    lower = url.lower()
    if "comment" in lower or "buildcomments" in lower or "hotflow" in lower:
        return "comments"
    if "mblog" in lower or "container/getindex" in lower or "profile" in lower or "statuses" in lower:
        return "posts"
    return "json"


def post_detail_urls(post: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    detail = post.get("detail_url")
    if isinstance(detail, str) and detail.startswith("http"):
        urls.append(detail)
    user_id = post.get("user_id")
    mblogid = post.get("mblogid")
    post_id = post.get("post_id")
    if user_id and mblogid:
        urls.append(f"https://weibo.com/{user_id}/{mblogid}")
    if mblogid:
        urls.append(f"https://m.weibo.cn/status/{mblogid}")
    if post_id:
        urls.append(f"https://m.weibo.cn/detail/{post_id}")
    seen = set()
    result = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


@dataclass
class CommentPage:
    comments: list[dict[str, Any]]
    next_max_id: str | None
    next_max_id_type: str | None


def parse_comment_page(payload: Any, source_url: str, fallback_post_id: str) -> CommentPage:
    comments = extract_comments(payload, source_url, fallback_post_id)
    next_max_id = None
    next_max_id_type = None
    for item in walk_dicts(payload):
        if not isinstance(item, dict):
            continue
        if next_max_id is None:
            next_max_id = first_present(item, "max_id", "next_cursor")
        if next_max_id_type is None:
            next_max_id_type = first_present(item, "max_id_type")
    if next_max_id in (0, "0", ""):
        next_max_id = None
    return CommentPage(comments=comments, next_max_id=str(next_max_id) if next_max_id else None, next_max_id_type=str(next_max_id_type) if next_max_id_type else None)
