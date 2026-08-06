import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class TimeInLauncherTests(unittest.TestCase):
    def test_batch_file_routes_to_time_in_test_action(self):
        launcher = (PROJECT_DIR / "TEST_TIME_IN.bat").read_text(encoding="ascii")

        self.assertIn('easy_setup.ps1" -Action TimeInTest', launcher)

    def test_time_in_test_action_uses_draft_only_mode(self):
        helper = (PROJECT_DIR / "easy_setup.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('"TimeInTest" { Test-TimeIn }', helper)
        self.assertIn(
            "& $pythonPath $senderPath --time-in --draft-only --contact $contact",
            helper,
        )


if __name__ == "__main__":
    unittest.main()
