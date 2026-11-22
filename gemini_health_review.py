"""Gemini-backed Telegram replies and weekly health-trend summaries.

Only call this module after an explicit user message or on the scheduled
weekly report run. The prompt limits the model to cautious, non-diagnostic
trend descriptions; the model is not a clinician.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import sqlite3
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from google import genai
from google.genai import types

from health_store import DB_PATH, PROFILE_PATH

LOGGER = logging.getLogger("garmin_gemini")
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_WEEKLY_SOURCE_CHARS = 32_000
MAX_CHAT_CONTEXT_CHARS = 16_000

SYSTEM_INSTRUCTION = """You are an informational health-support assistant, not a doctor.
Use only the supplied user-reported context and measurements. Do not diagnose
sleep apnea, hypopnea, heart disease, or any other condition; do not calculate
clinical risk scores; do not claim Garmin stages or signal matches prove a
medical event or causality. Distinguish observations, uncertainty, and missing
data. Never advise starting, stopping, or changing medication, and never clear
the user for exercise. Give practical, low-risk next steps and questions to
discuss with the user's clinician. If the user describes severe or rapidly
worsening symptoms, advise urgent local medical care. Reply in Russian, plainly
and concisely. Do not repeat identifying details or the API key."""


class GeminiReviewError(RuntimeError):
    """Safe-to-display error without request contents or credentials."""


def _client() -> genai.Client:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise GeminiReviewError("GEMINI_API_KEY is missing from the local .env file")
    return genai.Client(api_key=key)


def _model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_MODEL).strip()


def _generate(contents: list, *, max_output_tokens: int) -> str:
    client = _client()
    last_error = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=_model_name(),
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.25,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = (response.text or "").strip()
            if not text:
                raise GeminiReviewError("Gemini returned an empty response")
            return text
        except GeminiReviewError:
            raise
        except Exception as exc:  # SDK errors differ by version and status.
            last_error = exc
            if attempt == 0:
                time.sleep(2)
    LOGGER.warning("Gemini request failed (%s)", type(last_error).__name__)
    raise GeminiReviewError("Gemini API request failed; check the key, model, quota, and connection") from None


def _recent_context(timezone_name: str) -> str:
    """Build a small, de-identified context packet from local history."""
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    packet: dict = {"health_profile": {}, "nightly_summaries_last_14_days": [],
                    "journal_notes_last_14_days": [], "manual_measurements_last_14_days": []}
    if PROFILE_PATH.exists():
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            packet["health_profile"] = {
                "reported_history": profile.get("reported_history", []),
                "weekly_context": profile.get("weekly_context", []),
            }
        except (OSError, json.JSONDecodeError):
            packet["health_profile"] = {"status": "profile file unavailable or invalid"}

    if DB_PATH.exists():
        try:
            with closing(sqlite3.connect(DB_PATH, timeout=10)) as con:
                con.row_factory = sqlite3.Row
                packet["nightly_summaries_last_14_days"] = [dict(row) for row in con.execute(
                    """SELECT sleep_date, sleep_seconds, spo2_mean, spo2_min,
                              spo2_below_90, respiration_mean, respiration_min,
                              heart_rate_mean, awake_intervals, candidate_matches,
                              body_battery, readiness_score, readiness_level
                       FROM daily_snapshots WHERE sleep_date >= ? ORDER BY sleep_date""",
                    (cutoff,)).fetchall()]
                packet["journal_notes_last_14_days"] = [dict(row) for row in con.execute(
                    """SELECT created_at, entry_text FROM journal_entries
                       WHERE local_date >= ? ORDER BY created_at DESC LIMIT 8""",
                    (cutoff,)).fetchall()]
                packet["manual_measurements_last_14_days"] = [dict(row) for row in con.execute(
                    """SELECT created_at, kind, value_a, value_b, note FROM measurements
                       WHERE local_date >= ? ORDER BY created_at DESC LIMIT 12""",
                    (cutoff,)).fetchall()]
        except sqlite3.Error as exc:
            LOGGER.warning("Could not read local Gemini context (%s)", type(exc).__name__)
    packet["timezone"] = timezone_name
    return json.dumps(packet, ensure_ascii=False, default=str)[:MAX_CHAT_CONTEXT_CHARS]


def generate_chat_reply(message: str, timezone_name: str,
                        photo_path: str | None = None) -> str:
    """Reply to a user's Telegram journal/chat message using recent context."""
    prompt = (
        "The user sent this message to their private health journal bot. "
        "A photo may also be attached. First answer the specific question or "
        "acknowledge the observation. Use recent context only if relevant. "
        "Do not infer a diagnosis from wearable data or a photo. If the message "
        "is only a log entry, give a brief useful response and say it was saved. "
        "Keep the reply under 180 words.\n\n"
        f"USER MESSAGE:\n{message or '(photo without caption)'}\n\n"
        f"LOCAL HEALTH CONTEXT (user-reported; not independently verified):\n{_recent_context(timezone_name)}"
    )
    contents: list = [prompt]
    if photo_path:
        path = Path(photo_path)
        if not path.is_file():
            raise GeminiReviewError("The locally saved photo could not be found")
        mime_type = mimetypes.guess_type(path.name)[0]
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise GeminiReviewError("This photo format is not supported for Gemini review")
        contents.append(types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type))
    return _generate(contents, max_output_tokens=700)


def generate_weekly_ai_review(report_path: Path) -> str:
    """Generate a cautious Russian weekly interpretation from the local report."""
    try:
        source = report_path.read_text(encoding="utf-8")[:MAX_WEEKLY_SOURCE_CHARS]
    except OSError:
        raise GeminiReviewError("The local weekly report could not be read") from None
    prompt = (
        "Составь короткий недельный разбор на русском, максимум 100 слов. "
        "Не пересказывай средние, минимумы, счетчики и весь отчет. Нужны только "
        "изменения, практический вывод и следующие шаги. Выведи ровно 4 короткие "
        "строки с такими метками:\n"
        "Изменения: 1–2 наблюдения по сравнению с предыдущей неделей или по "
        "дневнику. Указывай тренд только если данных достаточно; иначе прямо "
        "напиши, что данных мало.\n"
        "Врач: что конкретно обсудить, если есть устойчивое ухудшение, симптомы "
        "или важный незакрытый вопрос профиля. Если новых срочных сигналов в "
        "этой неделе не видно, так и скажи, но не утверждай, что обращение к "
        "врачу вообще не нужно. Не ставь диагноз и не называй сигналы Garmin апноэ.\n"
        "Вело: явно выбери снизить, сохранить или осторожно наращивать нагрузку; "
        "если нет данных о вело или фактическом объеме, так и укажи и не выдумывай.\n"
        "Силовые: явно выбери снизить, сохранить или осторожно наращивать нагрузку; "
        "если нет данных о силовых или фактическом объеме, так и укажи и не выдумывай.\n"
        "Используй только имеющиеся сведения о восстановлении, симптомах и "
        "ограничениях врача. При активной боли или врачебном ограничении не "
        "предлагай наращивать нагрузку. Не меняй лекарства и не давай медицинский "
        "допуск к спорту. Пиши прямо, без вступления, повторения цифр и воды. "
        "Это наблюдательная поддержка, не диагноз и не доказательство причинности.\n\n"
        f"НЕДЕЛЬНЫЙ ОТЧЕТ И ДНЕВНИК:\n{source}"
    )
    return _generate([prompt], max_output_tokens=450)[:1000]


def append_ai_review(report_path: Path, review: str) -> None:
    """Append the generated narrative to the local Markdown report."""
    with report_path.open("a", encoding="utf-8") as report:
        report.write("\n\n## Gemini-generated exploratory review\n\n")
        report.write(review.strip() + "\n")
        report.write("\nThis AI-generated text is informational, may be inaccurate, and is not a diagnosis or treatment plan.\n")
