"""Local-only storage and descriptive weekly review for Garmin health data.

All profile facts are user-reported and unverified. The weekly report uses
descriptive summaries and conservative prompts; it does not diagnose or
prescribe treatment.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "health_history.sqlite3"
PROFILE_PATH = DATA_DIR / "health_profile.json"
REPORTS_DIR = PROJECT_DIR / "reports"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            sleep_date TEXT PRIMARY KEY,
            recovery_date TEXT,
            sleep_seconds INTEGER,
            spo2_mean REAL,
            spo2_min REAL,
            spo2_samples INTEGER NOT NULL DEFAULT 0,
            spo2_below_90 INTEGER NOT NULL DEFAULT 0,
            respiration_mean REAL,
            respiration_min REAL,
            respiration_samples INTEGER NOT NULL DEFAULT 0,
            heart_rate_mean REAL,
            heart_rate_min REAL,
            heart_rate_samples INTEGER NOT NULL DEFAULT 0,
            awake_intervals INTEGER NOT NULL DEFAULT 0,
            candidate_matches INTEGER NOT NULL DEFAULT 0,
            body_battery INTEGER,
            readiness_score INTEGER,
            readiness_level TEXT,
            collected_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journal_entries (
            telegram_update_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            local_date TEXT NOT NULL,
            entry_text TEXT NOT NULL,
            media_path TEXT
        );
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_update_id INTEGER UNIQUE,
            created_at TEXT NOT NULL,
            local_date TEXT NOT NULL,
            kind TEXT NOT NULL,
            value_a REAL NOT NULL,
            value_b REAL,
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS bot_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS topic_status (
            topic_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT ''
        );
    """)
    return con


@contextmanager
def _db():
    con = _connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _values(frame: Any, column: str) -> list[float]:
    if frame is None or getattr(frame, "empty", True) or column not in frame.columns:
        return []
    out = []
    for item in frame[column].dropna().tolist():
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _minimum(values: list[float]) -> float | None:
    return round(min(values), 2) if values else None


def save_daily_snapshot(sleep_date: str, recovery_date: str, sleep: dict,
                        spo2: Any, respiration: Any, heart_rate: Any,
                        events: list[dict], daily_status: dict) -> None:
    """Persist one nightly summary; reruns update that date idempotently."""
    o2 = _values(spo2, "spo2")
    resp = _values(respiration, "respiration")
    hr = _values(heart_rate, "heart_rate")
    awake_count = sum(1 for item in sleep.get("sleep_levels", [])
                      if item.get("type") == "awake")
    readiness = daily_status.get("training_readiness") or {}
    score = readiness.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        score = None
    battery = daily_status.get("body_battery")
    if isinstance(battery, bool) or not isinstance(battery, int) or not 0 <= battery <= 100:
        battery = None

    record = (
        sleep_date, recovery_date, int(sleep.get("sleep_time_seconds", 0)),
        _mean(o2), _minimum(o2), len(o2), sum(1 for value in o2 if value < 90),
        _mean(resp), _minimum(resp), len(resp), _mean(hr), _minimum(hr), len(hr),
        awake_count, len(events), battery, int(score) if score is not None else None,
        readiness.get("level"), datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    with _db() as con:
        con.execute("""
            INSERT INTO daily_snapshots VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sleep_date) DO UPDATE SET
              recovery_date=excluded.recovery_date,
              sleep_seconds=excluded.sleep_seconds,
              spo2_mean=excluded.spo2_mean, spo2_min=excluded.spo2_min,
              spo2_samples=excluded.spo2_samples, spo2_below_90=excluded.spo2_below_90,
              respiration_mean=excluded.respiration_mean,
              respiration_min=excluded.respiration_min,
              respiration_samples=excluded.respiration_samples,
              heart_rate_mean=excluded.heart_rate_mean, heart_rate_min=excluded.heart_rate_min,
              heart_rate_samples=excluded.heart_rate_samples,
              awake_intervals=excluded.awake_intervals,
              candidate_matches=excluded.candidate_matches,
              body_battery=excluded.body_battery,
              readiness_score=excluded.readiness_score,
              readiness_level=excluded.readiness_level,
              collected_at=excluded.collected_at
        """, record)


def get_bot_offset() -> int | None:
    with _db() as con:
        row = con.execute("SELECT state_value FROM bot_state WHERE state_key='telegram_offset'").fetchone()
    return int(row[0]) if row else None


def set_bot_offset(offset: int) -> None:
    with _db() as con:
        con.execute("INSERT INTO bot_state VALUES ('telegram_offset', ?) "
                    "ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value",
                    (str(offset),))


def set_topic_status(topic_key: str, status: str, note: str = "") -> None:
    if status not in {"active", "resolved"}:
        raise ValueError("Topic status must be active or resolved")
    with _db() as con:
        con.execute("""
            INSERT INTO topic_status (topic_key, status, updated_at, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(topic_key) DO UPDATE SET
              status=excluded.status, updated_at=excluded.updated_at, note=excluded.note
        """, (topic_key, status, datetime.now(timezone.utc).isoformat(timespec="seconds"), note[:500]))


def get_topic_status(topic_key: str) -> str:
    with _db() as con:
        row = con.execute("SELECT status FROM topic_status WHERE topic_key=?", (topic_key,)).fetchone()
    return str(row[0]) if row else "active"


def save_journal_entry(update_id: int, created_at: datetime, local_date: date,
                       entry_text: str, media_path: str | None) -> bool:
    with _db() as con:
        cur = con.execute("""
            INSERT OR IGNORE INTO journal_entries
            (telegram_update_id, created_at, local_date, entry_text, media_path)
            VALUES (?, ?, ?, ?, ?)
        """, (update_id, created_at.isoformat(timespec="seconds"),
              local_date.isoformat(), entry_text, media_path))
    return cur.rowcount > 0


def save_measurement(update_id: int, created_at: datetime, local_date: date,
                     kind: str, value_a: float, value_b: float | None,
                     note: str = "") -> None:
    with _db() as con:
        con.execute("""
            INSERT OR IGNORE INTO measurements
            (telegram_update_id, created_at, local_date, kind, value_a, value_b, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (update_id, created_at.isoformat(timespec="seconds"),
              local_date.isoformat(), kind, value_a, value_b, note[:500]))


def _avg(rows: list[sqlite3.Row], key: str) -> float | None:
    vals = [float(row[key]) for row in rows if row[key] is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _fmt_hours(seconds: float | None) -> str:
    if seconds is None:
        return "no data"
    mins = round(seconds / 60)
    return f"{mins // 60}h {mins % 60:02d}m"


def _metric_line(rows: list[sqlite3.Row], key: str, label: str, unit: str) -> str:
    value = _avg(rows, key)
    return f"{label}: no data" if value is None else f"{label}: {value:.1f} {unit} average of nightly averages"


def _profile_context() -> list[str]:
    if not PROFILE_PATH.exists():
        return []
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    # Include the persistent historical profile in every local weekly report.
    # Weekly context adds practical reminders; neither section is used to make
    # a diagnosis or to alter Garmin measurements.
    values = profile.get("reported_history", []) + profile.get("weekly_context", [])
    return [str(item) for item in values if isinstance(item, str)]


def generate_weekly_report(week_end: date, timezone_name: str) -> tuple[str, Path]:
    """Create Sunday summary from Monday–Sunday records and journal entries.

    The Telegram message is compact. The local Markdown report keeps all
    user-submitted journal text and relative photo paths for review.
    """
    week_start = week_end - timedelta(days=6)
    previous_start = week_start - timedelta(days=7)
    previous_end = week_start - timedelta(days=1)
    with _db() as con:
        rows = con.execute("SELECT * FROM daily_snapshots WHERE sleep_date BETWEEN ? AND ? ORDER BY sleep_date",
                           (week_start.isoformat(), week_end.isoformat())).fetchall()
        previous = con.execute("SELECT * FROM daily_snapshots WHERE sleep_date BETWEEN ? AND ? ORDER BY sleep_date",
                               (previous_start.isoformat(), previous_end.isoformat())).fetchall()
        journal = con.execute("SELECT * FROM journal_entries WHERE local_date BETWEEN ? AND ? ORDER BY created_at",
                              (week_start.isoformat(), week_end.isoformat())).fetchall()
        measurements = con.execute("SELECT * FROM measurements WHERE local_date BETWEEN ? AND ? ORDER BY created_at",
                                   (week_start.isoformat(), week_end.isoformat())).fetchall()

    nightly = len(rows)
    lines = [
        f"WEEKLY HEALTH REVIEW | {week_start.isoformat()} to {week_end.isoformat()}",
        f"Garmin nights recorded: {nightly}/7",
        f"Sleep duration: {_fmt_hours(_avg(rows, 'sleep_seconds'))} per recorded night",
        _metric_line(rows, "spo2_mean", "SpO2", "%"),
        f"Lowest nightly SpO2 sample: {min((r['spo2_min'] for r in rows if r['spo2_min'] is not None), default='no data')}%",
        f"SpO2 samples below 90%: {sum(int(r['spo2_below_90']) for r in rows)} across recorded nights (device samples, not a diagnosis)",
        _metric_line(rows, "respiration_mean", "Respiration", "breaths/min"),
        _metric_line(rows, "heart_rate_mean", "Sleeping heart rate", "bpm"),
        f"Garmin-rule candidate matches near awake labels: {sum(int(r['candidate_matches']) for r in rows)} (exploratory; not apnea events)",
    ]

    latest_battery = next((r["body_battery"] for r in reversed(rows) if r["body_battery"] is not None), None)
    latest_readiness = next((r for r in reversed(rows) if r["readiness_score"] is not None or r["readiness_level"]), None)
    recovery_parts = []
    if latest_battery is not None:
        recovery_parts.append(f"Body Battery {latest_battery}/100")
    if latest_readiness:
        readiness = latest_readiness["readiness_score"]
        level = latest_readiness["readiness_level"]
        recovery_parts.append("Training Readiness " + (f"{readiness}/100" if readiness is not None else "") + (f" {level}" if level else ""))
    lines.append("Latest recorded recovery: " + ("; ".join(recovery_parts) if recovery_parts else "no data"))

    if nightly >= 3 and len(previous) >= 3:
        current_sleep = _avg(rows, "sleep_seconds")
        previous_sleep = _avg(previous, "sleep_seconds")
        if current_sleep is not None and previous_sleep is not None:
            delta = (current_sleep - previous_sleep) / 3600
            lines.append(f"Sleep-duration change vs previous week: {delta:+.1f} h/night (descriptive comparison only)")
        current_o2 = _avg(rows, "spo2_mean")
        previous_o2 = _avg(previous, "spo2_mean")
        if current_o2 is not None and previous_o2 is not None:
            lines.append(f"SpO2 mean change vs previous week: {current_o2 - previous_o2:+.1f} percentage points (descriptive comparison only)")
    else:
        lines.append("Week-to-week comparison: not enough recorded nights in both weeks (minimum 3 each).")

    bp = [m for m in measurements if m["kind"] == "bp"]
    weight = [m for m in measurements if m["kind"] == "weight"]
    pain = [m for m in measurements if m["kind"] == "pain"]
    lines.append(f"Personal journal: {len(journal)} note(s), {sum(1 for j in journal if j['media_path'])} photo(s). Full entries are in the local report.")
    if bp:
        systolic = [float(m["value_a"]) for m in bp]
        diastolic = [float(m["value_b"]) for m in bp if m["value_b"] is not None]
        lines.append(f"Home BP entries: {len(bp)}; systolic {min(systolic):.0f}–{max(systolic):.0f} mmHg" +
                     (f", diastolic {min(diastolic):.0f}–{max(diastolic):.0f} mmHg" if diastolic else "") +
                     " (manually entered; follow your clinician's measurement instructions).")
    if weight:
        latest = weight[-1]["value_a"]
        lines.append(f"Latest manually entered weight: {latest:.1f} kg" +
                     (f"; change from first entry this week: {latest - weight[0]['value_a']:+.1f} kg" if len(weight) > 1 else ""))
    if pain:
        lines.append(f"Pain diary: {len(pain)} score(s); latest {pain[-1]['value_a']:.0f}/10" +
                     (f" ({pain[-1]['note']})" if pain[-1]["note"] else ""))

    prompts = [
        "Wearable SpO2 and sleep-stage readings are estimates; Garmin says unusual sleep positions can cause abnormally low sleep SpO2 values.",
        "If sleep symptoms persist or concern you, discuss appropriate evaluation with a qualified clinician; a watch cannot diagnose a sleep disorder.",
        "Use the treating clinician's exercise and blood-pressure guidance. This report cannot clear training intensity or change medication advice.",
    ]
    lines.extend(["", "CLINICIAN DISCUSSION POINTS (not a diagnosis or treatment plan)", *[f"- {p}" for p in prompts]])
    lines.append("Generated from user-reported history and Garmin estimates. Not reviewed by a clinician.")
    telegram_text = "\n".join(lines)

    context = _profile_context()
    md = [f"# Weekly health review: {week_start.isoformat()} to {week_end.isoformat()}", "",
          "This is a local, descriptive report from Garmin estimates and user-entered notes. It is not a diagnosis or a treatment plan.", "",
          "## Summary", *[f"- {line}" for line in lines if line and not line.startswith("-")], "",
          "## Context supplied by the user (not independently verified)"]
    md.extend([f"- {item}" for item in context] if context else ["- No profile context file found."])
    md.extend(["", "## Journal entries"])
    if not journal:
        md.append("No journal entries were received this week.")
    for entry in journal:
        md.extend([f"### {entry['created_at']}", "", entry["entry_text"] or "(photo received without a caption)"])
        if entry["media_path"]:
            rel = str(entry["media_path"]).replace("\\", "/")
            md.append(f"\n[Open attached photo](../{rel})")
        md.append("")
    if measurements:
        md.extend(["## Structured entries", ""])
        for item in measurements:
            if item["kind"] == "bp":
                value = f"{item['value_a']:.0f}/{item['value_b']:.0f} mmHg" if item["value_b"] is not None else f"{item['value_a']:.0f} mmHg systolic"
            elif item["kind"] == "weight":
                value = f"{item['value_a']:.1f} kg"
            else:
                value = f"{item['value_a']:.0f}/10"
            md.append(f"- {item['created_at']}: {item['kind']} {value}" + (f" — {item['note']}" if item['note'] else ""))
    md.extend(["", "## Data notes", "", f"Timezone: {timezone_name}.",
               "Garmin values are estimates. The Instinct 2 manual notes unusual sleep positions may cause low sleep-time SpO2 readings.",
               "The American Academy of Sleep Medicine recommends diagnostic testing, such as polysomnography or an appropriate home sleep apnea test, rather than wearable patterns for diagnosis.",
               "", "References:",
               "- https://aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf",
               "- https://support.garmin.com/en-US/?faq=qvzNMwxuTb9NxZ6Ce2a9z9"])
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"weekly_health_{week_end.isocalendar().year}-W{week_end.isocalendar().week:02d}.md"
    report_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    # Leave room for the daily summary in the same Telegram message. The full
    # weekly detail remains available in the local Markdown report.
    if len(telegram_text) > 1700:
        telegram_text = telegram_text[:1690].rsplit("\n", 1)[0]
        telegram_text += "\nFull weekly details are in the local Markdown report."
    return telegram_text, report_path
