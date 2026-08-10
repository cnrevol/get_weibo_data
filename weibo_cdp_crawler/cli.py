from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .crawler import CrawlerConfig, WeiboCdpCrawler
from .dates import build_date_range


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weibo CDP crawler")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222", help="Chrome CDP endpoint")
    parser.add_argument("--out", default="data/weibo_run", help="Output directory")
    parser.add_argument("--max-posts", type=int, default=100, help="Maximum posts to collect")
    parser.add_argument("--month", help="Collect one month, for example 2026-07 or 2026年7月")
    parser.add_argument("--since", help="Start date/month, inclusive. Examples: 2024-01, 2024-01-15")
    parser.add_argument("--until", help="End date/month, inclusive for date/month input. Examples: 2025-02, 2025-02-28")
    parser.add_argument("--scroll-rounds", type=int, default=80, help="Maximum home page scroll rounds")
    parser.add_argument("--scroll-delay", type=float, default=1.5, help="Delay between post scrolls, seconds")
    parser.add_argument("--max-comments-per-post", type=int, default=200, help="Maximum comments per post")
    parser.add_argument("--comment-delay", type=float, default=2.0, help="Delay between comment requests, seconds")
    parser.add_argument("--comment-pages", type=int, default=50, help="Maximum comment pages per post")
    parser.add_argument("--skip-comments", action="store_true", help="Only collect posts")
    parser.add_argument("--no-fetch-fulltext", action="store_true", help="Disable full-text enrichment")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def configure_logging(out_dir: Path, verbose: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(out_dir / "run.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def main():
    args = parse_args()
    out_dir = Path(args.out)
    configure_logging(out_dir, args.verbose)
    date_range = build_date_range(month=args.month, since=args.since, until=args.until)
    config = CrawlerConfig(
        cdp=args.cdp,
        out=args.out,
        max_posts=args.max_posts,
        date_start=date_range.start.isoformat() if date_range.start else None,
        date_end=date_range.end.isoformat() if date_range.end else None,
        scroll_rounds=args.scroll_rounds,
        scroll_delay=args.scroll_delay,
        max_comments_per_post=args.max_comments_per_post,
        comment_delay=args.comment_delay,
        comment_pages=args.comment_pages,
        skip_comments=args.skip_comments,
        fetch_fulltext=not args.no_fetch_fulltext,
    )
    crawler = WeiboCdpCrawler(config)
    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
