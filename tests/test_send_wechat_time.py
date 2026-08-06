import argparse
import sys
import tempfile
import unittest
from datetime import date, datetime, time as clock_time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import send_wechat_time as sender
from philippine_holidays import HolidayCheck


class TimeInMarkerTests(unittest.TestCase):
    def test_record_time_in_sent_atomically_replaces_marker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            marker_path = directory / ".wechat_last_time_in"
            marker_path.write_text("2026-08-05\n", encoding="ascii")

            sender.record_time_in_sent(date(2026, 8, 6), marker_path)

            self.assertEqual(marker_path.read_text(encoding="ascii"), "2026-08-06\n")
            self.assertEqual(
                list(directory.glob(".wechat_last_time_in.*.tmp")),
                [],
            )

    def test_time_in_was_sent_on_matches_only_the_recorded_date(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"
            marker_path.write_text("2026-08-06\n", encoding="ascii")

            self.assertTrue(sender.time_in_was_sent_on(date(2026, 8, 6), marker_path))
            self.assertFalse(sender.time_in_was_sent_on(date(2026, 8, 7), marker_path))


class AutomaticWorkdayRuleTests(unittest.TestCase):
    def test_unknown_holiday_year_fails_closed(self):
        checked_day = date(2027, 1, 4)
        unknown_year = HolidayCheck(
            day=checked_day,
            known_year=False,
            holiday=None,
            source_description="no verified calendar",
        )

        with patch.object(
            sender,
            "check_philippine_holiday",
            return_value=unknown_year,
        ), self.assertLogs(level="WARNING"):
            self.assertFalse(sender.philippine_holiday_rule_allows(checked_day))


class DraftDeliveryTests(unittest.TestCase):
    def test_draft_only_never_invokes_wechat_send_shortcut(self):
        screenshot = object()
        automation = Mock()

        with (
            patch.object(sender, "activate_wechat", return_value=123),
            patch.object(sender, "ensure_wechat_has_focus"),
            patch.object(sender, "paste_text"),
            patch.object(sender, "copy_image_to_clipboard"),
            patch.object(sender, "pyautogui", automation),
            patch.object(sender.time, "sleep"),
        ):
            sender.deliver_screenshot(
                screenshot,
                "Attendance Recording",
                draft_only=True,
            )

        automation.hotkey.assert_has_calls(
            [call("ctrl", "f"), call("ctrl", "a"), call("ctrl", "v")]
        )
        self.assertNotIn(call("alt", "s"), automation.hotkey.mock_calls)


class TimeInModeTests(unittest.TestCase):
    @staticmethod
    def time_in_args(*, draft_only: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            scheduled=False,
            time_in=True,
            send_now=False,
            preview=False,
            check=False,
            contact="Attendance Recording",
            send_time=clock_time(18, 0),
            grace_minutes=0,
            draft_only=draft_only,
            weekdays_only=False,
            full_screen=False,
            capture_width=500,
            capture_height=660,
            output=Path("unused-preview.png"),
        )

    def run_time_in(
        self,
        marker_path: Path,
        *,
        now: datetime,
        refreshed_now: datetime | None = None,
        draft_only: bool = False,
        holiday_allowed: bool = True,
        delivery_error: Exception | None = None,
    ):
        arguments = self.time_in_args(draft_only=draft_only)
        screenshot = object()
        capture = Mock(return_value=screenshot)
        delivery = Mock(side_effect=delivery_error)
        holiday_gate = Mock(return_value=holiday_allowed)
        datetime_api = Mock()
        if refreshed_now is None:
            datetime_api.now.return_value = now
        else:
            datetime_api.now.side_effect = [now, refreshed_now]
        kernel32 = SimpleNamespace(CloseHandle=Mock(return_value=True))

        with (
            patch.object(sender, "parse_args", return_value=arguments),
            patch.object(sender, "configure_logging"),
            patch.object(sender, "configure_dpi_awareness"),
            patch.object(sender, "acquire_single_instance_mutex", return_value=123),
            patch.object(sender, "KERNEL32", kernel32),
            patch.object(sender, "datetime", datetime_api),
            patch.object(sender, "TIME_IN_MARKER_FILE", marker_path),
            patch.object(sender.logging, "info"),
            patch.object(sender.logging, "warning"),
            patch.object(sender.logging, "exception"),
            patch.object(sender, "philippine_holiday_rule_allows", holiday_gate),
            patch.object(sender, "capture_timeout_screenshot", capture),
            patch.object(sender, "deliver_screenshot", delivery),
        ):
            result = sender.main()

        return result, capture, delivery, holiday_gate

    def test_time_in_is_a_distinct_cli_mode(self):
        with patch.object(sys, "argv", ["send_wechat_time.py", "--time-in"]):
            arguments = sender.parse_args()

        self.assertTrue(arguments.time_in)
        self.assertFalse(arguments.scheduled)
        self.assertFalse(arguments.send_now)

    def test_successful_actual_send_records_local_date(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"
            result, capture, delivery, holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 6, 8, 15),
            )

            self.assertEqual(result, 0)
            self.assertEqual(marker_path.read_text(encoding="ascii"), "2026-08-06\n")
            capture.assert_called_once()
            delivery.assert_called_once()
            holiday_gate.assert_called_once_with(date(2026, 8, 6))

    def test_duplicate_actual_send_is_skipped(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"
            marker_path.write_text("2026-08-06\n", encoding="ascii")

            result, capture, delivery, _holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 6, 10, 0),
            )

            self.assertEqual(result, 0)
            capture.assert_not_called()
            delivery.assert_not_called()

    def test_draft_is_allowed_but_does_not_change_marker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"
            marker_path.write_text("2026-08-06\n", encoding="ascii")

            with (
                patch.object(sender, "time_in_was_sent_on") as marker_read,
                patch.object(sender, "record_time_in_sent") as marker_write,
            ):
                result, capture, delivery, _holiday_gate = self.run_time_in(
                    marker_path,
                    now=datetime(2026, 8, 6, 8, 15),
                    draft_only=True,
                )

            self.assertEqual(result, 0)
            delivery.assert_called_once_with(
                capture.return_value,
                "Attendance Recording",
                draft_only=True,
            )
            marker_read.assert_not_called()
            marker_write.assert_not_called()
            self.assertEqual(marker_path.read_text(encoding="ascii"), "2026-08-06\n")

    def test_failed_delivery_does_not_create_marker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"

            result, _capture, delivery, _holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 6, 8, 15),
                delivery_error=RuntimeError("simulated send failure"),
            )

            self.assertEqual(result, 1)
            delivery.assert_called_once()
            self.assertFalse(marker_path.exists())

    def test_time_in_always_skips_weekends(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"

            result, capture, delivery, holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 8, 8, 15),
            )

            self.assertEqual(result, 0)
            capture.assert_not_called()
            delivery.assert_not_called()
            holiday_gate.assert_not_called()
            self.assertFalse(marker_path.exists())

    def test_time_in_skips_when_holiday_rule_rejects_date(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"

            result, capture, delivery, holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 21, 8, 15),
                holiday_allowed=False,
            )

            self.assertEqual(result, 0)
            holiday_gate.assert_called_once_with(date(2026, 8, 21))
            capture.assert_not_called()
            delivery.assert_not_called()
            self.assertFalse(marker_path.exists())

    def test_time_in_draft_still_skips_weekends(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"

            result, capture, delivery, holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 8, 8, 15),
                draft_only=True,
            )

            self.assertEqual(result, 0)
            capture.assert_not_called()
            delivery.assert_not_called()
            holiday_gate.assert_not_called()

    def test_time_in_draft_still_skips_non_working_holidays(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"

            result, capture, delivery, holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 21, 8, 15),
                draft_only=True,
                holiday_allowed=False,
            )

            self.assertEqual(result, 0)
            holiday_gate.assert_called_once_with(date(2026, 8, 21))
            capture.assert_not_called()
            delivery.assert_not_called()

    def test_time_in_rechecks_workday_if_holiday_check_crosses_midnight(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / ".wechat_last_time_in"

            result, capture, delivery, holiday_gate = self.run_time_in(
                marker_path,
                now=datetime(2026, 8, 7, 23, 59, 59),
                refreshed_now=datetime(2026, 8, 8, 0, 0, 1),
            )

            self.assertEqual(result, 0)
            holiday_gate.assert_called_once_with(date(2026, 8, 7))
            capture.assert_not_called()
            delivery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
