"""Keep the Claude Code copy of the skill identical to the canonical package.

skills/beat-sync-edit is the only source: SKILL.md, references/, scripts/ and
the requirements files are edited there. This tool copies them, plus the
repository LICENSE, into .claude/skills/beat-sync-edit (and LICENSE into the
canonical package). With --check it changes nothing and fails on any drift.
"""

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "beat-sync-edit"
CLAUDE = ROOT / ".claude" / "skills" / "beat-sync-edit"
# Generated payload: only these are managed. Environments (.venv), caches,
# user media and unrecognised files in a bundle are never touched.
MANAGED_FILES = ("SKILL.md", "requirements.txt", "requirements.lock.txt", "requirements-transcription.txt")
MANAGED_DIRS = ("references", "scripts", "assets", "agents")


def payload():
    """Map every managed target file to its source file."""
    pairs = {SKILL / "LICENSE": ROOT / "LICENSE", CLAUDE / "LICENSE": ROOT / "LICENSE"}
    for name in MANAGED_FILES:
        pairs[CLAUDE / name] = SKILL / name
    for directory in MANAGED_DIRS:
        for source in sorted((SKILL / directory).rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                pairs[CLAUDE / source.relative_to(SKILL)] = source
    return pairs


def stale_files(expected):
    """Managed-directory files in the mirror that have no canonical source."""
    extra = []
    for directory in MANAGED_DIRS:
        for path in (CLAUDE / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path not in expected:
                extra.append(path)
    return extra


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on drift instead of copying")
    args = parser.parse_args()
    for required in (SKILL / "SKILL.md", SKILL / "scripts" / "edit_project.py", ROOT / "LICENSE"):
        if not required.is_file():
            raise SystemExit(f"Missing canonical file: {required.relative_to(ROOT).as_posix()}")
    pairs = payload()
    extra = stale_files(set(pairs))
    problems = []
    for path in extra:
        if args.check:
            problems.append(path.relative_to(ROOT).as_posix() + " (no canonical source)")
        else:
            if not path.resolve().is_relative_to(CLAUDE.resolve()):
                raise ValueError(f"Refusing to remove a file outside the Claude copy: {path}")
            path.unlink()
    for target, source in pairs.items():
        if args.check:
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                problems.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    if problems:
        raise SystemExit("Out of sync; run python tools/sync_skill.py:\n" + "\n".join(problems))
    count = len(list((SKILL / "scripts").glob("*.py")))
    print(f"Claude Code copy is up to date ({count} runtime modules)." if args.check
          else f"Synchronized the Claude Code copy ({count} runtime modules).")


if __name__ == "__main__":
    main()
