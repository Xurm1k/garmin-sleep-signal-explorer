from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemini_health_review import generate_weekly_ai_review


class WeeklyReviewPromptTests(unittest.TestCase):
    def test_weekly_reply_is_compact_and_covers_requested_decisions(self) -> None:
        expected = (
            "Изменения: данных мало.\n"
            "Врач: обсудить устойчивые симптомы.\n"
            "Вело: сохранить текущий разрешенный объем.\n"
            "Силовые: данных о занятиях нет."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "weekly.md"
            report.write_text("Sample local weekly report", encoding="utf-8")
            with patch("gemini_health_review._generate", return_value=expected) as generate:
                result = generate_weekly_ai_review(report)

        self.assertEqual(result, expected)
        prompt = generate.call_args.args[0][0]
        self.assertIn("максимум 100 слов", prompt)
        self.assertIn("Вело:", prompt)
        self.assertIn("Силовые:", prompt)
        self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 450)


if __name__ == "__main__":
    unittest.main()
