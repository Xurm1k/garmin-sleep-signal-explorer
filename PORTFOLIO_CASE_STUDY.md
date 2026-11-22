# Portfolio case study: Garmin Sleep Signal Explorer

## The problem

Garmin provides sleep and recovery metrics, but I found the daily context easy to miss when it required checking several screens and reports. I wanted a repeatable way to surface a concise recovery summary, inspect overnight signals around the watch's awake-stage labels, and keep a local record for later review.

The Telegram reminder uses selected recovery metrics and transparent project rules; it does not forward Garmin's proprietary recommendation text. The analysis remains exploratory and is not medical advice.

## Portfolio context

I approached this as an Operations Analytics problem: turn scattered measurements into a checked, reviewable workflow. The project demonstrates data validation, exception handling, recurring delivery, local record-keeping, and careful communication of uncertainty. AI-assisted coding accelerated implementation; I defined the use case and acceptance criteria, compared reports with Garmin charts, reported parsing and visualization failures, and kept the claims within what the data can support.

## The workflow

The pipeline collects an overnight session from Garmin Connect, extracts known fields explicitly, validates values before analysis, aligns signals with sleep-stage intervals, and creates an interactive HTML dashboard and a bilingual PDF. Optional components save local notes and measurements, deliver a Telegram report, and produce a concise weekly summary.

The analysis compares SpO₂, respiration, and heart-rate changes with a local baseline around Garmin-labeled awake intervals. It produces candidate windows for review. This is a transparent project rule, not a clinical scoring method.

## Decisions and constraints

- **Do not guess at response data.** Garmin responses can contain multiple arrays and descriptors. The parser uses known structures and logs unsupported shapes instead of recursively interpreting arbitrary numbers.
- **Validate before plotting.** Physiological bounds reject obvious artifacts before they affect charts or summaries.
- **Make the timeline reviewable.** Sleep stages sit behind the signal traces, and notable windows are marked for comparison with the source chart.
- **Keep private data local.** Credentials, journal entries, health profiles, reports, and database files are excluded from the public repository.
- **State the limits.** Wearable stage labels and sensor readings are estimates. The project lacks clinical airflow measurements and has not been validated against a sleep study.

## My contribution

I framed the use case, specified the data and validation requirements, compared generated outputs with Garmin's own visualizations, and directed revisions when the code failed to parse or display the data correctly. I also reviewed whether the event logic said more than the measurements justified and asked that the project distinguish an exploratory match from a medical event.

I used AI as a coding tool; I do not present the implementation as solo software authorship. The work I can demonstrate is product framing, requirements, output review, practical debugging feedback, privacy decisions, and clear communication of limitations.

## What this demonstrates

- Turning an open-ended question into explicit input, validation, and output requirements
- Reviewing an automated report against a source visualization and identifying mismatches
- Treating missing or unfamiliar data as an explicit condition rather than inventing values
- Separating exploratory signals from clinical conclusions
- Considering operational choices for PC and Linux-server deployments

## Next steps

1. Add synthetic Garmin-response fixtures for supported parser shapes.
2. Report sample coverage and time gaps alongside each signal.
3. Measure how results change when baseline and event windows change.
4. Provide a reproducible demo built entirely from synthetic data.

## Interview summary

“I used AI-assisted coding to build a Garmin data pipeline around a question I defined. I set requirements for explicit parsing and input checks, compared the output with the watch's charts, and steered revisions when the results did not line up. The result is an exploratory report, not a diagnostic tool.”
