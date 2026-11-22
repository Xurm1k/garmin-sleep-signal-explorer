"""Bilingual Matplotlib PDF renderer used by pipeline.py."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, FancyBboxPatch

COLORS = {
    "ink": "#12233F", "muted": "#64748B", "grid": "#E4EAF1",
    "spo2": "#087E8B", "respiration": "#3977C3", "heart_rate": "#D66A4A",
    "event": "#DB3155", "awake": "#F28C45", "deep": "#264C7E",
    "light": "#8EC5E8", "rem": "#A878C2",
}
STAGE_NAMES = {"awake": "Бодрствование / Awake", "deep": "Глубокий / Deep",
               "light": "Лёгкий / Light", "rem": "Быстрый сон / REM"}

def _timestamp(value):
    return pd.to_datetime(value, utc=True, errors="coerce")

def _local_datetimes(series: pd.Series, tz: ZoneInfo):
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(tz).dt.tz_localize(None)

def _fmt(value: float | None, suffix: str = "") -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.1f}{suffix}"


def _summary_values(sleep: dict, spo2: pd.DataFrame, respiration: pd.DataFrame,
                    heart_rate: pd.DataFrame, events: list[dict]) -> list[tuple[str, str, str]]:
    s = spo2["spo2"] if not spo2.empty else pd.Series(dtype=float)
    r = respiration["respiration"] if not respiration.empty else pd.Series(dtype=float)
    h = heart_rate["heart_rate"] if not heart_rate.empty else pd.Series(dtype=float)
    return [
        ("ЧИСТЫЙ СОН / TOTAL SLEEP", f"{sleep['total_sleep_hours']:.2f} ч / h", "длительность сна / sleep duration"),
        ("SpO₂", f"{_fmt(s.min())} / {_fmt(s.mean())}", "мин. / ср. · min / mean, %"),
        ("ДЫХАНИЕ / RESPIRATION", f"{_fmt(r.mean())} / {_fmt(r.min())}", "ср. / мин. · mean / min, breaths/min"),
        ("ПУЛЬС / HEART RATE", f"{_fmt(h.mean())} / {_fmt(h.max())}", "ср. / макс. · mean / max, bpm"),
        ("СОВПАДЕНИЯ / MATCHES", str(len(events)), "SpO₂ ↓ · respiration ↓ · HR ↑"),
    ]


def render_pdf(sleep: dict, spo2: pd.DataFrame, respiration: pd.DataFrame,
               heart_rate: pd.DataFrame, events: list[dict], target_date: str,
               timezone_name: str, output_path: Path,
               preview_path: Path | None = None) -> Path:
    """Create a landscape PDF with shared time axis and dedicated metric tracks."""
    tz = ZoneInfo(timezone_name)
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.labelcolor": COLORS["muted"],
        "xtick.color": COLORS["muted"],
        "ytick.color": COLORS["muted"],
        "text.color": COLORS["ink"],
        "pdf.fonttype": 42,
    })
    fig = plt.figure(figsize=(15.5, 9.2), facecolor="#F7F9FC")
    outer = fig.add_gridspec(4, 1, height_ratios=[0.52, 0.82, 5.75, 0.28], hspace=0.10)

    # Header and summary strip.
    header = fig.add_subplot(outer[0])
    header.set_facecolor(COLORS["ink"])
    header.set_xticks([])
    header.set_yticks([])
    for spine in header.spines.values():
        spine.set_visible(False)
    header.text(0.025, 0.68, "SLEEP SIGNALS", color="#8EDBE1", fontsize=8,
                fontweight="bold", transform=header.transAxes)
    header.text(0.025, 0.18, f"Ночной профиль / Night profile · {target_date}", color="white",
                fontsize=18, fontweight="bold", transform=header.transAxes)
    header.text(0.975, 0.30, "SpO₂  ·  дыхание / respiration  ·  пульс / heart rate", color="#D7E2F0",
                fontsize=9, ha="right", transform=header.transAxes)
    summary_ax = fig.add_subplot(outer[1])
    summary_ax.set_axis_off()
    summary = _summary_values(sleep, spo2, respiration, heart_rate, events)
    for i, (label, value, detail) in enumerate(summary):
        x = 0.012 + i * 0.198
        box = FancyBboxPatch((x, 0.06), 0.184, 0.88,
                             boxstyle="round,pad=0.012,rounding_size=0.02",
                             transform=summary_ax.transAxes, facecolor="white",
                             edgecolor="#E5EAF1", linewidth=0.8)
        summary_ax.add_patch(box)
        summary_ax.text(x + 0.012, 0.77, label, color=COLORS["muted"], fontsize=7,
                        fontweight="bold", transform=summary_ax.transAxes)
        summary_ax.text(x + 0.012, 0.43, value, color=COLORS["ink"], fontsize=12,
                        fontweight="bold", transform=summary_ax.transAxes)
        summary_ax.text(x + 0.012, 0.19, detail, color=COLORS["muted"], fontsize=6.5,
                        transform=summary_ax.transAxes)

    tracks = outer[2].subgridspec(4, 1, height_ratios=[1.3, 1.0, 1.0, 0.48], hspace=0.12)
    axes = []
    for i in range(4):
        axes.append(fig.add_subplot(tracks[i], sharex=axes[0] if axes else None))
    ax_spo2, ax_resp, ax_hr, ax_stage = axes

    metric_specs = [
        (ax_spo2, spo2, "spo2", "SpO₂ / Сатурация", "%", COLORS["spo2"]),
        (ax_resp, respiration, "respiration", "Дыхание / Respiration", "вдох/мин · breaths/min", COLORS["respiration"]),
        (ax_hr, heart_rate, "heart_rate", "Пульс / Heart rate", "уд/мин · bpm", COLORS["heart_rate"]),
    ]
    for ax, frame, col, label, unit, color in metric_specs:
        ax.set_facecolor("white")
        ax.grid(axis="y", color=COLORS["grid"], linewidth=0.75)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color("#D6DEE8")
        ax.spines["bottom"].set_color("#D6DEE8")
        ax.tick_params(axis="both", length=0, labelsize=8)
        ax.set_ylabel(f"{label}\n{unit}", color=color, fontsize=8, fontweight="bold", rotation=0,
                      ha="right", va="center", labelpad=34)
        if frame.empty:
            ax.text(0.5, 0.5, "Нет данных / No data", color=COLORS["muted"], ha="center", va="center",
                    transform=ax.transAxes)
            continue
        x = _local_datetimes(frame["timestamp"], tz)
        y = frame[col].astype(float)
        ax.plot(x, y, color=color, linewidth=1.65, solid_capstyle="round", zorder=3)
        if len(y) > 1:
            ax.fill_between(x, y, float(y.median()), color=color, alpha=0.07, linewidth=0, zorder=1)
        low, high = float(y.quantile(0.02)), float(y.quantile(0.98))
        pad = max((high - low) * 0.18, 0.8)
        ax.set_ylim(low - pad, high + pad)

    # Sleep phases as a dedicated, labeled hypnogram strip and subtle bands
    # behind all three metrics.
    ax_stage.set_facecolor("white")
    ax_stage.set_ylim(0, 1)
    ax_stage.set_yticks([])
    ax_stage.set_ylabel("ФАЗЫ / STAGES", color=COLORS["muted"], fontsize=8, fontweight="bold",
                        rotation=0, ha="right", va="center", labelpad=34)
    for side in ("top", "right", "left"):
        ax_stage.spines[side].set_visible(False)
    ax_stage.spines["bottom"].set_color("#D6DEE8")
    for stage in sleep["sleep_levels"]:
        start, end = _timestamp(stage["start"]), _timestamp(stage["end"])
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue
        start_local, end_local = start.tz_convert(tz).tz_localize(None), end.tz_convert(tz).tz_localize(None)
        stage_type = stage["type"]
        color = COLORS[stage_type]
        ax_stage.axvspan(start_local, end_local, ymin=0.14, ymax=0.88, color=color, alpha=0.95,
                         linewidth=0, zorder=2)
        for ax in (ax_spo2, ax_resp, ax_hr):
            ax.axvspan(start_local, end_local, color=color, alpha=0.075, linewidth=0, zorder=0)
        width_minutes = (end_local - start_local).total_seconds() / 60
        if width_minutes >= 28:
            ax_stage.text(start_local + (end_local - start_local) / 2, 0.51,
                          STAGE_NAMES[stage_type], color="white", fontsize=6.5,
                          fontweight="bold", ha="center", va="center", clip_on=True, zorder=3)

    # A strong, consistent highlight across every panel for each matched event.
    signal_frames = {
        "spo2": (ax_spo2, spo2, "timestamp", "spo2", COLORS["event"], "↓"),
        "respiration": (ax_resp, respiration, "respiration_timestamp", "respiration", COLORS["respiration"], "↓"),
        "heart_rate": (ax_hr, heart_rate, "heart_rate_timestamp", "heart_rate", "#C47C00", "↑"),
    }
    event_handles = []
    for number, event in enumerate(events, start=1):
        wake = event.get("awake_start")
        if wake is None:
            continue
        wake_local = wake.tz_convert(tz).tz_localize(None)
        left, right = wake_local - pd.Timedelta(minutes=10), wake_local + pd.Timedelta(minutes=5)
        for ax in (ax_spo2, ax_resp, ax_hr, ax_stage):
            ax.axvspan(left, right, color=COLORS["event"], alpha=0.11, linewidth=0, zorder=1)
            ax.axvline(wake_local, color=COLORS["event"], linewidth=1.15,
                       linestyle=(0, (3, 2)), alpha=0.9, zorder=4)
        ax_spo2.annotate(f"E{number}",
                         (event["timestamp"].tz_convert(tz).tz_localize(None), event["spo2"]),
                         xytext=(0, 10), textcoords="offset points", ha="center",
                         color="white", fontsize=7, fontweight="bold",
                         bbox={"boxstyle": "round,pad=0.25", "fc": COLORS["event"], "ec": "white", "lw": 0.5},
                         zorder=7)
        for frame_key, (ax, frame, time_key, value_key, marker_color, direction) in signal_frames.items():
            if frame.empty or time_key not in event:
                continue
            xmark = event[time_key].tz_convert(tz).tz_localize(None)
            ax.scatter([xmark], [event[value_key]], s=56, marker="o", facecolor=marker_color,
                       edgecolor="white", linewidth=1.2, zorder=6)
        event_handles.append(Patch(facecolor=COLORS["event"], alpha=0.25,
                                   label=f"E{number} · пробуждение / wake {wake_local:%H:%M}"))

    phase_handles = [Patch(facecolor=COLORS[key], label=STAGE_NAMES[key])
                     for key in ("awake", "deep", "light", "rem")]
    axes_handles = [plt.Line2D([0], [0], color=color, lw=2, label=label)
                    for _, _, _, label, _, color in metric_specs]
    all_handles = axes_handles + phase_handles + event_handles
    fig.legend(handles=all_handles, loc="lower center", bbox_to_anchor=(0.5, 0.065),
               ncol=min(len(all_handles), 7), frameon=False, fontsize=7.5,
               handlelength=1.7, columnspacing=1.4)

    date_format = mdates.DateFormatter("%H:%M")
    ax_stage.xaxis.set_major_formatter(date_format)
    ax_stage.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=9))
    ax_stage.tick_params(axis="x", length=0, labelsize=8, pad=7)
    for ax in (ax_spo2, ax_resp, ax_hr):
        ax.tick_params(axis="x", labelbottom=False)
    all_times = []
    for frame in (spo2, respiration, heart_rate):
        if not frame.empty:
            all_times.extend(_local_datetimes(frame.timestamp, tz).dropna().tolist())
    for stage in sleep["sleep_levels"]:
        start, end = _timestamp(stage["start"]), _timestamp(stage["end"])
        if not pd.isna(start) and not pd.isna(end):
            all_times.extend([start.tz_convert(tz).tz_localize(None), end.tz_convert(tz).tz_localize(None)])
    if all_times:
        axes[0].set_xlim(min(all_times), max(all_times))
    ax_stage.set_xlabel(f"Время / Time ({timezone_name})", color=COLORS["muted"], fontsize=8, labelpad=7)

    fig.text(0.04, 0.975, "GARMIN CONNECT  /  НОЧНОЙ АНАЛИЗ · OVERNIGHT ANALYSIS", color=COLORS["muted"],
             fontsize=7, fontweight="bold")
    fig.text(0.96, 0.975, "PDF · MATPLOTLIB", color=COLORS["muted"],
             fontsize=7, ha="right")
    fig.text(0.04, 0.035,
             "Совпадение / Match: локальный спад SpO₂ и дыхания / local SpO₂ and respiration dips + рост пульса / HR rise "
             "около бодрствования / near wake. Исследовательская корреляция / Exploratory correlation; "
             "не диагноз и не доказательство причинности / not a diagnosis or proof of causation.",
             color=COLORS["muted"], fontsize=7)
    fig.subplots_adjust(left=0.12, right=0.95, top=0.965, bottom=0.115)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="pdf", facecolor=fig.get_facecolor(), bbox_inches="tight")
    if preview_path:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(preview_path, format="png", dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return output_path

