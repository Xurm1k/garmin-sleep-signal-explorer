from pathlib import Path
import unittest


PROJECT_DIR = Path(__file__).resolve().parents[1]


class CloudScheduleConfigTests(unittest.TestCase):
    def test_daily_timer_is_persistent_and_local_time_based(self) -> None:
        timer = (PROJECT_DIR / "cloud" / "garmin-pipeline.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 08:30:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("RandomizedDelaySec=5m", timer)

    def test_telegram_listener_restarts_and_long_polls(self) -> None:
        service = (PROJECT_DIR / "cloud" / "garmin-intake.service").read_text(encoding="utf-8")
        intake = (PROJECT_DIR / "telegram_intake.py").read_text(encoding="utf-8")
        self.assertIn("Restart=on-failure", service)
        self.assertIn("RestartSec=15", service)
        self.assertIn('"timeout": 30', intake)
        self.assertIn("time.sleep(15)", intake)
        self.assertIn("get_bot_offset()", intake)
        self.assertIn("set_bot_offset(offset)", intake)


if __name__ == "__main__":
    unittest.main()
