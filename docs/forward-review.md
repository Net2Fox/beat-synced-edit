# Independent installed-bundle forward review

Date: 2026-10-03. Reviewer: independent `package_reviewer` agent. Result: the
requested speech-led fixture workflow completed successfully with the copied
Codex bundle, and the copied Claude Code bundle CLI started successfully.

This review began by reading `skills/beat-sync-edit/SKILL.md`, then its speech,
text/subtitles, project and workflow-extension references. It did not inspect
implementation code to discover how to perform the edit. Command usage came
from those references and the public CLI help.

## Isolation and scope

Both current packaged skill directories were copied to
`work/forward-review/codex-bundle` and `work/forward-review/claude-bundle` after
the parent agent reported its final package rebuild. Each contained 36 Python
modules. Every editing command ran from `work/forward-review/case`, outside the
repository root, and invoked the copied bundle's `scripts/edit_project.py`.
Media, output, reports and caches lived under that case directory. No root
implementation code was imported by the independent evidence checker or changed
by this review.

The existing Python 3.12.10 environment was used; dependency installation into
a new venv was not tested. `python.exe` resolved to
`C:\Users\Net2Fox\AppData\Local\Programs\Python\Python312\python.exe`,
FFmpeg to `c:\windows\ffmpeg.exe`, and ffprobe to
`G:\Scoop\shims\ffprobe.exe`. No downloads or ASR run were needed in this review.

Inputs were the supplied generated spoken recording and its supplied actual
Whisper transcript, copied from `work/speech-evidence`. The transcript contains
one sentence ending at 5.46 s, including one recognizer token `test, keep`.
That token was retained as supplied; no artificial word alignment was invented.
The original video picture is an intentionally flat blue generated fixture.
The B-roll is a locally generated orange/cream geometric PNG, not external
footage. This verifies workflow mechanics, not real-interview editing quality.

## Commands executed

Preparation was performed from the parent workspace. The absolute repository
path below is the one used in this run:

```powershell
$reviewRepo = 'C:\Users\Net2Fox\Documents\Codex\2026-10-03\codex-claude-code-https-github-com\work\net2fox-beat-synced-edit'
$reviewRoot = Join-Path $reviewRepo 'work\forward-review'
New-Item -ItemType Directory -Path $reviewRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $reviewRepo 'skills\beat-sync-edit') -Destination (Join-Path $reviewRoot 'codex-bundle') -Recurse
Copy-Item -LiteralPath (Join-Path $reviewRepo '.claude\skills\beat-sync-edit') -Destination (Join-Path $reviewRoot 'claude-bundle') -Recurse
New-Item -ItemType Directory -Path (Join-Path $reviewRoot 'case\work'),(Join-Path $reviewRoot 'case\outputs'),(Join-Path $reviewRoot 'case\input') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $reviewRepo 'work\speech-evidence\spoken.mp4'),(Join-Path $reviewRepo 'work\speech-evidence\asr.json') -Destination (Join-Path $reviewRoot 'case\input')
Get-Command python,ffmpeg,ffprobe | Select-Object Name,Source
```

The execution tool's working directory was then set to
`$reviewRoot\case` for every following command. CLI discovery commands all
exited zero:

```powershell
python -X utf8 '..\codex-bundle\scripts\edit_project.py' speech-plan --help
python -X utf8 '..\codex-bundle\scripts\edit_project.py' speech-analyze --help
python -X utf8 '..\codex-bundle\scripts\edit_project.py' speech-broll --help
python -X utf8 '..\codex-bundle\scripts\edit_project.py' preview --help
python -X utf8 '..\claude-bundle\scripts\edit_project.py' --help
```

The variables below were reset at the beginning of each editing shell call.
Nonzero exit codes after analysis, planning, B-roll, text styling, preview,
render, verification and review registration were checked and would have stopped
the workflow. All those editing commands exited zero.

```powershell
$env:NUMBA_CACHE_DIR = Join-Path (Get-Location) 'work\numba-cache'
$editScript = (Resolve-Path '..\codex-bundle\scripts\edit_project.py').Path
$caseRoot = (Get-Location).Path
python -X utf8 $editScript speech-analyze (Join-Path $caseRoot 'input\spoken.mp4') --transcript (Join-Path $caseRoot 'input\asr.json') -o (Join-Path $caseRoot 'work\analysis.json') > (Join-Path $caseRoot 'work\speech-analyze.stdout.json')
python -X utf8 $editScript speech-plan (Join-Path $caseRoot 'input\spoken.mp4') --transcript (Join-Path $caseRoot 'work\analysis.json') -o (Join-Path $caseRoot 'work\project.json') --width 180 --height 320 --fps 30 --padding 0 > (Join-Path $caseRoot 'work\speech-plan.stdout.json')
ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=0x184E65:s=180x320:d=1' -vf 'drawbox=x=25:y=45:w=130:h=115:color=0xF4A340:t=fill,drawbox=x=55:y=75:w=70:h=55:color=0xF8F5ED:t=fill,drawbox=x=35:y=182:w=110:h=8:color=0xF8F5ED:t=fill' -frames:v 1 -update 1 (Join-Path $caseRoot 'input\broll.png')
ffmpeg -hide_banner -loglevel error -ss 1.5 -i (Join-Path $caseRoot 'input\spoken.mp4') -frames:v 1 -update 1 (Join-Path $caseRoot 'work\source-1.5.png')
python -X utf8 $editScript speech-broll (Join-Path $caseRoot 'work\project.json') --shot 'speech-phrase-0a24d32725d2' --media (Join-Path $caseRoot 'input\broll.png') --offset 1.5 --duration 2 --reframe contain > (Join-Path $caseRoot 'work\speech-broll.stdout.json')
python -X utf8 $editScript text-style (Join-Path $caseRoot 'work\project.json') --track subtitles --preset boxed --font-size 16 --stroke-width 1 --max-lines 3 --margin 0.1 > (Join-Path $caseRoot 'work\text-style.stdout.json')
python -X utf8 $editScript subtitles-export (Join-Path $caseRoot 'work\project.json') -o (Join-Path $caseRoot 'outputs\captions.srt')
python -X utf8 $editScript preview (Join-Path $caseRoot 'work\project.json') -o (Join-Path $caseRoot 'work\preview.mp4') --cache (Join-Path $caseRoot 'work\preview-cache') > (Join-Path $caseRoot 'work\preview.stdout.json')
python -X utf8 $editScript render (Join-Path $caseRoot 'work\project.json') -o (Join-Path $caseRoot 'outputs\final.mp4') --cache (Join-Path $caseRoot 'work\final-cache') > (Join-Path $caseRoot 'work\render.stdout.json')
python -X utf8 $editScript verify (Join-Path $caseRoot 'outputs\final.mp4') --project (Join-Path $caseRoot 'work\project.json') --work (Join-Path $caseRoot 'work\verify') > (Join-Path $caseRoot 'work\verify.stdout.json')
python -X utf8 '.\work\check_evidence.py'
python -X utf8 $editScript review-export (Join-Path $caseRoot 'outputs\final.qa.json') --observations (Join-Path $caseRoot 'work\visual-observations.json') > (Join-Path $caseRoot 'work\visual-review.stdout.json')
python -X utf8 $editScript review-export (Join-Path $caseRoot 'work\verify\final.qa.json') --observations (Join-Path $caseRoot 'work\visual-observations.json') > (Join-Path $caseRoot 'work\verify-review.stdout.json')
python -X utf8 '..\claude-bundle\scripts\edit_project.py' --help > (Join-Path $caseRoot 'work\claude-help.txt')
ffprobe -v error -show_entries stream=codec_name,codec_type,width,height,r_frame_rate,nb_frames,sample_rate,duration -of json '.\outputs\final.mp4'
```

`check_evidence.py` is an independent local measurement script saved beside its
`objective-evidence.json` output. It imports stdlib and NumPy only, decodes source
and output audio through FFmpeg to mono 48 kHz float PCM, compares zero-lag
correlations and gain-adjusted SNR, and compares final source-caption words
against the project's recoverable revision-zero history. It asserts unchanged
word IDs/text/frame ranges, source-bound captions, insertion frames `[45, 105]`,
and correlation above 0.95 in each measured window.

## Observed evidence

| Check | Observation |
|---|---|
| Final video | 164 decoded frames; 5.466667 s; 180×320; 30 fps |
| Encoding | H.264; yuv420p; audible stream present; AAC at 48 kHz |
| Encoded audio duration | 5.466 s |
| Automatic export verification | `technical_pass: true`; full decode returned 0 with no errors |
| Detected intervals | No black intervals or silent intervals in the final export |
| Measured loudness | −16.02 LUFS; −5.13 dBTP |
| Timeline after B-roll | 45 source frames, 60 still frames, 59 source frames |
| B-roll audio mapping | Original `spoken.mp4` source interval 1.5–3.5 s, at 1× |
| Captions | Three source-bound cues; all 15 word IDs, text and frame ranges identical to the pre-insert revision |
| Claude Code bundle | `--help` completed with exit 0 and listed speech/render/verify commands |

Objective source/final audio agreement, after decoding both files:

| Output interval | Zero-lag correlation | Gain-adjusted SNR |
|---|---:|---:|
| 0–1.5 s | 0.999795 | 33.86 dB |
| 1.5–3.5 s, during B-roll | 0.999910 | 37.43 dB |
| 3.5–5.466667 s | 0.999913 | 37.62 dB |
| 1.45–1.55 s, first cut | 0.999977 | 43.45 dB |
| 3.45–3.55 s, second cut | 0.999997 | 52.24 dB |

The best-fit audio gain was approximately 1.206–1.210. Consequently, this is
evidence that source speech and timing survive picture replacement, not a claim
that encoded output samples are bit-identical to the source. It is also not a
subjective listening test.

The reviewer viewed actual pixels from `work/source-1.5.png`, `input/broll.png`,
`work/preview.review-01.png`, `outputs/final.review-01.png` and
`work/verify/final.review-01.png`. Every returned preview/final/verification
contact sheet was inspected. Each sheet contained these 13 timestamps:
0, 0.033333, 1.233333, 1.466667, 1.5, 1.533333, 2.733334, 3.466667,
3.5, 3.533333, 3.55, 5.033333 and 5.433334 s.

The original blue picture is present before 1.5 s and after 3.5 s. The orange and
cream graphic is visible during the insert. Captions remain visible across both
picture cuts and stay within the frame at the sampled times. The first caption
is two lines, the second is three lines, and the final caption is one line.
The observations were saved in `work/visual-observations.json` and registered
against both final QA reports through `review-export`.

Final recorded review states: `technical_pass: true`, `visual_review: pass`,
`editorial_review: not_reviewed`, `playback_review: not_reviewed`. Recognition
accuracy was not reviewed. Automatic tracking reports low confidence for the
flat generated source, appropriately providing no subject-identity evidence.

## Documentation traps and limitations

- No blocking documentation problem or functional code failure occurred.
- The speech reference uses the shorthand `python edit_project.py`, while the
  installed entry point is `scripts/edit_project.py`. Reading the top-level skill
  first resolves this, as required. Copying only a speech-reference command from
  an arbitrary working directory would fail to locate the script. The run used
  an absolute resolved script path after discovery.
- Font sizes in the text reference are output pixels. Its 1080-wide example
  value of 58 would be too large for this 180-wide fixture; a 16-pixel caption
  style was deliberately selected using the documented semantics.
- In the tested snapshot, `review-export` recorded `visual_review: pass` and the
  supplied evidence, but left each contact sheet's `pixels_inspected_by_agent`
  field `false`. This metadata ambiguity was reported to the parent agent. The
  parent subsequently resolved it by renaming the generation-time field to
  `pixels_inspected_at_generation`, which makes its scope explicit. The retained
  snapshot evidence still contains the old field; this label-only fix did not
  require another media render.
- The parent also reported changing the canonical skill's first workflow step
  to distinguish transcript analysis for speech from music analysis and motion
  compositions without a soundtrack. The speech-specific reference already
  provided the correct path used in this review.
- The Claude check establishes startup and self-contained command discovery,
  not a second end-to-end render under a Claude agent. The Codex copied bundle
  performed the full edit and render.
- No real-person tracking, music sync, free-form editorial judgement, new
  transcription, subjective audio listening or general real-world quality was
  established by this small generated case. The saved states retain these limits.

## Artifact identity

Local evidence is retained under `work/forward-review/case`. These work files
are intentionally ignored by Git; this report records the performed run.

| File | SHA-256 |
|---|---|
| `input/spoken.mp4` | `8d88c2457fd1d56426c7a94f485bccefa5849f444177392b8cdc877d7bd4e426` |
| `input/asr.json` | `9e9a5ff7b8b30e836f8e77069f6479a82d30bc1a20685362d022a09c6e0ff39c` |
| `input/broll.png` | `3863edc08996b3f309d805e97342aa92174625ea408ade91dd8423a7703e9fd2` |
| `outputs/final.mp4` | `c092fbf174a1e4ab6aada8d163a5d3df4d4871dff2f6bd77d00b0ea4eade066d` |

The rendered tool provenance identifies Python 3.12.10 and tool source SHA-256
`cb573eda7fcec7e66b8b2ffd8c0c28c013e0866853ce8f6d14814be5748f6951`.
