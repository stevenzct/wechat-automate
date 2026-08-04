import tempfile
import unittest
from datetime import date
from pathlib import Path

from philippine_holidays import (
    REGULAR,
    SPECIAL_NON_WORKING,
    SPECIAL_WORKING,
    check_philippine_holiday,
    parse_official_gazette_html,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


class BundledCalendarTests(unittest.TestCase):
    def check_day(self, value: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            return check_philippine_holiday(
                date.fromisoformat(value),
                refresh=False,
                calendar_path=PROJECT_DIR / "philippine_holidays.json",
                cache_path=Path(temporary_directory) / "cache.json",
            )

    def test_regular_holiday_is_skipped(self):
        result = self.check_day("2026-03-20")
        self.assertTrue(result.known_year)
        self.assertTrue(result.should_skip)
        self.assertEqual(result.holiday.kind, REGULAR)

    def test_special_non_working_holiday_is_skipped(self):
        result = self.check_day("2026-12-24")
        self.assertTrue(result.should_skip)
        self.assertEqual(result.holiday.kind, SPECIAL_NON_WORKING)

    def test_special_working_holiday_continues(self):
        result = self.check_day("2026-02-25")
        self.assertFalse(result.should_skip)
        self.assertEqual(result.holiday.kind, SPECIAL_WORKING)

    def test_ordinary_workday_continues(self):
        result = self.check_day("2026-08-04")
        self.assertFalse(result.should_skip)
        self.assertIsNone(result.holiday)

    def test_unknown_year_fails_closed(self):
        result = self.check_day("2027-01-04")
        self.assertFalse(result.known_year)
        self.assertTrue(result.should_skip)


class OfficialGazetteParserTests(unittest.TestCase):
    def test_categorized_table(self):
        regular_rows = "".join(
            f"<tr><td>Regular Holiday {day}</td><td>{day} January</td></tr>"
            for day in range(1, 11)
        )
        html = f"""
            <p>Proclamation signed on 3 September 2026.</p>
            <table>
              <tr><th>A. Regular Holidays</th></tr>
              {regular_rows}
              <tr><th>B. Special (Non-Working) Days</th></tr>
              <tr><td>Special One</td><td>1 February</td></tr>
              <tr><td>Special Two</td><td>2 February</td></tr>
              <tr><td>Special Three</td><td>3 February</td></tr>
              <tr><td>Special Four</td><td>4 February</td></tr>
              <tr><th>C. Special (Working) Day</th></tr>
              <tr><td>Working Celebration</td><td>25 February</td></tr>
            </table>
        """
        holidays = parse_official_gazette_html(
            html,
            2027,
            "https://www.officialgazette.gov.ph/nationwide-holidays/2027/",
        )
        by_day = {holiday.day: holiday for holiday in holidays}
        self.assertEqual(by_day[date(2027, 1, 1)].kind, REGULAR)
        self.assertEqual(by_day[date(2027, 2, 1)].kind, SPECIAL_NON_WORKING)
        self.assertEqual(by_day[date(2027, 2, 25)].kind, SPECIAL_WORKING)
        self.assertNotIn(date(2027, 9, 3), by_day)


if __name__ == "__main__":
    unittest.main()
