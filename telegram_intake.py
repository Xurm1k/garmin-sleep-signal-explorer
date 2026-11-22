#!/usr/bin/env python3
"""Save private-chat health notes/photos to the local journal.

This listener stores material locally and acknowledges receipt. It does not
send health content to an AI model or generate diagnoses.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from dotenv import load_dotenv

from health_store import (get_bot_offset, save_journal_entry,
                          save_measurement, set_bot_offset, set_topic_status)
from gemini_health_review import GeminiReviewError, generate_chat_reply

PROJECT_DIR = Path(__file__).resolve().parent
MEDIA_DIR = PROJECT_DIR / "data" / "intake_media"
LOGGER = logging.getLogger("garmin_telegram_intake")
MAX_MEDIA_BYTES = 12 * 1024 * 1024
MAX_NOTE_CHARS = 4000


class IntakeError(RuntimeError):
    pass


def _api(token: str, method: str, data: dict | None = None) -> dict:
    """Call Telegram without logging token-bearing URLs or user content."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        response = requests.post(url, data=data or {}, timeout=(10, 45))
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IntakeError(f"Telegram {method} request failed") from None
    if not body.get("ok"):
        raise IntakeError(f"Telegram {method} request was rejected")
    return body.get("result") or {}


def _download_photo(token: str, photo: dict, local_date: date, update_id: int) -> str:
    file_id = photo.get("file_id")
    if not isinstance(file_id, str) or not file_id:
        raise IntakeError("Telegram photo did not include a file id")
    details = _api(token, "getFile", {"file_id": file_id})
    remote = details.get("file_path")
    size = details.get("file_size")
    if not isinstance(remote, str) or not remote or Path(remote).name != remote.split("/")[-1]:
        raise IntakeError("Telegram returned an invalid file path")
    if isinstance(size, int) and size > MAX_MEDIA_BYTES:
        raise IntakeError("Photo is larger than the local intake limit")
    suffix = Path(remote).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    folder = MEDIA_DIR / local_date.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"telegram_{update_id}{suffix}"
    url = f"https://api.telegram.org/file/bot{token}/{remote}"
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            written = 0
            with destination.open("wb") as target:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_MEDIA_BYTES:
                        target.close()
                        destination.unlink(missing_ok=True)
                        raise IntakeError("Photo is larger than the local intake limit")
                    target.write(chunk)
    except requests.RequestException:
        destination.unlink(missing_ok=True)
        raise IntakeError("Could not download Telegram photo") from None
    return destination.relative_to(PROJECT_DIR).as_posix()


def _measurement_command(text: str) -> tuple[str, float, float | None, str] | None:
    match = re.fullmatch(r"\s*/bp\s+(\d{2,3})\s*/\s*(\d{2,3})(?:\s+(.+))?\s*", text, re.I)
    if match:
        systolic, diastolic = int(match.group(1)), int(match.group(2))
        if 50 <= systolic <= 300 and 30 <= diastolic <= 200:
            return "bp", float(systolic), float(diastolic), (match.group(3) or "")
        return None
    match = re.fullmatch(r"\s*/weight\s+(\d{2,3}(?:[.,]\d)?)(?:\s+(.+))?\s*", text, re.I)
    if match:
        value = float(match.group(1).replace(",", "."))
        if 30 <= value <= 350:
            return "weight", value, None, (match.group(2) or "")
        return None
    match = re.fullmatch(r"\s*/pain\s+(\d{1,2})(?:\s+(.+))?\s*", text, re.I)
    if match:
        value = int(match.group(1))
        if 0 <= value <= 10:
            return "pain", float(value), None, (match.group(2) or "")
        return None
    return None


def _ack(token: str, chat_id: str, message: str) -> None:
    _api(token, "sendMessage", {"chat_id": chat_id, "text": message})


def _process_update(update: dict, token: str, expected_chat: str,
                    expected_sender: str, tz: ZoneInfo) -> None:
    update_id = update.get("update_id")
    message = update.get("message") or update.get("edited_message")
    if not isinstance(update_id, int) or not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = str(chat.get("id", ""))
    sender_id = str(sender.get("id", ""))
    if chat_id != expected_chat or sender_id != expected_sender:
        LOGGER.info("Skipped update from a non-authorized Telegram chat/user")
        return
    if sender.get("is_bot"):
        return

    text = message.get("text") or message.get("caption") or ""
    text = str(text).strip()[:MAX_NOTE_CHARS]
    if text.lower() in {"/start", "/help"}:
        _ack(token, chat_id,
             "Private health journal is ready. Notes and photos are stored locally. "
             "Commands: /bp 120/80, /weight 75, /pain 3 add a short note. "
             "Use /resolve topic-name or /reopen topic-name to update a local topic status. "
             "No AI analysis or diagnosis is sent by this listener.")
        return
    topic_command = re.fullmatch(r"/(resolve|reopen)\s+([a-z][a-z0-9_-]{1,39})(?:\s+(.+))?", text, re.I)
    if topic_command:
        topic = topic_command.group(2).lower()
        status = "resolved" if topic_command.group(1).lower() == "resolve" else "active"
        set_topic_status(topic, status, topic_command.group(3) or "")
        _ack(token, chat_id,
             f"Topic '{topic}' marked {status} in the local tracker. This is a journal status, not a medical assessment.")
        return

    stamp = message.get("date")
    try:
        created = datetime.fromtimestamp(int(stamp), tz=timezone.utc).astimezone(tz)
    except (TypeError, ValueError, OSError):
        created = datetime.now(tz)
    local_date = created.date()
    media_path = None
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        photo = max((item for item in photos if isinstance(item, dict)),
                    key=lambda item: item.get("file_size", 0), default=None)
        if photo:
            media_path = _download_photo(token, photo, local_date, update_id)

    if not text and not media_path:
        _ack(token, chat_id,
             "Пока я могу сохранить текстовые сообщения и фотографии. "
             "Отправь текст или фото ещё раз.")
        return
    if not text:
        text = "Photo received without a caption."
    command = _measurement_command(text)
    if command:
        kind, value_a, value_b, note = command
        save_measurement(update_id, created, local_date, kind, value_a, value_b, note)
        # Keep the original command and optional photo together in the diary.
        entry_text = text
    else:
        entry_text = text
    saved = save_journal_entry(update_id, created, local_date, entry_text, media_path)
    if saved:
        LOGGER.info("Saved one local health journal entry (photo=%s)", bool(media_path))
        _ack(token, chat_id, "✅ Получено и записано в дневник здоровья.")
    else:
        # Telegram may redeliver an update if acknowledgement or offset
        # persistence failed. Confirm the existing record instead of silently
        # consuming the update.
        _ack(token, chat_id, "✅ Это сообщение уже записано в дневник здоровья.")
        return

    # Receipt is sent before the optional AI response, so a slow or unavailable
    # Gemini API cannot leave a successfully stored message unacknowledged.
    try:
        local_photo = str(PROJECT_DIR / media_path) if media_path else None
        reply = generate_chat_reply(text, tz.key, local_photo)
    except GeminiReviewError as exc:
        LOGGER.warning("Gemini reply unavailable: %s", exc)
        return
    except Exception as exc:
        LOGGER.warning("Gemini reply failed (%s)", type(exc).__name__)
        return
    try:
        _ack(token, chat_id, reply[:3500])
    except IntakeError:
        # The saved entry and receipt are already durable; don't make Telegram
        # redeliver the update just because the optional AI reply failed.
        LOGGER.warning("Saved journal entry; optional Gemini reply could not be delivered")


def main() -> int:
    load_dotenv(PROJECT_DIR / ".env", override=False)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(PROJECT_DIR / "telegram_intake.log", encoding="utf-8")])
    token = (os.getenv("TG_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TG_CHAT_ID") or "").strip()
    sender = (os.getenv("TG_OWNER_USER_ID") or chat).strip()
    if not token or not chat:
        raise IntakeError("Set TG_BOT_TOKEN and TG_CHAT_ID in the local .env file")
    try:
        tz = ZoneInfo(os.getenv("GARMIN_TIMEZONE", "Europe/Berlin"))
    except ZoneInfoNotFoundError as exc:
        raise IntakeError("GARMIN_TIMEZONE is not a valid IANA timezone") from exc
    webhook = _api(token, "getWebhookInfo")
    if webhook.get("url"):
        raise IntakeError("A Telegram webhook is active. Disable it before starting this polling listener.")

    offset = get_bot_offset()
    LOGGER.info("Telegram local journal listener started; no message content is written to logs")
    while True:
        try:
            args = {"timeout": 30, "allowed_updates": '["message","edited_message"]'}
            if offset is not None:
                args["offset"] = offset
            result = _api(token, "getUpdates", args)
            for update in result:
                if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                    continue
                update_id = update["update_id"]
                processed = True
                try:
                    _process_update(update, token, chat, sender, tz)
                except IntakeError as exc:
                    LOGGER.warning("Could not save one Telegram intake item: %s", exc)
                    processed = False
                except Exception:
                    LOGGER.exception("Unexpected failure while saving a Telegram intake item")
                    processed = False
                if not processed:
                    break
                offset = update_id + 1
                set_bot_offset(offset)
        except KeyboardInterrupt:
            LOGGER.info("Telegram local journal listener stopped")
            return 0
        except IntakeError as exc:
            LOGGER.warning("Telegram listener request failed: %s", exc)
            time.sleep(15)
        except Exception:
            LOGGER.exception("Telegram listener loop failed")
            time.sleep(15)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except IntakeError as exc:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.error("Telegram intake stopped: %s", exc)
        sys.exit(1)
