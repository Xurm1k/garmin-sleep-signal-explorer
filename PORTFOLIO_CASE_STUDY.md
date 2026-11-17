# Portfolio case study: Garmin Sleep Signal Explorer

## The project

I started with a question from my Garmin sleep charts: do changes in oxygen saturation, respiration rate, and heart rate tend to appear near the watch's awake-stage labels?

I used AI-assisted coding to turn that question into a Python pipeline. My contribution was shaping the question into reviewable requirements, comparing its outputs with Garmin's charts, steering fixes when the API data did not parse as expected, and keeping the conclusions within what the data can support.

## What the pipeline does

- Reads overnight data from Garmin Connect.
- Uses explicit field mappings for known response shapes; it does not search arbitrary numeric arrays.
- Rejects values outside configured ranges before analysis.
- Aligns SpO₂, respiration, heart rate, and sleep-stage intervals on the overnight timeline.
- Marks windows where all three signals change near a Garmin awake-stage entry.
- Writes an interactive HTML dashboard and a PDF; Telegram delivery is optional.
- Adds a daily recovery snapshot using current Body Battery and Training Readiness, with a configurable freshness check for Body Battery and a cautious low-reserve prompt.

## A decision I had to make

The first version of the analysis treated large fixed drops as meaningful on their own. Looking at Garmin's charts made clear that the question was about changes around awakenings, not just isolated thresholds. The current rule compares each signal with its own local baseline and anchors the search window to an awake-stage entry.

That makes the output easier to review against the chart. It does not make the rule clinically valid. The window and thresholds are project choices, and a match is only a prompt to inspect a section of the timeline.

## What I personally contributed

- Defined the use case and the relationship I wanted to inspect between signals and awakenings.
- Required explicit Garmin fields and input-range checks after early parsing attempts returned empty or invalid data.
- Compared generated visualizations with Garmin's own overnight charts and asked for visible sleep stages and clearer event markers.
- Asked whether the custom ODI3-like counter was meaningful and how to describe it without presenting it as a clinical score.
- Focused the public explanation on the main question: which signals changed near an awakening label, and what that result cannot establish.
- Identified a usability gap in my routine: sleep and recovery context was scattered across Garmin Connect screens, so I wanted a single Telegram summary after the watch synced. I set requirements for Body Battery freshness and a restrained recovery reminder.

I used AI as a coding tool. My contribution was the problem framing, requirements, visual review, and interpretation of the results. That is the role I would describe in a portfolio and in an interview.

## Limits

The watch data available here do not include the airflow measurements used in clinical respiratory-event scoring. The watch's stage labels are estimates, its samples can miss short changes, and the selected thresholds have not been validated against a sleep study. This project cannot diagnose apnea or hypopnea, establish causation, or estimate risk.

## What I would do next

1. Add synthetic examples for the Garmin response shapes the parser supports.
2. Show sample coverage and time gaps next to each signal.
3. Check how much the results change when the baseline and event windows change.
4. Make a repeatable demo that uses synthetic data only.
5. If evaluating against clinical data ever becomes appropriate, agree on a method with a qualified sleep professional and use data with proper consent.

## How I would present it in an interview

Start with the question, then show the Garmin chart that prompted it. Explain that the API response was not as straightforward as one numeric list, what requirements you gave for parsing and validation, and how you reviewed the revised visual output. Finish with the main limitation: this is a way to inspect wearable patterns, not a diagnosis. Be open about using AI assistance and focus on how you framed, reviewed, and constrained the result.

## Resume wording

These bullets describe project direction and review, not solo software authorship:

- Defined the question, signal relationships, validation bounds, and event windows for an AI-assisted Garmin sleep-data project.
- Reviewed API-driven reports against Garmin charts and directed revisions to parsing and sleep-stage visualization.
- Documented privacy safeguards and the limits of interpreting consumer wearable data.

## References

- [AASM diagnostic testing guideline](https://aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf)
- [AASM respiratory-event scoring criteria](https://isr.aasm.org/helpv6/ScoringRespiratoryEventsR.html)
