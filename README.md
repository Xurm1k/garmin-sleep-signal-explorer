# Garmin Sleep Signal Explorer

Garmin Sleep Signal Explorer looks at one specific question: do changes in SpO₂, respiration rate, and heart rate show up near a Garmin-labeled awakening? The Python pipeline reads an overnight session, checks selected fields, aligns the signals with sleep stages, and creates a PDF and interactive HTML report. Telegram delivery is optional.

For the decisions behind the project and an honest description of my role, see [PORTFOLIO_CASE_STUDY.md](PORTFOLIO_CASE_STUDY.md).

This is a personal data exploration project, not a medical tool. It cannot diagnose a sleep disorder or estimate health risk.

## What it does

1. Reads Garmin credentials from `.env`; Telegram credentials are needed only for delivery.
2. Fetches the latest overnight session in the configured time zone.
3. Reads known Garmin fields. If a response has an unfamiliar shape, the pipeline logs it instead of guessing.
4. Rejects values outside the configured ranges before analysis: SpO₂ 70–100%, respiration 6–30 breaths/min, and heart rate 30–220 bpm.
5. Plots Garmin sleep stages behind the signals.
6. Marks a **signal match** when SpO₂ and respiration fall and heart rate rises near a Garmin awake-stage entry.
7. Saves the HTML and PDF in `reports/`. If Telegram credentials are set, it also sends the PDF and a short summary.
8. Adds the latest fresh Body Battery and Training Readiness readings to the Telegram summary. Low readings prompt a gentle rest/easy-session reminder.

## Daily recovery reminder

After the watch syncs, the pipeline reads Body Battery samples for the current local date and the latest Training Readiness snapshot. It reports Body Battery only when the sample is no more than `BODY_BATTERY_MAX_AGE_MINUTES` old (default: 120 minutes). If no fresh sample is available, it reports that instead of reusing stale data.

The reminder is triggered at Body Battery 25 or below, or Training Readiness below 50 / a Garmin level of `LOW` or `POOR`. The thresholds are practical project rules, not clinical guidance. The reminder suggests considering rest or an easy session; it does not decide whether training is medically safe. The Training Readiness endpoint is exposed by the community `garminconnect` package and may change without notice. If recovery endpoints fail, the overnight sleep report still proceeds.

## Garmin Connect cards and notifications

Garmin Connect has separate push-notification preferences (`More > Settings > Notifications > Push Notifications`), so check whether an `Insights` option is available and enabled before assuming a card cannot generate a push. Garmin describes classic Insights as an in-app section whose statistics refresh daily. Garmin's Connect+ Active Intelligence insights are explicitly app-only. The project solves a related workflow gap by sending its own scheduled Telegram summary; it does not change Garmin Connect notification settings or reproduce Garmin's full coaching cards.

## How to interpret a “signal match”

I wanted to check whether changes in three signals appeared close to the awake intervals in Garmin's chart. For each awake-stage entry, the rule compares the signals with their own median values from 20 to 10 minutes beforehand. It then looks from 10 minutes before through 5 minutes after the entry. A change must clear a small minimum and 1.5 times the baseline's median absolute deviation.

I chose these windows and thresholds for this exploration; they have not been clinically validated. Garmin sleep stages are estimates, and the samples can miss short events. A match only says the rule found the three changes in its search window. It does not identify why they happened. The data available to this project also lack the airflow signal used in clinical respiratory-event scoring.

The local experimental `pipeline1.py` is not part of this public copy. Its custom “ODI3-like” counter used project-selected rules, so it should not be described as a clinical ODI3, hypopnea estimate, or risk score.

## Project structure

```text
garmin-sleep-signals/
├── pipeline.py       # Garmin collection, parsing, event logic, Plotly, Telegram
├── pdf_report.py     # Static PDF report renderer
├── requirements.txt
├── .env.example      # Variable names only; no credentials
├── .gitignore
├── README.md
└── PORTFOLIO_CASE_STUDY.md
```

## Setup

Requirements: Python 3.10 or newer, a Garmin Connect account, and (optionally) a Telegram bot and chat ID.

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill it in on your computer. Never commit `.env`.

```env
GARMIN_EMAIL=your-email@example.com
GARMIN_PASSWORD=your-new-password
TG_BOT_TOKEN=your-new-bot-token
TG_CHAT_ID=your-chat-id
GARMIN_TIMEZONE=Europe/Berlin
BODY_BATTERY_MAX_AGE_MINUTES=120
```

Telegram variables are needed only if you want delivery. Keep them blank or omit them if you only want local reports. Do not paste secrets into source code, screenshots, issue trackers, or public chat. If a credential was exposed, rotate it before using this project again.

## Run

```bash
python pipeline.py
```

The script selects the latest overnight session using `GARMIN_TIMEZONE` and `NIGHT_START_HOUR` (default `18`). Reports go to `reports/`. Leave the Telegram variables out of `.env` to keep the run local; add them if you want the PDF and summary sent to your chat.

To receive the recovery reminder each morning, run the pipeline after the watch has synchronized. On Windows, create a daily Task Scheduler task with **Program** set to `<project>\venv\Scripts\python.exe`, **Arguments** set to `<project>\pipeline.py`, and **Start in** set to the project folder. If you move the folder, update all three paths in the task.

Optional event-window settings:

```env
DIP_BASELINE_MINUTES=10
DIP_LEAD_MINUTES=10
DIP_FOLLOW_MINUTES=5
WAKE_WINDOW_MINUTES=10
NIGHT_START_HOUR=18
```

The source defaults define the baseline, lead, and follow windows in relation to an awake-stage entry. Review `detect_events()` before changing them; a changed rule changes the meaning of the reported count.

## Publish this project on GitHub

1. Use the cleaned folder from this archive. Do not upload the Garmin project folder from your computer as-is.
2. Keep `.env`, `reports/`, logs, cached Garmin responses, screenshots, virtual environments, and exports off GitHub. `.gitignore` excludes the common local files.
3. Before committing, inspect the staged file list and search for credentials, chat IDs, dates, and personal health data. Do not use a real night's report as a public example.
4. Create an empty repository on GitHub, then run the commands below from the project folder. Review every staged file before committing.
5. Choose a license only after checking what you want others to be allowed to do with the project and the licenses of its dependencies.

Repository description:

> An exploratory Garmin sleep-data pipeline for signal validation, overnight visualization, and transparent event-window analysis.

Topics: `python`, `data-visualization`, `garmin-connect`, `plotly`, `matplotlib`, `sleep-data`.

In PowerShell, from the project folder:

```powershell
git init -b main
git add --all
git status --short
git diff --cached --check
git diff --cached --name-only
# Review the staged files before committing.
git commit -m "Prepare Garmin sleep signal analysis portfolio project"
git remote add origin https://github.com/YOUR-USERNAME/garmin-sleep-signal-explorer.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your GitHub username. If Git reports that `origin` already exists, check it with `git remote -v` before changing anything. If a secret ever reaches GitHub, revoke or rotate it; deleting the file alone does not remove it from history.

## Portfolio framing

The implementation used AI-assisted coding. The project owner's work was to define the question, set requirements for the Garmin fields and value checks, compare the generated reports with Garmin's own charts, steer revisions when parsing failed, and limit the claims to what the data support. In a portfolio or interview, describe those decisions and distinguish project direction from code authorship.

## Limitations and privacy

- Garmin Connect response formats can change, and this project uses a community library rather than an official Garmin API contract.
- Garmin's insight cards and notification behavior depend on the feature type and user settings; this pipeline does not forward Garmin's original card text.
- Missing samples are not interpolated into evidence of a physiological event.
- Sensor readings are estimates and have varying sampling intervals and confidence.
- Event counts depend on user-selected windows and thresholds.
- Reports contain sensitive health data. Store them locally and share them only with informed consent.
- This repository is for personal exploration, not diagnosis or treatment.

## Acknowledgements

The project uses the community-maintained `python-garminconnect` library and open-source plotting and data tools. It is not affiliated with Garmin.

Clinical boundary reference: the [American Academy of Sleep Medicine diagnostic testing guideline](https://aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf) recommends polysomnography or technically adequate home sleep apnea testing for diagnosis; consumer wearable pattern matching is not a diagnostic substitute. The AASM's [respiratory scoring criteria](https://isr.aasm.org/helpv6/ScoringRespiratoryEventsR.html) include airflow-signal requirements that this project does not measure.

Garmin references: [Insights in Garmin Connect](https://support.garmin.com/en-US/?faq=c3DcuWOsuW0BiEjv94eIm5), [customizing push notifications](https://support.garmin.com/en-IE/?faq=JIk40ZUqX26kyblDLHgbD8), and [Active Intelligence availability](https://support.garmin.com/en-MY/?faq=kWi5DoaMPZ4VCJBA0lFWP7).
