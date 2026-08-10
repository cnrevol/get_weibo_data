from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import Browser, BrowserContext, Page, Response, async_playwright

from .extractors import (
    classify_url,
    extract_comments,
    extract_long_text,
    extract_posts,
    parse_comment_page,
    post_detail_urls,
)
from .storage import Storage


LOG = logging.getLogger("weibo_cdp_crawler")


@dataclass
class CrawlerConfig:
    cdp: str = "http://127.0.0.1:9222"
    out: str = "data/weibo_run"
    max_posts: int = 100
    scroll_rounds: int = 80
    scroll_delay: float = 1.5
    max_comments_per_post: int = 200
    comment_delay: float = 2.0
    comment_pages: int = 50
    skip_comments: bool = False
    fetch_fulltext: bool = True
    headless_attach_timeout: float = 30.0


class WeiboCdpCrawler:
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.storage = Storage(Path(config.out))
        self.run_id: int | None = None
        self.posts_seen: set[str] = set()
        self.comments_seen: set[str] = set()
        self.target_url: str | None = None

    async def run(self):
        async with async_playwright() as p:
            LOG.info("Connecting to Chrome CDP: %s", self.config.cdp)
            browser = await p.chromium.connect_over_cdp(self.config.cdp, timeout=self.config.headless_attach_timeout * 1000)
            try:
                context = self._select_context(browser)
                page = await self._select_page(context)
                self.target_url = page.url
                self.run_id = self.storage.create_run(self.target_url, asdict(self.config))
                page.on("response", lambda response: asyncio.create_task(self._on_response(response)))

                LOG.info("Target page: %s", page.url)
                input("Confirm the target Weibo account page in Chrome, then press Enter to start...")

                await self.collect_posts(page)
                if self.config.fetch_fulltext:
                    await self.collect_fulltexts(context)
                if not self.config.skip_comments:
                    await self.collect_comments(context)
                self.storage.finish_run(self.run_id, "finished")
            except Exception:
                if self.run_id is not None:
                    self.storage.finish_run(self.run_id, "failed")
                raise
            finally:
                self.storage.close()
                await browser.close()

    def _select_context(self, browser: Browser) -> BrowserContext:
        if not browser.contexts:
            raise RuntimeError("No Chrome context found. Start Chrome with remote debugging and open Weibo first.")
        return browser.contexts[0]

    async def _select_page(self, context: BrowserContext) -> Page:
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return await context.new_page()
        for page in reversed(pages):
            if "weibo" in page.url.lower():
                await page.bring_to_front()
                return page
        page = pages[-1]
        await page.bring_to_front()
        return page

    async def _on_response(self, response: Response):
        if self.run_id is None:
            return
        url = response.url
        if "weibo" not in url.lower():
            return
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type and "javascript" not in content_type and "text/plain" not in content_type:
            return
        try:
            payload = await response.json()
        except Exception:
            return

        kind = classify_url(url)
        self.storage.save_raw_response(self.run_id, kind, url, payload)

        post_count = 0
        for post in extract_posts(payload, url):
            if self.storage.save_post(self.run_id, post):
                post_count += 1
            if post.get("post_id"):
                self.posts_seen.add(post["post_id"])

        comment_count = 0
        for comment in extract_comments(payload, url):
            if self.storage.save_comment(self.run_id, comment):
                comment_count += 1
            if comment.get("comment_id"):
                self.comments_seen.add(comment["comment_id"])

        if post_count or comment_count:
            LOG.info("Captured %s posts, %s comments from %s", post_count, comment_count, url)

    async def collect_posts(self, page: Page):
        LOG.info("Collecting posts by network capture and page scroll.")
        last_count = 0
        stagnant_rounds = 0
        for idx in range(self.config.scroll_rounds):
            if len(self.posts_seen) >= self.config.max_posts:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(int(self.config.scroll_delay * 1000))
            current = len(self.posts_seen)
            LOG.info("Post scroll %s/%s, posts=%s", idx + 1, self.config.scroll_rounds, current)
            if current == last_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            last_count = current
            if stagnant_rounds >= 8:
                LOG.info("Post count has not changed for 8 rounds; stopping post scroll.")
                break

    async def collect_comments(self, context: BrowserContext):
        posts = self.storage.list_posts(limit=self.config.max_posts)
        LOG.info("Collecting comments for %s posts.", len(posts))
        for idx, post in enumerate(posts, start=1):
            post_id = post.get("post_id")
            if not post_id:
                continue
            LOG.info("Comments %s/%s for post_id=%s", idx, len(posts), post_id)
            fetched = await self._fetch_comments_direct(context, post)
            if fetched == 0:
                await self._fetch_comments_by_detail_page(context, post)
            await asyncio.sleep(self.config.comment_delay)

    async def collect_fulltexts(self, context: BrowserContext):
        posts = self.storage.list_posts(limit=self.config.max_posts)
        LOG.info("Fetching full text for %s posts.", len(posts))
        for idx, post in enumerate(posts, start=1):
            post_id = post.get("post_id")
            if not post_id:
                continue
            if post.get("full_text"):
                continue
            LOG.info("Full text %s/%s for post_id=%s", idx, len(posts), post_id)
            fulltext_result = await self._fetch_fulltext_direct(context, post)
            if fulltext_result and self.run_id is not None:
                updated = {
                    **post,
                    "text": fulltext_result["text"],
                    "full_text": fulltext_result["text"],
                    "list_text": post.get("list_text") or post.get("text") or "",
                    "text_source": "full_text",
                    "is_long_text": True,
                    "raw": {},
                    "fulltext_raw": fulltext_result["payload"],
                }
                self.storage.save_post(self.run_id, updated)
            await asyncio.sleep(max(0.5, self.config.comment_delay / 2))

    async def _fetch_fulltext_direct(self, context: BrowserContext, post: dict[str, Any]) -> dict[str, Any] | None:
        if self.run_id is None:
            return None
        ids = []
        for key in ("post_id", "mblogid"):
            value = post.get(key)
            if value and str(value) not in ids:
                ids.append(str(value))
        urls = []
        for value in ids:
            urls.extend(
                [
                    f"https://weibo.com/ajax/statuses/longtext?id={value}",
                    f"https://m.weibo.cn/statuses/extend?id={value}",
                ]
            )

        best_text = ""
        best_payload: Any = None
        best_url = ""
        for url in urls:
            try:
                response = await context.request.get(url, headers={"referer": self.target_url or "https://weibo.com/"}, timeout=30000)
                if not response.ok:
                    LOG.debug("Full text request status=%s url=%s", response.status, url)
                    continue
                payload = await response.json()
            except Exception as exc:
                LOG.debug("Full text request failed url=%s error=%s", url, exc)
                continue
            self.storage.save_raw_response(self.run_id, "fulltext", url, payload)
            candidate = extract_long_text(payload)
            if len(candidate) > len(best_text):
                best_text = candidate
                best_payload = payload
                best_url = url
        if best_text:
            LOG.info("Full text fetched post_id=%s chars=%s", post.get("post_id"), len(best_text))
            return {"text": best_text, "payload": best_payload, "url": best_url}
        return None

    async def _fetch_comments_direct(self, context: BrowserContext, post: dict[str, Any]) -> int:
        if self.run_id is None:
            return 0
        post_id = str(post["post_id"])
        user_id = post.get("user_id") or ""
        total = 0

        endpoint = "https://weibo.com/ajax/statuses/buildComments"
        max_id = ""
        for page_no in range(self.config.comment_pages):
            params = {
                "is_reload": "1" if page_no == 0 else "0",
                "id": post_id,
                "is_show_bulletin": "2",
                "is_mix": "0",
                "count": "20",
                "uid": user_id,
                "fetch_level": "0",
                "locale": "zh-CN",
            }
            if max_id:
                params["max_id"] = max_id
            url = f"{endpoint}?{urlencode(params)}"
            try:
                response = await context.request.get(url, headers={"referer": self.target_url or "https://weibo.com/"}, timeout=30000)
                if not response.ok:
                    LOG.warning("Comment request failed status=%s url=%s", response.status, url)
                    break
                payload = await response.json()
            except Exception as exc:
                LOG.warning("Comment request failed for post_id=%s: %s", post_id, exc)
                break

            self.storage.save_raw_response(self.run_id, "comments", url, payload)
            page = parse_comment_page(payload, url, post_id)
            new_comments = 0
            for comment in page.comments:
                if self.storage.save_comment(self.run_id, comment):
                    new_comments += 1
                    total += 1
                if comment.get("comment_id"):
                    self.comments_seen.add(comment["comment_id"])

            LOG.info("Direct comments page=%s post_id=%s new=%s total=%s", page_no + 1, post_id, new_comments, total)
            if total >= self.config.max_comments_per_post:
                break
            if not page.next_max_id or new_comments == 0:
                break
            max_id = page.next_max_id
            await asyncio.sleep(self.config.comment_delay)
        return total

    async def _fetch_comments_by_detail_page(self, context: BrowserContext, post: dict[str, Any]) -> int:
        before = len(self.comments_seen)
        urls = post_detail_urls(post)
        if not urls:
            return 0
        page = await context.new_page()
        page.on("response", lambda response: asyncio.create_task(self._on_response(response)))
        try:
            for url in urls[:2]:
                try:
                    LOG.info("Fallback detail page for comments: %s", url)
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    for _ in range(min(12, self.config.comment_pages)):
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(int(self.config.comment_delay * 1000))
                        if len(self.comments_seen) - before >= self.config.max_comments_per_post:
                            break
                    if len(self.comments_seen) > before:
                        break
                except Exception as exc:
                    LOG.warning("Detail fallback failed url=%s error=%s", url, exc)
        finally:
            await page.close()
        return len(self.comments_seen) - before
