"""Load and refresh the official Philippine nationwide holiday calendar.

Scheduled automation should skip Regular Holidays and Special (Non-Working)
Days, but it should continue on Special (Working) Days.  A verified calendar is
bundled for the current supported year, while later years are refreshed from
the Official Gazette when their annual calendar becomes available.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CALENDAR_FILE = APP_DIR / "philippine_holidays.json"
DEFAULT_CACHE_FILE = APP_DIR / ".philippine_holiday_cache.json"
OFFICIAL_GAZETTE_URL = (
    "https://www.officialgazette.gov.ph/nationwide-holidays/{year}/"
)
REFRESH_INTERVAL = timedelta(hours=24)
NETWORK_TIMEOUT_SECONDS = 5

REGULAR = "regular"
SPECIAL_NON_WORKING = "special_non_working"
SPECIAL_WORKING = "special_working"
VALID_TYPES = {REGULAR, SPECIAL_NON_WORKING, SPECIAL_WORKING}
NON_WORKING_TYPES = {REGULAR, SPECIAL_NON_WORKING}

MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
MONTH_PATTERN = "|".join(MONTH_NUMBERS)
DAY_FIRST_DATE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{MONTH_PATTERN})\b",
    re.IGNORECASE,
)
MONTH_FIRST_DATE = re.compile(
    rf"\b(?P<month>{MONTH_PATTERN})\s+"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str
    kind: str
    source_url: str

    @property
    def is_non_working(self) -> bool:
        return self.kind in NON_WORKING_TYPES

    @property
    def display_type(self) -> str:
        return {
            REGULAR: "Regular Holiday",
            SPECIAL_NON_WORKING: "Special (Non-Working) Holiday",
            SPECIAL_WORKING: "Special (Working) Holiday",
        }[self.kind]


@dataclass(frozen=True)
class HolidayCheck:
    day: date
    known_year: bool
    holiday: Holiday | None
    source_description: str
    refresh_warning: str | None = None

    @property
    def should_skip(self) -> bool:
        # An unknown year fails closed so the automation never guesses that a
        # date is a workday before the government publishes/verifies its list.
        return not self.known_year or bool(
            self.holiday and self.holiday.is_non_working
        )


class _VisibleBlockParser(HTMLParser):
    """Extract table rows and other visible text blocks from a holiday page."""

    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.table_rows: list[str] = []
        self._depth = 0
        self._parts: list[str] = []
        self._outer_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in self.BLOCK_TAGS:
            if self._depth == 0:
                self._parts = []
                self._outer_tag = tag.lower()
            self._depth += 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() not in self.BLOCK_TAGS or not self._depth:
            return
        self._depth -= 1
        if self._depth == 0:
            text = _clean_text(" ".join(self._parts))
            if text:
                self.blocks.append(text)
                if self._outer_tag == "tr":
                    self.table_rows.append(text)
            self._parts = []
            self._outer_tag = None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _category_from_text(value: str) -> str | None:
    normalized = _clean_text(value).lower().replace("–", "-").replace("—", "-")
    if "special (non-working)" in normalized or "special non-working" in normalized:
        return SPECIAL_NON_WORKING
    if "special (working)" in normalized or "special working" in normalized:
        return SPECIAL_WORKING
    if re.search(r"\bregular holidays?\b", normalized):
        return REGULAR
    return None


def _date_match(value: str) -> re.Match[str] | None:
    return DAY_FIRST_DATE.search(value) or MONTH_FIRST_DATE.search(value)


def _holiday_name(block: str, match: re.Match[str], kind: str) -> str:
    candidate = _clean_text(f"{block[:match.start()]} {block[match.end():]}")
    candidate = re.sub(r"\([^)]*\)", " ", candidate)
    candidate = re.sub(
        r"\b(?:additional\s+)?special\s*\((?:non-)?working\)\s*days?\b",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\b(?:additional\s+)?special\s+(?:non-)?working\s+days?\b",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bregular holidays?\b", " ", candidate, flags=re.IGNORECASE
    )
    candidate = re.sub(r"\b20\d{2}\b", " ", candidate)
    candidate = _clean_text(candidate.strip(" -|:,."))
    if candidate:
        return candidate
    return {
        REGULAR: "Unnamed Regular Holiday",
        SPECIAL_NON_WORKING: "Unnamed Special (Non-Working) Holiday",
        SPECIAL_WORKING: "Unnamed Special (Working) Holiday",
    }[kind]


def parse_official_gazette_html(
    html_text: str,
    year: int,
    source_url: str,
) -> list[Holiday]:
    """Parse the categorized annual nationwide holiday table from HTML."""
    parser = _VisibleBlockParser()
    parser.feed(html_text)

    # Annual calendars are normally tables. Prefer their rows so prose dates
    # such as signing/publication dates cannot be mistaken for holidays.
    candidate_blocks = parser.table_rows or parser.blocks

    current_kind: str | None = None
    holidays_by_day: dict[date, Holiday] = {}
    for block in candidate_blocks:
        category = _category_from_text(block)
        match = _date_match(block)
        if category:
            current_kind = category
        if not match or not current_kind:
            continue

        day_number = int(match.group("day"))
        month_number = MONTH_NUMBERS[match.group("month").lower()]
        try:
            holiday_day = date(year, month_number, day_number)
        except ValueError:
            continue

        kind = category or current_kind
        holiday = Holiday(
            day=holiday_day,
            name=_holiday_name(block, match, kind),
            kind=kind,
            source_url=source_url,
        )
        existing = holidays_by_day.get(holiday_day)
        if existing is None or holiday.is_non_working or not existing.is_non_working:
            holidays_by_day[holiday_day] = holiday

    holidays = sorted(holidays_by_day.values(), key=lambda item: item.day)
    regular_count = sum(item.kind == REGULAR for item in holidays)
    special_non_working_count = sum(
        item.kind == SPECIAL_NON_WORKING for item in holidays
    )
    if regular_count < 10 or special_non_working_count < 4:
        raise ValueError(
            "The Official Gazette page did not contain a complete categorized "
            f"calendar for {year}."
        )
    return holidays


def _holiday_from_record(record: dict[str, Any], source_url: str) -> Holiday:
    kind = str(record.get("type", ""))
    if kind not in VALID_TYPES:
        raise ValueError(f"Unsupported holiday type: {kind!r}")
    holiday_day = date.fromisoformat(str(record["date"]))
    name = _clean_text(str(record.get("name", "")))
    if not name:
        raise ValueError(f"Holiday {holiday_day.isoformat()} has no name.")
    record_source = _clean_text(str(record.get("source_url", source_url)))
    return Holiday(holiday_day, name, kind, record_source)


def _read_calendar(path: Path) -> tuple[dict[int, dict[date, Holiday]], set[int]]:
    if not path.is_file():
        return {}, set()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("years"), dict):
        raise ValueError(f"Unsupported holiday calendar format in {path.name}.")

    calendars: dict[int, dict[date, Holiday]] = {}
    complete_years: set[int] = set()
    for year_text, year_record in payload["years"].items():
        year = int(year_text)
        if not isinstance(year_record, dict):
            raise ValueError(f"Invalid calendar entry for {year} in {path.name}.")
        source_urls = year_record.get("source_urls") or []
        source_url = str(source_urls[0]) if source_urls else ""
        holidays = {
            holiday.day: holiday
            for holiday in (
                _holiday_from_record(record, source_url)
                for record in year_record.get("holidays", [])
            )
        }
        if any(holiday_day.year != year for holiday_day in holidays):
            raise ValueError(f"A holiday is stored under the wrong year in {path.name}.")
        calendars[year] = holidays
        if year_record.get("status") == "official" and holidays:
            complete_years.add(year)
    return calendars, complete_years


def _read_cache_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "years": {}, "refresh": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("schema_version") != 1:
            raise ValueError
        if not isinstance(payload.get("years"), dict):
            raise ValueError
        if not isinstance(payload.get("refresh"), dict):
            payload["refresh"] = {}
        return payload
    except (OSError, ValueError, json.JSONDecodeError):
        return {"schema_version": 1, "years": {}, "refresh": {}}


def _write_cache_payload(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _should_refresh(payload: dict[str, Any], year: int, now_utc: datetime) -> bool:
    refresh_record = payload.get("refresh", {}).get(str(year), {})
    attempted_at = _parse_utc_timestamp(refresh_record.get("attempted_at"))
    return attempted_at is None or now_utc - attempted_at >= REFRESH_INTERVAL


def fetch_official_calendar(year: int) -> tuple[list[Holiday], str]:
    """Download and validate one annual nationwide calendar."""
    source_url = OFFICIAL_GAZETTE_URL.format(year=year)
    request = Request(
        source_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-PH,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0 Safari/537.36"
            ),
        },
    )
    with urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        html_text = response.read().decode(content_type, errors="replace")
    return parse_official_gazette_html(html_text, year, source_url), source_url


def _refresh_year(
    year: int,
    cache_path: Path,
    payload: dict[str, Any],
    now_utc: datetime,
) -> tuple[dict[str, Any], str | None]:
    attempted_at = now_utc.isoformat().replace("+00:00", "Z")
    refresh_record: dict[str, Any] = {"attempted_at": attempted_at}
    warning: str | None = None
    try:
        holidays, source_url = fetch_official_calendar(year)
        payload.setdefault("years", {})[str(year)] = {
            "status": "official",
            "retrieved_at": attempted_at,
            "source_urls": [source_url],
            "holidays": [
                {
                    "date": holiday.day.isoformat(),
                    "name": holiday.name,
                    "type": holiday.kind,
                    "source_url": holiday.source_url,
                }
                for holiday in holidays
            ],
        }
        refresh_record["succeeded_at"] = attempted_at
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        warning = (
            f"Could not refresh the {year} Official Gazette holiday calendar "
            f"({error})."
        )
        refresh_record["error"] = str(error)

    payload.setdefault("refresh", {})[str(year)] = refresh_record
    try:
        _write_cache_payload(cache_path, payload)
    except OSError as error:
        cache_warning = f"Could not save the holiday refresh cache ({error})."
        warning = f"{warning} {cache_warning}" if warning else cache_warning
    return payload, warning


def check_philippine_holiday(
    day: date,
    *,
    refresh: bool = True,
    calendar_path: Path = DEFAULT_CALENDAR_FILE,
    cache_path: Path = DEFAULT_CACHE_FILE,
    now_utc: datetime | None = None,
) -> HolidayCheck:
    """Return the nationwide work status for a date using verified year data."""
    now_utc = now_utc or datetime.now(timezone.utc)
    bundled, bundled_complete = _read_calendar(calendar_path)
    cache_payload = _read_cache_payload(cache_path)

    refresh_warnings: list[str] = []
    if refresh and _should_refresh(cache_payload, day.year, now_utc):
        cache_payload, warning = _refresh_year(
            day.year,
            cache_path,
            cache_payload,
            now_utc,
        )
        if warning:
            refresh_warnings.append(warning)

    # Annual lists are commonly released before year-end. From September on,
    # prefetch the following year so January does not depend on a last-minute
    # download at the scheduled send time.
    next_year = day.year + 1
    if (
        refresh
        and day.month >= 9
        and _should_refresh(cache_payload, next_year, now_utc)
    ):
        cache_payload, warning = _refresh_year(
            next_year,
            cache_path,
            cache_payload,
            now_utc,
        )
        if warning:
            refresh_warnings.append(warning)

    refresh_warning = " ".join(refresh_warnings) or None

    cached: dict[int, dict[date, Holiday]] = {}
    cached_complete: set[int] = set()
    try:
        cached, cached_complete = _read_calendar(cache_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        refresh_warning = (
            f"{refresh_warning} The holiday cache is invalid ({error})."
            if refresh_warning
            else f"The holiday cache is invalid ({error})."
        )

    holidays = dict(bundled.get(day.year, {}))
    holidays.update(cached.get(day.year, {}))
    known_year = day.year in bundled_complete or day.year in cached_complete
    sources: list[str] = []
    if day.year in bundled_complete:
        sources.append("bundled official calendar")
    if day.year in cached_complete:
        sources.append("Official Gazette refresh cache")
    source_description = " + ".join(sources) if sources else "no verified calendar"

    return HolidayCheck(
        day=day,
        known_year=known_year,
        holiday=holidays.get(day),
        source_description=source_description,
        refresh_warning=refresh_warning,
    )
