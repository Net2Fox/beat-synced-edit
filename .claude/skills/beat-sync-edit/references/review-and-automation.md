# Review and automation

Read this when you check an export (what `preview` and `render` already verify and
write, `verify`, intentional black or silence), record a review with `review-export`,
render several projects with `batch-render`, script the CLI with `--json`, `--dry-run`
and `execute-plan`, or look up commands and flags.

Contents: [Export QA](#export-qa) · [Review an export](#review-an-export) ·
[Record a review](#record-a-review) · [Batch renders](#batch-renders) ·
[Machine output and dry runs](#machine-output-and-dry-runs) · [CLI discovery](#cli-discovery)

## Export QA

`preview` and `render` run export QA on the encoded MP4 themselves and exit with code 4
when a technical check fails, leaving the MP4 and its reports on disk; never deliver
that file. Reports are named after the output and written beside it (`<outputs>` for a
render, `<work>` for a preview):

| File | Contents |
|---|---|
| `final.verification.json` | the printed result: measured `duration`, `frames`, `width`, `height`, `fps`; `qa` (`technical_pass`, `report`, `contact_sheets`, `review_notes`); `tracking[]`; `fonts[]`; `audio_loudness`; `provenance`. A preview adds `review_page`, the HTML page for the user ([project-workflow.md](project-workflow.md)) |
| `final.qa.json` (`qa.report`) | `technical_pass`, `checks[]` (`name`, `status`, `observed`, `expected`), `black_intervals` and `silent_intervals` (`start`, `end`, `intentional`), `review_notes`, `audio_measurements` (`integrated_lufs`, `true_peak_dbtp`, `lra_lu`), `contact_sheets`, `visual_review`, `editorial_review`, `playback_review`, the MP4's `sha256` |
| `final.review-NN.png` (`qa.contact_sheets`) | decoded output frames, 24 per page |
| `final.audio.json` | mix and loudness report ([audio-workflow.md](audio-workflow.md)) |

`technical_pass` needs H.264 yuv420p video, a full decode and 48 kHz audio within
0.08 s of the video's duration; with a project, also its dimensions, frame count, fps
and duration (a preview at its reduced size) and, with loudness normalization on,
integrated loudness and true peak ([audio-workflow.md](audio-workflow.md)). Black (at
least 0.08 s) and silent (below -45 dB for at least 0.25 s) intervals never fail QA:
unexplained ones add one `review_notes` line per kind, as do a true peak at or above
0 dBTP and unmeasurable loudness. An interval is a prompt to look, not proof of an error.

## Review an export

1. Open every PNG in `qa.contact_sheets`. Tiles, labelled in output seconds, show the
   first, middle and last frame, the frames before, at and after every cut, and the
   middle frame of every title, caption and graphic; a yellow outline marks the style's
   `safe_area`. Extract a full-size frame with `ffmpeg` where a thumbnail is not enough.
2. Read `qa.review_notes` and, in `qa.report`, the intervals and `audio_measurements`;
   mark intended intervals (a fade from black, a silent intro) with `qa_policy` (below).
   The agent cannot hear: these, `final.audio.json`, the beat map and the transcript
   are its audio evidence; report playback as not reviewed unless the user played it.
3. Check `tracking[]` entries with `review_required: true`; `low_confidence_intervals`
   are source seconds ([project-workflow.md](project-workflow.md)).

`qa_policy` is a `revise` operation ([project-workflow.md](project-workflow.md)) that
the next `preview`, `render` or `verify --project` applies. Ranges are `[start, end]`
output seconds within the duration; a detected interval inside one (±0.06 s) is
`intentional`. The operation replaces the whole policy, so repeat ranges you keep.

```json
[{"op": "qa_policy", "values": {"intentional_black": [[0, 0.4]], "intentional_silence": [[0, 0.6]]}}]
```

Run `verify` only on a file changed after render ([finishing-tools.md](finishing-tools.md)):

```sh
edit_project.py verify <outputs>/final-look.mp4 --project <work>/project.json --work <work>/qa
```

It runs the same checks, writes `<name>.qa.json` and contact sheets to `--work`
(default: beside the video) and exits with code 4 on a failed check. `--project` adds the
project checks, cut and cue sampling, safe area, loudness targets and `qa_policy`; omit
it when the file differs from the project in size, frame count or frame rate (the
sheets then sample seven evenly spaced times instead of cuts).

## Record a review

`technical_pass` covers technical checks only. `visual_review`, `editorial_review` and
`playback_review` stay `not_reviewed` until `review-export` records observations from a
review that really happened (the report-only-what-you-observed rule in SKILL.md).

```sh
edit_project.py review-export <outputs>/final.qa.json --observations <work>/review.json
```

```json
{"reviewer": "agent", "visual": {"status": "pass", "evidence": "Inspected 0.0, 1.2 and 2.0 s: both caption lines and the face fit inside the safe area."}}
```

Pass a `.qa.json` from preview, render or verify, not `.verification.json`. `reviewer`
is required; include only reviewed categories (`visual`, `editorial`, `playback`), each
with `status` `pass`, `fail` or `not_reviewed` and non-empty `evidence` for `pass` or
`fail`; other keys are rejected. The command refuses if the MP4 changed since that
report (run `verify` first), updates the report in place (or writes `-o`) and appends
to `review_history`. It cannot prove anyone watched.

## Batch renders

Render saved projects with a shared shot cache (one `analyze` library can feed several
plans: [analysis cache](music-editorial.md#analysis-cache)):

```sh
edit_project.py batch-render <work>/jobs.json --work <work>/batch
```

```json
{"jobs": [{"project": "short.json", "output": "short.mp4"}, {"project": "long.json", "output": "long.mp4", "preview": true}]}
```

A job accepts only `project`, `output` (a distinct `.mp4`) and `preview` (default
`false`; preview size, no HTML page); relative paths resolve beside the manifest. All
projects and outputs are checked before the first render. Shots are cached in
`<work>/batch/cache`; each job runs export QA with reports beside its output;
`<work>/batch/batch-report.json` (each job's `ok` and `result` or `error`) is rewritten
after every job. The batch stops at the first failed job unless `--continue-on-error`;
any failure gives `all_succeeded: false` and exit code 4.

## Machine output and dry runs

Every command accepts `--json`, `--json-brief`, `--dry-run` and `--plan <file>`.
Without `--json`, stdout is the bare result JSON and an error is one `Error: <message>`
line on stderr. `--json` (indented) or `--json-brief` (one line), before or after the
command, wraps stdout in a `beat-sync.cli.v1` envelope:
`{"schema", "ok": true, "command", "result", "provenance"}` or
`{"schema", "ok": false, "command", "error": {"code", "message"}}`. Progress always goes
to stderr. Exit codes: 0 success; 2 `invalid_argument` (bad arguments, values or JSON);
3 `input_io` (missing or unreadable file); 4 `execution_failed` (FFmpeg or render
failure, failed technical QA, failed batch job).

```sh
edit_project.py render <work>/project.json -o <outputs>/final.mp4 --dry-run --plan <work>/render-plan.json --json
edit_project.py execute-plan <work>/render-plan.json --json
```

- `--dry-run` checks syntax, overwrite guards, input existence and saved-project
  validity and hashes every input (argument files, files referenced in input JSON,
  every file in an input folder). It decodes nothing, so it cannot predict codec, model
  or visual problems, and writes nothing unless `--plan` names a file. `--plan` needs
  `--dry-run`; `contract` and `execute-plan` have no dry run.
- The plan stores the arguments, working directory, a signature of the CLI scripts and
  Python, and the input hashes; `execute-plan` rechecks them and runs that one command
  from the saved directory without a shell. Any change fails (prepare a new plan). A
  plan protects reproducibility; it is not an approval.
- Keep outputs, reports, caches and plans out of input folders: the CLI refuses an
  output that would overwrite an input and a plan saved inside an input folder, and a
  new file in an input folder invalidates a plan.

## CLI discovery

`edit_project.py --help` lists the commands, `edit_project.py CMD --help` a command's
flags, required arguments and choices (most defaults and many meanings are only in the
references), and `edit_project.py presets` the plan presets' settings.
`edit_project.py contract` prints a machine-readable schema of every command (about
120 KB, no defaults): use it only when a program needs that schema, never to look up flags.
