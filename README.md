# Garmin Sleep Signal Explorer

A Python workflow for making Garmin sleep and recovery context easier to notice and review. It validates overnight signals, produces local HTML/PDF reports, and can send daily recovery summaries through Telegram. A local journal and optional weekly Gemini review help preserve context over time.

I built it around a practical gap: relevant recovery information can be easy to miss when it is spread across screens and reports. The project surfaces selected metrics and its own rule-based reminders; it does not forward or replace Garmin's recommendations. A detected “match” is an exploratory window for review, not an event, diagnosis, risk estimate, or proof of cause.

## Features

- Explicit extraction from known Garmin response structures; unsupported shapes are logged instead of guessed.
- Input validation for SpO₂, respiration, and heart-rate data before analysis.
- Sleep stages behind signal traces on one overnight timeline.
- Local-baseline comparisons around Garmin awake-stage labels.
- Local PDF/HTML reports and optional Telegram delivery.
- SQLite storage for nightly summaries, journal notes, and manual measurements.
- Optional Gemini chat and weekly review. When enabled, selected local context is sent to Google's API.
- Telegram text/photo intake with an acknowledgement after local storage.

## Choose a deployment

| Option | Advantage | Requirement |
|---|---|---|
| **A. Linux server** | Runs while your PC is off | Cloud VM, outbound connectivity, and provider capacity |
| **B. Windows PC as server** | Keeps the data on your computer | PC must be on, awake, connected, and able to reach the services |

Both use this same project. Personal data and credentials stay in local `.env`, `data/`, and `reports/` files; none belong in GitHub.

## A. Linux server with systemd

Example systemd units are in `cloud/`. They assume `/opt/garmin-sleep` and a dedicated `garminbot` service account. Adjust these values if your installation differs.

1. Create and secure a Linux VM; confirm outbound internet access.
2. Copy the project source to the VM. Do not copy a personal archive or a public report.
3. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
4. Create a private `.env` and local `data/` directory. Restrict permissions to the service account.
5. Review and copy the unit files from `cloud/` to `/etc/systemd/system/`; adjust paths and account names as needed.
6. Enable the Telegram listener and the daily timer, then inspect their status and logs.
7. Add `GEMINI_API_KEY` to the private `.env` only if you want Gemini replies and the Sunday review.

The timer is scheduled for 08:30 local server time, with up to five minutes of randomized delay and catch-up after downtime. Confirm the server timezone and next scheduled time. Cloud free-tier availability, capacity, and pricing can change; check the provider's current terms.

## B. Windows PC as a small server

1. Install Python 3.10 or newer. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and enter your own credentials locally.
3. In Windows Task Scheduler, create a daily task for `pipeline.py` after the watch has synced. Set **Program** to the virtual environment's `python.exe`, **Arguments** to the full path of `pipeline.py`, and **Start in** to the project folder.
4. Create a separate startup/sign-in task for `telegram_intake.py`. The included hidden launcher is an example; review its paths before use and configure restart after failure.
5. Enable **Run task as soon as possible after a scheduled start is missed** if desired. Prevent sleep during the run: shutdown, hibernation, lost internet, or a moved folder interrupts the schedule.

The supplied Windows launchers are examples and may need path adjustments.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Example `.env` keys (use your own values):

```env
GARMIN_EMAIL=your-garmin-email
GARMIN_PASSWORD=your-garmin-password
TG_BOT_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-telegram-chat-id
GARMIN_TIMEZONE=Etc/UTC
GEMINI_API_KEY=optional-gemini-key
```

Telegram and Gemini are optional. Review the code and external data flows before enabling either service.

## Project files

```text
pipeline.py                 Garmin collection, validation, analysis, and delivery
pdf_report.py               Bilingual PDF rendering
health_store.py             Local SQLite journal and weekly summaries
telegram_intake.py          Telegram long-poll listener
gemini_health_review.py     Optional Gemini chat and weekly review
cloud/                      Example systemd services and timer
tests/                      Focused tests
.env.example                Placeholder configuration
```

## Privacy

Never commit `.env`, credentials, `data/`, `reports/`, logs, screenshots, archives, SSH keys, or virtual environments. `.gitignore` excludes common local files; inspect the staged file list before each commit. If a secret was pushed, rotate it—deleting a file does not remove it from Git history.

Telegram notes/photos are sent through Telegram. If Gemini is enabled, selected context is sent to Google's API. Use the integrations only if their data handling fits your needs.

## Limitations

Garmin response formats may change; this project uses a community library, not a stable official API contract. Wearable readings and sleep stages are estimates, may contain gaps, and do not include the airflow measurements used in clinical respiratory-event scoring. The thresholds and event windows are exploratory and have not been clinically validated. Discuss persistent symptoms with a qualified clinician.

Not affiliated with Garmin. Optional AI summaries can be wrong and are not professional medical advice.


## Portfolio case study

[Read the case study](./PORTFOLIO_CASE_STUDY.md) for the problem framing, data-quality controls, workflow automation, privacy decisions, and my contribution as an Operations and Quality professional using AI-assisted coding.
