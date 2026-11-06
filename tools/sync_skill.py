"""Keep the Claude Code copy of the skill identical to the canonical package.

skills/beat-sync-edit is the only source: SKILL.md, references/, scripts/ and
the requirements files are edited there. This tool copies every file of that
package (except local environments, caches and hidden or backup files), plus
the repository LICENSE, into .claude/skills/beat-sync-edit, and LICENSE into
the canonical package. With --check it changes nothing and fails when any
copied file differs, is missing, or has no canonical source.
"""

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "beat-sync-edit"
CLAUDE = ROOT / ".claude" / "skills" / "beat-sync-edit"
# Never copied, compared or removed: environments and caches may live in
# either copy (README setup creates .venv inside an installed skill).
LOCAL_ONLY = {".venv", "venv", "__pycache__", "work", "outputs"}


def ignored(relative):
    """Local or junk entries: environments, caches, hidden and backup files."""
    return any(part in LOCAL_ONLY or part.startswith(".") for part in relative.parts) \
        or relative.name.endswith(("~", ".pyc", ".pyo"))


def files(root):
    """Every tracked-content file below root, relative to it."""
    if not root.is_dir():
        return set()
    return {path.relative_to(root) for path in root.rglob("*")
            if path.is_file() and not ignored(path.relative_to(root))}


def payload():
    """Map every target file to its source file."""
    pairs = {SKILL / "LICENSE": ROOT / "LICENSE", CLAUDE / "LICENSE": ROOT / "LICENSE"}
    for relative in files(SKILL):
        if relative != Path("LICENSE"):
            pairs[CLAUDE / relative] = SKILL / relative
    return pairs


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        # Replace the link itself; never write through it to another location.
        target.unlink()
    shutil.copyfile(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on drift instead of copying")
    args = parser.parse_args()
    for required in (SKILL / "SKILL.md", SKILL / "scripts" / "edit_project.py", ROOT / "LICENSE"):
        if not required.is_file():
            raise SystemExit(f"Missing canonical file: {required.relative_to(ROOT).as_posix()}")
    pairs = payload()
    stale = sorted(CLAUDE / relative for relative in files(CLAUDE) if CLAUDE / relative not in pairs)
    problems = []
    for path in stale:
        if args.check:
            problems.append(path.relative_to(ROOT).as_posix() + " (no canonical source)")
        else:
            if not path.resolve().is_relative_to(CLAUDE.resolve()):
                raise ValueError(f"Refusing to remove a file outside the Claude copy: {path}")
            path.unlink()
    for target, source in sorted(pairs.items()):
        if args.check:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != source.read_bytes():
                problems.append(target.relative_to(ROOT).as_posix())
        else:
            copy(source, target)
    if not args.check:
        for directory in sorted({path.parent for path in stale}, key=lambda p: len(p.parts), reverse=True):
            if directory != CLAUDE and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    if problems:
        raise SystemExit("Out of sync; run python tools/sync_skill.py:\n" + "\n".join(problems))
    count = len(list((SKILL / "scripts").glob("*.py")))
    print(f"Claude Code copy is up to date ({count} runtime modules)." if args.check
          else f"Synchronized the Claude Code copy ({count} runtime modules).")


if __name__ == "__main__":
    main()
