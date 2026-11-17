#!/usr/bin/env python3
"""Garmin overnight sleep report. Secrets are loaded only from project .env."""
from __future__ import annotations

import logging
import html
import math
import os
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import plotly.graph_objects as go
import requests
from dotenv import load_dotenv
from garminconnect import Garmin
from plotly.subplots import make_subplots
import pdf_report

PROJECT_DIR = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_DIR / "reports"
LOGGER = logging.getLogger("garmin_pipeline")
STAGE_COLORS = {
    "awake": "rgba(255, 140, 0, 0.48)",
    "deep": "rgba(10, 25, 80, 0.58)",
    "light": "rgba(70, 160, 220, 0.42)",
    "rem": "rgba(150, 70, 190, 0.48)",
}
SPO2_COLUMNS = ["timestamp", "spo2"]
RESP_COLUMNS = ["timestamp", "respiration"]


class PipelineError(RuntimeError):
    """A user-actionable pipeline error."""


def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise PipelineError(f"Missing {name} in {PROJECT_DIR / '.env'}")
    return value.strip()


def setup() -> ZoneInfo:
    load_dotenv(PROJECT_DIR / ".env", override=False)
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(PROJECT_DIR / "pipeline.log", encoding="utf-8")])
    try:
        tz = ZoneInfo(os.getenv("GARMIN_TIMEZONE", "Europe/Berlin"))
    except ZoneInfoNotFoundError as exc:
        raise PipelineError("GARMIN_TIMEZONE is not a valid IANA timezone") from exc
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return tz


def last_night(now: datetime, night_start_hour: int = 18) -> date:
    """Return Garmin's calendar date for the night that most recently began.

    Garmin sleep endpoints are keyed by the date on which the sleep session
    ends. Before the configured evening start, that date is today; afterwards
    it is tomorrow. This handles runs on either side of midnight consistently.
    """
    local = now
    if local.hour >= night_start_hour:
        return local.date() + timedelta(days=1)
    return local.date()


def call_retry(label: str, fn, attempts: int = 3, delay: float = 2.0):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # garminconnect raises varied request/auth errors
            last = exc
            LOGGER.warning("%s failed (%d/%d): %s", label, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(delay * attempt)
    raise PipelineError(f"{label} failed after {attempts} attempts: {last}") from last


def init_garmin() -> Garmin:
    email, password = env_required("GARMIN_EMAIL"), env_required("GARMIN_PASSWORD")
    client = Garmin(email, password)
    call_retry("Garmin login", client.login)
    return client


def fetch_data(garmin: Garmin, target_date: str) -> tuple[dict, dict, dict]:
    try:
        sleep = call_retry("get_daily_sleep", lambda: garmin.get_daily_sleep(target_date), attempts=1)
    except PipelineError as primary:
        LOGGER.info("Trying sleep fallback get_sleep_data")
        try:
            sleep = call_retry("get_sleep_data", lambda: garmin.get_sleep_data(target_date))
        except PipelineError as fallback:
            raise PipelineError(f"Both sleep endpoints failed: {primary}; {fallback}") from fallback

    def first_available(label, methods):
        errors = []
        for method in methods:
            fn = getattr(garmin, method, None)
            if not callable(fn):
                errors.append(f"{method} unavailable")
                continue
            try:
                return call_retry(method, lambda: fn(target_date))
            except PipelineError as exc:
                errors.append(str(exc))
        raise PipelineError(f"{label} unavailable: {'; '.join(errors)}")

    spo2 = first_available("SpO2", ["get_spo2_acclimation_data", "get_spo2_data"])
    respiration = first_available("respiration", ["get_respiration_data"])
    return sleep, spo2, respiration


def _dict(value: Any, context: str) -> dict:
    if not isinstance(value, dict):
        raise PipelineError(f"Unsupported {context} response: expected object, got {type(value).__name__}")
    return value


def sleep_data(raw: Any) -> dict:
    """Read sleepTimeSeconds and only documented stage list forms.

    Garmin places sleepLevels at the response root (with older variants under
    dailySleepDTO). activityLevel numeric codes are 0 deep, 1 light, 2 REM,
    and 3 awake. sleepTimeSeconds remains read strictly from dailySleepDTO.
    Unknown shapes are logged and ignored; numeric arrays are never searched.
    """
    root = _dict(raw, "sleep")
    dto = root.get("dailySleepDTO", root)
    dto = _dict(dto, "dailySleepDTO")
    seconds = dto.get("sleepTimeSeconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        raise PipelineError("Sleep response lacks a valid dailySleepDTO.sleepTimeSeconds")
    stages = []
    intervals = root.get("sleepLevels", dto.get("sleepLevels"))
    if isinstance(intervals, list):
        for item in intervals:
            if not isinstance(item, dict):
                LOGGER.warning("Ignoring unsupported sleepLevels item")
                continue
            start = item.get("startGMT") or item.get("startTimeGMT")
            end = item.get("endGMT") or item.get("endTimeGMT")
            label = item.get("activityLevel")
            if label is None:
                label = item.get("sleepLevel", item.get("level"))
            stage = normalize_stage(label)
            if start and end and stage:
                stages.append({"start": start, "end": end, "type": stage})
    elif intervals is not None:
        LOGGER.warning("Unsupported sleepLevels shape: %s", type(intervals).__name__)
    level_map = root.get("sleepLevelsMap", dto.get("sleepLevelsMap"))
    if not stages and isinstance(level_map, dict):
        for label, spans in level_map.items():
            stage = normalize_stage(label)
            if not stage or not isinstance(spans, list):
                continue
            for span in spans:
                if isinstance(span, dict):
                    start = span.get("startGMT") or span.get("startTimeGMT")
                    end = span.get("endGMT") or span.get("endTimeGMT")
                    if start and end:
                        stages.append({"start": start, "end": end, "type": stage})
    elif not stages and level_map is not None:
        LOGGER.warning("Unsupported sleepLevelsMap shape: %s", type(level_map).__name__)
    return {"sleep_time_seconds": int(seconds), "total_sleep_hours": seconds / 3600,
            "sleep_levels": stages}


def normalize_stage(label: Any) -> str | None:
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        return {0: "deep", 1: "light", 2: "rem", 3: "awake"}.get(int(label))
    if not isinstance(label, str):
        return None
    key = label.strip().lower().replace(" ", "_")
    aliases = {"awake": "awake", "wake": "awake", "deep": "deep", "light": "light",
               "rem": "rem", "asleep": "light", "sleep": "light",
               "0": "deep", "1": "light", "2": "rem", "3": "awake"}
    return aliases.get(key)


def _timestamp(value: Any, unit: str | None = None):
    if isinstance(value, bool) or value is None:
        return pd.NaT
    # Garmin value timestamps are generally epoch milliseconds; ISO strings
    # are accepted explicitly. Numeric seconds are not guessed.
    if isinstance(value, (int, float)):
        if unit != "ms":
            return pd.NaT
        return pd.to_datetime(value, unit="ms", utc=True, errors="coerce")
    return pd.to_datetime(value, utc=True, errors="coerce")


def _descriptor_columns(descriptors: Any, context: str,
                        index_names: tuple[str, ...] = ("index", "descriptorIndex"),
                        key_names: tuple[str, ...] = ("key", "descriptorKey")) -> dict[str, int]:
    """Decode Garmin's documented positional descriptor list (key + index)."""
    if not isinstance(descriptors, list):
        raise PipelineError(f"Unsupported {context} descriptors: expected a list")
    columns: dict[str, int] = {}
    used_indexes: set[int] = set()
    for item in descriptors:
        if not isinstance(item, dict):
            raise PipelineError(f"Unsupported {context} descriptor item")
        raw_index = next((item.get(name) for name in index_names if item.get(name) is not None), None)
        raw_key = next((item.get(name) for name in key_names if item.get(name) is not None), None)
        if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 0:
            raise PipelineError(f"Invalid index in {context} descriptor")
        if not isinstance(raw_key, str) or not raw_key:
            raise PipelineError(f"Invalid key in {context} descriptor")
        if raw_index in used_indexes or raw_key in columns:
            raise PipelineError(f"Duplicate {context} descriptor index/key")
        used_indexes.add(raw_index)
        columns[raw_key] = raw_index
    return columns


def _decoded_series(raw: dict, values_key: str, descriptors_key: str,
                    metric: str, value_keys: tuple[str, ...],
                    bounds: tuple[float, float], timestamp_keys: tuple[str, ...] = ("timestamp",),
                    descriptor_index_names: tuple[str, ...] = ("index", "descriptorIndex"),
                    descriptor_key_names: tuple[str, ...] = ("key", "descriptorKey")) -> list[tuple[Any, float]]:
    """Decode only named Garmin descriptor arrays; never scan arbitrary arrays."""
    rows = raw.get(values_key)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise PipelineError(f"Unsupported {values_key}: expected list or null")
    descriptors = _descriptor_columns(raw.get(descriptors_key), values_key,
                                       descriptor_index_names, descriptor_key_names)
    ts_key = next((k for k in timestamp_keys if k in descriptors), None)
    value_key = next((k for k in value_keys if k in descriptors), None)
    if ts_key is None or value_key is None:
        raise PipelineError(f"{values_key} descriptors lack timestamp or {metric}; got {sorted(descriptors)}")
    accepted: list[tuple[Any, float]] = []
    rejected = 0
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(descriptors[ts_key], descriptors[value_key]):
            rejected += 1
            continue
        ts = _timestamp(row[descriptors[ts_key]], "ms")
        try:
            value = float(row[descriptors[value_key]])
        except (TypeError, ValueError):
            rejected += 1
            continue
        if pd.isna(ts) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            rejected += 1
            continue
        accepted.append((ts, value))
    if rejected:
        LOGGER.info("Discarded %d malformed/out-of-range %s points from %s", rejected, metric, values_key)
    return accepted


def metric_frame(raw: Any, metric: str) -> pd.DataFrame:
    """Extract only known Garmin row keys, validate before DataFrame creation."""
    root = _dict(raw, metric)
    if metric == "spo2":
        # Garmin daily SpO2 response: descriptor-indexed single readings.
        # Hourly averages are an explicit fallback when single values are null.
        bounds, column = (70, 100), "spo2"
        try:
            accepted = _decoded_series(
                root, "spO2SingleValues", "spO2SingleValuesDescriptorList",
                "spo2", ("spo2Reading",), bounds,
                descriptor_index_names=("spo2ValueDescriptorIndex", "index", "descriptorIndex"),
                descriptor_key_names=("spo2ValueDescriptorKey", "key", "descriptorKey"))
        except PipelineError as exc:
            LOGGER.error("SpO2 single readings unavailable: %s", exc)
            accepted = []
        if not accepted:
            try:
                # Acclimation hourly descriptors use a distinct Garmin DTO:
                # spo2ValueDescIndex / spo2ValueDescKey (not index / key).
                accepted = _decoded_series(
                    root, "spO2HourlyAverages", "spO2HourlyAveragesDescriptorList",
                    "spo2", ("spo2Level",), bounds,
                    descriptor_index_names=("spo2ValueDescIndex", "index", "descriptorIndex"),
                    descriptor_key_names=("spo2ValueDescKey", "key", "descriptorKey"))
            except PipelineError as exc:
                LOGGER.error("SpO2 hourly fallback unavailable; continuing without SpO2: %s", exc)
                accepted = []
    elif metric == "respiration":
        # Garmin returns positional rows; descriptor keys prevent accidentally
        # selecting heart-rate or another adjacent numeric channel.
        bounds, column = (6, 30), "respiration"
        try:
            accepted = _decoded_series(root, "respirationValuesArray", "respirationValueDescriptorsDTOList",
                                       "respiration", ("respiration", "respirationValue"), bounds)
        except PipelineError as exc:
            LOGGER.error("Respiration series unavailable; continuing without respiration: %s", exc)
            accepted = []
    else:
        raise ValueError(f"Unknown metric: {metric}")
    # Validation is complete before the DataFrame is constructed.
    frame = pd.DataFrame(accepted, columns=["timestamp", column])
    if not frame.empty:
        frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return frame


def sleep_metric_frame(raw_sleep: Any, metric: str) -> pd.DataFrame:
    """Prefer the high-resolution series embedded in Garmin's sleep response.

    The daily SpO2 acclimation endpoint is mostly hourly averages. Garmin's
    sleep payload includes minute-level SpO2 epochs, sleep respiration epochs,
    and sleep heart-rate samples; these are the sources used by Connect's
    overnight charts and by the awakening correlation below.
    """
    root = _dict(raw_sleep, "sleep metrics")
    specs = {
        "spo2": ("wellnessEpochSPO2DataDTOList", "epochTimestamp", "spo2Reading", None, (70, 100)),
        "respiration": ("wellnessEpochRespirationDataDTOList", "startTimeGMT", "respirationValue", "ms", (6, 30)),
        "heart_rate": ("sleepHeartRate", "startGMT", "value", "ms", (30, 220)),
    }
    if metric not in specs:
        raise ValueError(f"Unknown sleep metric: {metric}")
    list_key, time_key, value_key, unit, bounds = specs[metric]
    rows = root.get(list_key)
    column = metric
    if rows is None:
        LOGGER.warning("Garmin sleep response has no %s series (%s)", metric, list_key)
        return pd.DataFrame(columns=["timestamp", column])
    if not isinstance(rows, list):
        LOGGER.error("Unsupported Garmin sleep series %s: expected list", list_key)
        return pd.DataFrame(columns=["timestamp", column])
    accepted = []
    rejected = 0
    for row in rows:
        if not isinstance(row, dict):
            rejected += 1
            continue
        timestamp = _timestamp(row.get(time_key), unit)
        try:
            value = float(row.get(value_key))
        except (TypeError, ValueError):
            rejected += 1
            continue
        if pd.isna(timestamp) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            rejected += 1
            continue
        accepted.append((timestamp, value))
    if rejected:
        LOGGER.info("Discarded %d invalid %s sleep points", rejected, metric)
    frame = pd.DataFrame(accepted, columns=["timestamp", column])
    if not frame.empty:
        frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    LOGGER.info("Using %d high-resolution %s sleep points", len(frame), metric)
    return frame


def detect_events(spo2: pd.DataFrame, respiration: pd.DataFrame,
                  heart_rate: pd.DataFrame, sleep: dict | None = None,
                  baseline_minutes: int = 10, lead_minutes: int = 10,
                  follow_minutes: int = 5) -> list[dict]:
    """Find three-signal changes near each Garmin awake-stage entry.

    Against each metric's own median in the baseline interval (20 to 10 min
    before wake by default), inspect the low SpO2/respiration and high HR in
    the 10 min before through 5 min after wake. Require each change to exceed
    max(metric-specific floor, 1.5 x baseline MAD). This is a configurable
    exploratory rule, not a clinically validated definition.
    """
    if spo2.empty or respiration.empty or heart_rate.empty:
        return []
    if sleep is None:
        LOGGER.warning("No sleep-stage data: cannot anchor signal dips to awakenings")
        return []

    def change_around(frame: pd.DataFrame, column: str, wake: pd.Timestamp,
                      floor: float, direction: str) -> dict | None:
        times = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        values = pd.to_numeric(frame[column], errors="coerce")
        valid = pd.DataFrame({"timestamp": times, "value": values}).dropna()
        baseline = valid[(valid.timestamp >= wake - pd.Timedelta(minutes=baseline_minutes + lead_minutes)) &
                         (valid.timestamp < wake - pd.Timedelta(minutes=lead_minutes))].value
        dip = valid[(valid.timestamp >= wake - pd.Timedelta(minutes=lead_minutes)) &
                    (valid.timestamp <= wake + pd.Timedelta(minutes=follow_minutes))]
        if len(baseline) < 3 or dip.empty:
            return None
        center = float(baseline.median())
        mad = float((baseline - center).abs().median())
        threshold = max(floor, 1.5 * mad)
        row = dip.loc[dip.value.idxmin() if direction == "down" else dip.value.idxmax()]
        magnitude = center - float(row.value) if direction == "down" else float(row.value) - center
        if magnitude < threshold:
            return None
        return {"timestamp": row.timestamp, "value": float(row.value),
                "baseline": center, "drop": magnitude, "threshold": threshold}

    events = []
    for stage in sleep.get("sleep_levels", []):
        if stage.get("type") != "awake":
            continue
        wake = _timestamp(stage.get("start"))
        if pd.isna(wake):
            continue
        s_dip = change_around(spo2, "spo2", wake, 1.0, "down")
        r_dip = change_around(respiration, "respiration", wake, 0.5, "down")
        h_rise = change_around(heart_rate, "heart_rate", wake, 2.0, "up")
        if s_dip is None or r_dip is None or h_rise is None:
            continue
        events.append({"timestamp": s_dip["timestamp"],
                       "respiration_timestamp": r_dip["timestamp"],
                       "heart_rate_timestamp": h_rise["timestamp"],
                       "awake_start": wake, "spo2": s_dip["value"],
                       "spo2_baseline": s_dip["baseline"], "spo2_drop": s_dip["drop"],
                       "respiration": r_dip["value"],
                       "respiration_baseline": r_dip["baseline"],
                       "respiration_drop": r_dip["drop"],
                       "heart_rate": h_rise["value"],
                       "heart_rate_baseline": h_rise["baseline"],
                       "heart_rate_rise": h_rise["drop"], "awake_following": True})
    return events


def mark_awakenings(events: list[dict], sleep: dict, wake_window_minutes: int) -> None:
    window = pd.Timedelta(minutes=wake_window_minutes)
    intervals = []
    for stage in sleep["sleep_levels"]:
        if stage["type"] != "awake":
            continue
        start, end = _timestamp(stage["start"]), _timestamp(stage["end"])
        if not pd.isna(start) and not pd.isna(end):
            intervals.append((start, end))
    for event in events:
        t = event["timestamp"]
        anchored_wake = event.get("awake_start")
        anchored_match = (anchored_wake is not None and
                          t - pd.Timedelta(minutes=2) <= anchored_wake <= t + window)
        event["awake_following"] = anchored_match or any(
            t <= start <= t + window or t < end <= t + window for start, end in intervals)


def build_dashboard(sleep: dict, spo2: pd.DataFrame, respiration: pd.DataFrame,
                    heart_rate: pd.DataFrame, events: list[dict], target_date: str) -> Path:
    # One plotting grid and one sleep timeline. Each metric has a centered,
    # independently scaled y-axis so all three nightly means share a height.
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    valid_stages = []
    for stage in sleep["sleep_levels"]:
        start, end = _timestamp(stage["start"]), _timestamp(stage["end"])
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue
        valid_stages.append((start, end, stage["type"]))
        # Plotly 7.1's add_vrect() silently adds no shapes in this environment.
        # Use explicit paper-height rectangles so every sleep phase is visible
        # across the single shared timeline, behind both metric traces.
        fig.add_shape(type="rect", xref="x", yref="paper",
                      x0=start, x1=end, y0=0, y1=1,
                      fillcolor=STAGE_COLORS[stage["type"]],
                      line={"width": 0}, layer="below")
    # Tint the analysis window and mark the awake-stage entry for each hit.
    for number, event in enumerate(events, start=1):
        wake = event.get("awake_start")
        if wake is None:
            continue
        fig.add_shape(type="rect", xref="x", yref="paper",
                      x0=wake - pd.Timedelta(minutes=10),
                      x1=wake + pd.Timedelta(minutes=5), y0=0, y1=1,
                      fillcolor="rgba(255, 54, 92, 0.12)",
                      line={"width": 0}, layer="below")
        fig.add_shape(type="line", xref="x", yref="paper",
                      x0=wake, x1=wake, y0=0, y1=1,
                      line={"color": "#ff365c", "width": 2, "dash": "dash"},
                      layer="above")
        fig.add_annotation(x=wake, y=1, xref="x", yref="paper",
                           text=f"#{number} ПРОБУЖДЕНИЕ", showarrow=False,
                           yshift=15, bgcolor="#ff365c", bordercolor="#ffffff",
                           borderwidth=1, borderpad=4,
                           font={"color": "#ffffff", "size": 10})
    if not spo2.empty:
        fig.add_trace(go.Scatter(x=spo2.timestamp, y=spo2.spo2, name="SpO₂",
                                 mode="lines", line={"color": "#f4f4f4", "width": 2.4},
                                 hovertemplate="SpO₂: %{y:.1f}%<extra></extra>"),
                      row=1, col=1, secondary_y=True)
    if not respiration.empty:
        fig.add_trace(go.Scatter(x=respiration.timestamp, y=respiration.respiration,
                                 name="Дыхание", mode="lines",
                                 line={"color": "#39c6ff", "width": 2.3},
                                 hovertemplate="Дыхание: %{y:.1f} вдох/мин<extra></extra>"),
                      row=1, col=1, secondary_y=False)
    if not heart_rate.empty:
        fig.add_trace(go.Scatter(x=heart_rate.timestamp, y=heart_rate.heart_rate,
                                 name="Пульс", mode="lines",
                                 line={"color": "#ffad33", "width": 2.2},
                                 hovertemplate="Пульс: %{y:.0f} уд/мин<extra></extra>", yaxis="y3"))
    # Bright, numbered markers make each three-signal match visible on all
    # three curves. Hover shows the local baseline and size of each change.
    marker_specs = [
        ("spo2", "timestamp", "spo2_drop", "spo2_baseline", "y2", "#ff3158", "%"),
        ("respiration", "respiration_timestamp", "respiration_drop", "respiration_baseline", "y", "#00e5ff", " вдох/мин"),
        ("heart_rate", "heart_rate_timestamp", "heart_rate_rise", "heart_rate_baseline", "y3", "#ffd60a", " уд/мин"),
    ]
    for index, (column, time_key, delta_key, baseline_key, axis, color, unit) in enumerate(marker_specs):
        if not events:
            continue
        fig.add_trace(go.Scatter(
            x=[event[time_key] for event in events],
            y=[event[column] for event in events],
            mode="markers+text" if column == "spo2" else "markers",
            text=[f"#{i}" for i in range(1, len(events) + 1)] if column == "spo2" else None,
            textposition="top center",
            textfont={"color": color, "size": 12, "family": "Arial Black"},
            marker={"symbol": "circle", "size": 16, "color": color,
                    "line": {"color": "#ffffff", "width": 2}},
            name=f"Метка {column}", showlegend=False, yaxis=axis,
            customdata=[[i, event["awake_start"].strftime("%H:%M"),
                         event[baseline_key], event[delta_key]]
                        for i, event in enumerate(events, start=1)],
            hovertemplate=(f"Совпадение #%{{customdata[0]}}<br>Пробуждение: "
                           f"%{{customdata[1]}}<br>Значение: %{{y:.1f}}{unit}<br>"
                           f"Локальный уровень: %{{customdata[2]:.1f}}{unit}<br>"
                           f"Отклонение: %{{customdata[3]:.1f}}{unit}<extra></extra>")))
    if events:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                 name=f"Совпадение 3 сигналов · {len(events)}",
                                 marker={"symbol": "circle", "size": 12, "color": "#ff365c",
                                         "line": {"color": "#ffffff", "width": 2}}),
                      row=1, col=1, secondary_y=True)
    stage_labels = {"awake": "Бодрствование", "deep": "Глубокий", "light": "Лёгкий", "rem": "REM"}
    for stage_name, color in STAGE_COLORS.items():
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=stage_labels[stage_name],
                                 marker={"symbol": "square", "size": 10, "color": color}),
                      row=1, col=1, secondary_y=False)
    def centered_axis(values: pd.Series, padding: float = 1.15) -> list[float] | None:
        if values.empty:
            return None
        numeric = pd.to_numeric(values, errors="coerce").dropna()
        if numeric.empty:
            return None
        mean = float(numeric.mean())
        q_low, q_high = (float(x) for x in numeric.quantile([0.05, 0.95]))
        half = max(mean - q_low, q_high - mean, 0.5) * padding
        return [mean - half, mean + half]

    respiration_range = centered_axis(respiration["respiration"])
    spo2_range = centered_axis(spo2["spo2"])
    heart_rate_range = centered_axis(heart_rate["heart_rate"])
    x_start = min((start for start, _, _ in valid_stages), default=None)
    x_end = max((end for _, end, _ in valid_stages), default=None)
    if x_start is None:
        timestamps = [pd.to_datetime(frame.timestamp, utc=True).min()
                      for frame in (spo2, respiration) if not frame.empty]
        ends = [pd.to_datetime(frame.timestamp, utc=True).max()
                for frame in (spo2, respiration) if not frame.empty]
        x_start = min(timestamps) if timestamps else None
        x_end = max(ends) if ends else None
    fig.update_layout(template="plotly_dark", height=760, hovermode="x unified",
                      title={"text": f"СОН · {target_date}<br><sup>{len(spo2):,} SpO₂ точек · "
                                      f"{len(events)} трёхсигнальных совпадений</sup>",
                             "x": 0.04, "xanchor": "left", "font": {"size": 22}},
                      legend={"orientation": "h", "y": 1.10, "x": 0.02,
                              "bgcolor": "rgba(14, 20, 32, 0.82)", "bordercolor": "#34445a",
                              "borderwidth": 1, "font": {"size": 11}},
                      margin={"t": 135, "b": 105, "l": 90, "r": 150},
                      xaxis={"title": "Время", "domain": [0.08, 0.83]},
                      yaxis3={"overlaying": "y", "side": "right",
                              "anchor": "free", "position": 0.99, "range": heart_rate_range,
                              "showgrid": False, "tickfont": {"color": "#ffad33"},
                              "title": {"text": "Пульс, уд/мин", "font": {"color": "#ffad33"}}})
    fig.update_layout(yaxis2={"anchor": "free", "position": 0.90,
                              "tickfont": {"color": "#f4f4f4"}})
    if x_start is not None and x_end is not None and x_end > x_start:
        fig.update_xaxes(range=[x_start, x_end])
    fig.update_yaxes(title_text="Дыхание, вдохов/мин", range=respiration_range, secondary_y=False)
    fig.update_yaxes(title_text="SpO₂, %", range=spo2_range, secondary_y=True)
    fig.update_xaxes(showgrid=True, gridcolor="rgba(190, 205, 225, 0.12)",
                     linecolor="#516176", tickfont={"color": "#c4d0df"},
                     rangeslider={"visible": False})
    fig.update_yaxes(showgrid=True, gridcolor="rgba(190, 205, 225, 0.14)",
                     linecolor="#516176", tickfont={"color": "#c4d0df"})
    fig.update_layout(plot_bgcolor="#0b1220", paper_bgcolor="#080d17",
                      font={"family": "Segoe UI, Arial, sans-serif", "color": "#e9f0f8"},
                      hoverlabel={"bgcolor": "#121d2d", "bordercolor": "#8092aa",
                                  "font": {"color": "#ffffff", "size": 12}},
                      uirevision=f"sleep-{target_date}")
    fig.add_annotation(text="Цветные блоки — фазы сна · розовая зона и вертикальный пунктир — окно совпадения у пробуждения",
                       xref="paper", yref="paper", x=0, y=-0.19, showarrow=False,
                       align="left", font={"size": 11, "color": "#aebbd0"})
    path = REPORTS_DIR / f"sleep_report_{target_date}.html"
    fig.write_html(str(path), include_plotlyjs=True, full_html=True)
    LOGGER.info("Saved interactive dashboard: %s", path)
    return path


def summary_text(target_date: str, sleep: dict, spo2: pd.DataFrame,
                 respiration: pd.DataFrame, heart_rate: pd.DataFrame,
                 events: list[dict], daily_status: dict | None = None) -> str:
    def mean_text(frame: pd.DataFrame, column: str) -> str:
        return "—" if frame.empty else f"{frame[column].mean():.1f}"

    total_minutes = int(sleep["sleep_time_seconds"] // 60)
    hours, minutes = divmod(total_minutes, 60)
    text = (f"🌙 Garmin — ночь / night {target_date}\n\n"
            f"<b>✔️ Match (probably Apnoe): {len(events)}</b>\n"
            f"Total sleep: {hours}h {minutes:02d}min\n"
            f"SpO₂, avg.: {mean_text(spo2, 'spo2')}%\n"
            f"Respiration avg.: {mean_text(respiration, 'respiration')} breaths/min\n"
            f"HR avg.: {mean_text(heart_rate, 'heart_rate')} bpm")
    if daily_status:
        text += "\n\n<b>Daily recovery check</b>"
        battery = daily_status.get("body_battery")
        readiness = daily_status.get("training_readiness")
        if battery is None:
            text += "\nBody Battery: no current reading"
        else:
            text += f"\nBody Battery: {battery}/100"
        if readiness:
            score = readiness.get("score")
            level = readiness.get("level")
            if score is not None:
                label = f"{score}/100" + (f" · {level}" if level else "")
                text += f"\nTraining Readiness: {label}"
            elif level:
                text += f"\nTraining Readiness: {level}"
            feedback = readiness.get("feedback")
            if feedback:
                text += f"\nGarmin: {html.escape(feedback)}"
        else:
            text += "\nTraining Readiness: no current reading"
        if daily_status.get("low_recovery"):
            text += ("\n<b>Low recovery reserve:</b> consider rest or an easy session "
                     "today. This is a training-load prompt, not medical advice.")
    return text


def _as_object_list(raw: Any, label: str) -> list[dict]:
    """Accept the documented single-object/list response forms only."""
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list) and all(isinstance(item, dict) for item in raw):
        return raw
    if raw in (None, []):
        return []
    raise PipelineError(f"Unsupported {label} response shape: {type(raw).__name__}")


def fetch_daily_recovery(garmin: Garmin, current_date: str, now: datetime) -> dict:
    """Read Body Battery samples and Training Readiness snapshots explicitly.

    Garmin's Body Battery endpoint documents [epoch-milliseconds, level]
    pairs in bodyBatteryValuesArray. No other arrays are searched. The latest
    valid sample at or before `now` is used. Both endpoints are optional for
    pipeline continuity: endpoint/shape failures are logged and reported as
    unavailable rather than blocking the sleep report.
    """
    result: dict[str, Any] = {"body_battery": None, "training_readiness": None,
                              "low_recovery": False}
    max_age_minutes = int(os.getenv("BODY_BATTERY_MAX_AGE_MINUTES", "120"))
    if max_age_minutes < 1:
        raise PipelineError("BODY_BATTERY_MAX_AGE_MINUTES must be at least 1")
    body_fn = getattr(garmin, "get_body_battery", None)
    if callable(body_fn):
        try:
            entries = _as_object_list(call_retry(
                "get_body_battery", lambda: body_fn(current_date, current_date), attempts=2),
                "Body Battery")
            samples: list[tuple[pd.Timestamp, int]] = []
            for entry in entries:
                values = entry.get("bodyBatteryValuesArray")
                if values is None:
                    continue
                if not isinstance(values, list):
                    raise PipelineError("Unsupported bodyBatteryValuesArray shape")
                for pair in values:
                    if not isinstance(pair, list) or len(pair) != 2:
                        LOGGER.warning("Skipping malformed Body Battery sample")
                        continue
                    try:
                        ts = pd.to_datetime(pair[0], unit="ms", utc=True, errors="coerce")
                        level = float(pair[1])
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if pd.isna(ts) or not math.isfinite(level) or not 0 <= level <= 100:
                        continue
                    now_utc = pd.Timestamp(now.astimezone(ZoneInfo("UTC")))
                    age_minutes = (now_utc - ts).total_seconds() / 60
                    if 0 <= age_minutes <= max_age_minutes:
                        samples.append((ts, int(round(level))))
                    elif age_minutes > max_age_minutes:
                        LOGGER.debug("Ignoring stale Body Battery sample (%.0f min old)", age_minutes)
            if samples:
                result["body_battery"] = max(samples, key=lambda item: item[0])[1]
            else:
                LOGGER.info("No valid Body Battery samples for %s", current_date)
        except Exception as exc:
            LOGGER.warning("Body Battery unavailable: %s", exc)
    else:
        LOGGER.info("Installed garminconnect has no get_body_battery method")

    readiness_fn = getattr(garmin, "get_training_readiness", None)
    if callable(readiness_fn):
        try:
            snapshots = _as_object_list(call_retry(
                "get_training_readiness", lambda: readiness_fn(current_date), attempts=2),
                "Training Readiness")
            valid = []
            for item in snapshots:
                score = item.get("score")
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    score = None
                elif not 0 <= score <= 100:
                    score = None
                timestamp = item.get("timestampLocal") or item.get("timestamp") or ""
                valid.append({"score": int(score) if score is not None else None,
                              "level": item.get("level") if isinstance(item.get("level"), str) else None,
                              "feedback": item.get("feedbackShort") if isinstance(item.get("feedbackShort"), str) else None,
                              "timestamp": str(timestamp)})
            if valid:
                result["training_readiness"] = max(valid, key=lambda item: item["timestamp"])
        except Exception as exc:
            LOGGER.warning("Training Readiness unavailable: %s", exc)
    else:
        LOGGER.info("Installed garminconnect has no get_training_readiness method")

    battery = result["body_battery"]
    readiness = result["training_readiness"]
    level = (readiness or {}).get("level", "").strip().upper()
    score = (readiness or {}).get("score")
    low_readiness = level in {"LOW", "POOR", "VERY_LOW", "VERY LOW"} or (score is not None and score < 50)
    # Garmin's own Body Battery scale describes 5–25 as very low reserve.
    result["low_recovery"] = (battery is not None and battery <= 25) or low_readiness
    LOGGER.info("Daily recovery values: Body Battery=%s, Training Readiness=%s",
                battery, readiness)
    return result


def telegram_request(url: str, *, data: dict, files: dict | None = None) -> None:
    last = None
    for attempt in range(1, 4):
        try:
            response = requests.post(url, data=data, files=files, timeout=(10, 60))
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                raise PipelineError(f"Telegram API rejected request: {body.get('description', 'unknown error')}")
            return
        except (requests.RequestException, ValueError, PipelineError) as exc:
            last = exc
            if attempt < 3:
                LOGGER.warning("Telegram delivery failed (%d/3): %s", attempt, exc)
                time.sleep(attempt * 2)
    raise PipelineError(f"Telegram delivery failed after retries: {last}") from last


def send_telegram(path: Path, text: str) -> None:
    token, chat_id = env_required("TG_BOT_TOKEN"), env_required("TG_CHAT_ID")
    base = f"https://api.telegram.org/bot{token}"
    telegram_request(base + "/sendMessage",
                     data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    with path.open("rb") as document:
        telegram_request(base + "/sendDocument",
                         data={"chat_id": chat_id,
                               "caption": "Двуязычный PDF-отчёт сна / Bilingual sleep report"},
                         files={"document": (path.name, document, "application/pdf")})
    LOGGER.info("Report sent to Telegram")


def main() -> int:
    try:
        tz = setup()
        night_start = int(os.getenv("NIGHT_START_HOUR", "18"))
        if not 0 <= night_start <= 23:
            raise PipelineError("NIGHT_START_HOUR must be from 0 to 23")
        target = last_night(datetime.now(tz), night_start).isoformat()
        current_date = datetime.now(tz).date().isoformat()
        LOGGER.info("Collecting overnight data for Garmin date %s (%s)", target, tz.key)
        garmin = init_garmin()
        raw_sleep, raw_spo2, raw_respiration = fetch_data(garmin, target)
        sleep = sleep_data(raw_sleep)
        LOGGER.info("Parsed %d sleep-stage intervals", len(sleep["sleep_levels"]))
        if not sleep["sleep_levels"]:
            LOGGER.warning("Garmin sleep response contained no recognized sleepLevels; stage bands cannot be drawn")
        # Use the dense overnight samples bundled in Garmin's sleep payload;
        # daily acclimation endpoints can be hourly and flatten SpO2 dips.
        spo2 = sleep_metric_frame(raw_sleep, "spo2")
        if spo2.empty:
            LOGGER.warning("No dense sleep SpO2; using daily endpoint fallback")
            spo2 = metric_frame(raw_spo2, "spo2")
        respiration = sleep_metric_frame(raw_sleep, "respiration")
        if respiration.empty:
            LOGGER.warning("No sleep respiration epochs; using daily endpoint fallback")
            respiration = metric_frame(raw_respiration, "respiration")
        heart_rate = sleep_metric_frame(raw_sleep, "heart_rate")
        events = detect_events(spo2, respiration, heart_rate, sleep,
                               baseline_minutes=int(os.getenv("DIP_BASELINE_MINUTES", "10")),
                               lead_minutes=int(os.getenv("DIP_LEAD_MINUTES", "10")),
                               follow_minutes=int(os.getenv("DIP_FOLLOW_MINUTES", "5")))
        mark_awakenings(events, sleep, int(os.getenv("WAKE_WINDOW_MINUTES", "10")))
        LOGGER.info("Detected %d three-signal wake-associated events", len(events))
        html_path = build_dashboard(sleep, spo2, respiration, heart_rate, events, target)
        pdf_path = REPORTS_DIR / f"sleep_report_{target}.pdf"
        pdf_report.render_pdf(sleep, spo2, respiration, heart_rate, events,
                              target, tz.key, pdf_path)
        LOGGER.info("Saved bilingual PDF report: %s", pdf_path)
        # Recovery metrics describe the current day, while sleep metrics are
        # keyed by the Garmin date of the overnight session.
        daily_status = fetch_daily_recovery(garmin, current_date, datetime.now(tz))
        send_telegram(pdf_path, summary_text(target, sleep, spo2, respiration,
                                             heart_rate, events, daily_status))
        return 0
    except Exception as exc:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.exception("Pipeline stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
