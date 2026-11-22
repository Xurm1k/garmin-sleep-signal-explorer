# Portfolio case study: Garmin Sleep Signal Explorer

## The question

Could a small data pipeline make overnight Garmin measurements easier to inspect around the watch's own awake-stage labels?

I used AI-assisted coding to build the project. My contribution was defining the question and acceptance criteria, reviewing Garmin charts against generated reports, reporting parsing and visualization failures, deciding which data checks mattered, and keeping the claims within what the available data can support.

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
