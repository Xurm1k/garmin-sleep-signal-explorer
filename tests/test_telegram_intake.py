import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import telegram_intake as intake
from gemini_health_review import GeminiReviewError


def sample_update(update_id: int = 42, text: str = "A sample journal note after a workout") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "date": 1795320000,
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 12345, "is_bot": False},
            "text": text,
        },
    }


class TelegramIntakeTests(unittest.TestCase):
    def test_receipt_is_sent_before_optional_gemini_reply(self) -> None:
        events: list[tuple[str, str]] = []

        def acknowledge(_token: str, _chat_id: str, text: str) -> None:
            events.append(("ack", text))

        def gemini_reply(*_args) -> str:
            events.append(("gemini", "called"))
            return "Короткий комментарий"

        with patch.object(intake, "save_measurement"), \
                patch.object(intake, "save_journal_entry", return_value=True), \
                patch.object(intake, "_ack", side_effect=acknowledge), \
                patch.object(intake, "generate_chat_reply", side_effect=gemini_reply):
            intake._process_update(sample_update(), "token", "12345", "12345",
                                   ZoneInfo("Europe/Berlin"))

        self.assertEqual([item[0] for item in events], ["ack", "gemini", "ack"])
        self.assertIn("записано", events[0][1].lower())
        self.assertEqual(events[2][1], "Короткий комментарий")

    def test_duplicate_update_is_acknowledged_without_second_ai_call(self) -> None:
        acknowledgements: list[str] = []
        with patch.object(intake, "save_measurement"), \
                patch.object(intake, "save_journal_entry", return_value=False), \
                patch.object(intake, "_ack", side_effect=lambda _t, _c, text: acknowledgements.append(text)), \
                patch.object(intake, "generate_chat_reply") as gemini:
            intake._process_update(sample_update(), "token", "12345", "12345",
                                   ZoneInfo("Europe/Berlin"))

        self.assertEqual(len(acknowledgements), 1)
        self.assertIn("уже записано", acknowledgements[0].lower())
        gemini.assert_not_called()

    def test_gemini_failure_does_not_remove_receipt(self) -> None:
        acknowledgements: list[str] = []
        with patch.object(intake, "save_measurement"), \
                patch.object(intake, "save_journal_entry", return_value=True), \
                patch.object(intake, "_ack", side_effect=lambda _t, _c, text: acknowledgements.append(text)), \
                patch.object(intake, "generate_chat_reply", side_effect=GeminiReviewError("offline")):
            intake._process_update(sample_update(), "token", "12345", "12345",
                                   ZoneInfo("Europe/Berlin"))

        self.assertEqual(len(acknowledgements), 1)
        self.assertIn("записано", acknowledgements[0].lower())


if __name__ == "__main__":
    unittest.main()
