"""Build or verify the self-contained Codex skill from the root CLI sources."""

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "beat-sync-edit"
SCRIPTS = (
    "beat_map.py", "clip_tag.py", "plan_edit.py", "render_edit.py",
    "vertical_style.py", "flash_montage.py", "overunder_stack.py",
    "edit_project.py", "project_workspace.py", "project_plan.py", "edit_presets.py",
    "media_library.py", "smart_reframe.py", "project_render.py",
    "text_overlay.py", "text_project.py", "text_commands.py", "subtitle_tools.py", "speech_transcribe.py",
)
RESOURCES = ("LICENSE", "requirements.txt", "requirements.lock.txt", "requirements-transcription.txt", "UPSTREAM.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the published skill differs from root sources")
    args = parser.parse_args()
    pairs = [(ROOT / name, SKILL / "scripts" / name) for name in SCRIPTS]
    pairs.extend((ROOT / name, SKILL / name) for name in RESOURCES)
    stale = []
    for source, target in pairs:
        if args.check:
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                stale.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    if stale:
        raise SystemExit("Rebuild the Codex skill with python tools/build_codex_skill.py:\n" + "\n".join(stale))
    print("Codex bundle is up to date." if args.check else "Built skills/beat-sync-edit (no environment or media files).")


if __name__ == "__main__":
    main()
