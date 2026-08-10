from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


DATE_PATTERNS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%m-%d %H:%M",
    "%m-%d",
)

YEAR = "\u5e74"
MONTH = "\u6708"
DAY = "\u65e5"
JUST_NOW = "\u521a\u521a"
MINUTES_AGO = "\u5206\u949f\u524d"
HOURS_AGO = "\u5c0f\u65f6\u524d"
TODAY = "\u4eca\u5929"
YESTERDAY = "\u6628\u5929"


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        return start, datetime(year + 1, 1, 1)
    return start, datetime(year, month + 1, 1)


def parse_month(value: str) -> tuple[int, int]:
    raw = value.strip()
    match = re.fullmatch(rf"(\d{{4}})(?:[-/]|{YEAR})(\d{{1,2}}){MONTH}?", raw)
    if not match:
        raise ValueError(f"Invalid month: {value}. Expected YYYY-MM or YYYY year/month.")
    year = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month: {value}")
    return year, month


def normalize_date_text(value: str) -> str:
    return (
        value.replace(YEAR, "-")
        .replace(MONTH, "-")
        .replace(DAY, "")
        .replace("/", "-")
        .strip("- ")
    )


def parse_boundary(value: str, *, is_end: bool) -> datetime:
    raw = value.strip()
    if re.fullmatch(rf"\d{{4}}(?:[-/]|{YEAR})\d{{1,2}}{MONTH}?", raw):
        year, month = parse_month(raw)
        start, end = month_bounds(year, month)
        return end if is_end else start

    normalized = normalize_date_text(raw)
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, pattern)
            if is_end and pattern == "%Y-%m-%d":
                return parsed + timedelta(days=1)
            return parsed
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value}. Expected YYYY-MM or YYYY-MM-DD.")


@dataclass(frozen=True)
class DateRange:
    start: datetime | None = None
    end: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self.start is not None or self.end is not None

    def contains(self, value: datetime | None) -> bool:
        if value is None:
            return not self.enabled
        if self.start is not None and value < self.start:
            return False
        if self.end is not None and value >= self.end:
            return False
        return True

    def before_start(self, value: datetime | None) -> bool:
        return value is not None and self.start is not None and value < self.start

    def after_or_at_end(self, value: datetime | None) -> bool:
        return value is not None and self.end is not None and value >= self.end

    def label(self) -> str:
        start = self.start.isoformat(sep=" ") if self.start else "-inf"
        end = self.end.isoformat(sep=" ") if self.end else "+inf"
        return f"[{start}, {end})"


def build_date_range(month: str | None = None, since: str | None = None, until: str | None = None) -> DateRange:
    if month and (since or until):
        raise ValueError("Use either --month or --since/--until, not both.")
    if month:
        year, month_num = parse_month(month)
        start, end = month_bounds(year, month_num)
        return DateRange(start=start, end=end)
    start = parse_boundary(since, is_end=False) if since else None
    end = parse_boundary(until, is_end=True) if until else None
    if start and end and start >= end:
        raise ValueError("--since must be earlier than --until.")
    return DateRange(start=start, end=end)


def parse_weibo_datetime(value: object, *, now: datetime | None = None) -> datetime | None:
    if value is None:
        return None
    now = now or datetime.now()
    raw = str(value).strip()
    if not raw:
        return None

    if raw == JUST_NOW:
        return now.replace(second=0, microsecond=0)

    match = re.fullmatch(rf"(\d+)\s*{MINUTES_AGO}", raw)
    if match:
        return (now - timedelta(minutes=int(match.group(1)))).replace(second=0, microsecond=0)

    match = re.fullmatch(rf"(\d+)\s*{HOURS_AGO}", raw)
    if match:
        return (now - timedelta(hours=int(match.group(1)))).replace(second=0, microsecond=0)

    match = re.fullmatch(rf"{TODAY}\s+(\d{{1,2}}):(\d{{2}})", raw)
    if match:
        return now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)

    match = re.fullmatch(rf"{YESTERDAY}\s+(\d{{1,2}}):(\d{{2}})", raw)
    if match:
        base = now - timedelta(days=1)
        return base.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)

    normalized = re.sub(r"\s+", " ", normalize_date_text(raw))
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(normalized, pattern)
            if pattern.startswith("%m-"):
                parsed = parsed.replace(year=now.year)
            return parsed
        except ValueError:
            continue

    try:
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").replace(tzinfo=None)
    except ValueError:
        return None
