"""Build/check identical, self-contained Codex and Claude Code skill bundles."""

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "beat-sync-edit"
CLAUDE = ROOT / ".claude" / "skills" / "beat-sync-edit"
# Runtime modules live at root; tests, development helpers and fixtures belong in
# tests/, tools/ and work/. Discovery prevents newly imported runtime helpers from
# being accidentally omitted from an otherwise apparently healthy package.
SCRIPTS = tuple(sorted(path.name for path in ROOT.glob("*.py")))
RESOURCES = ("LICENSE", "requirements.txt", "requirements.lock.txt", "requirements-transcription.txt", "UPSTREAM.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on root/Codex/Claude script or instruction drift")
    args = parser.parse_args()
    pairs = [(ROOT / name, bundle / "scripts" / name) for bundle in (SKILL, CLAUDE) for name in SCRIPTS]
    pairs.extend((ROOT / name, bundle / name) for bundle in (SKILL, CLAUDE) for name in RESOURCES)
    canonical = [SKILL / "SKILL.md"]
    for directory in ("references", "assets", "agents"):
        canonical.extend(path for path in (SKILL / directory).rglob("*") if path.is_file())
    pairs.extend((source, CLAUDE / source.relative_to(SKILL)) for source in canonical)
    stale = []
    expected = {target.resolve() for _, target in pairs}
    # Only generated payload folders are managed. Never remove environments,
    # user media, caches or unrecognized files from the bundle root.
    extra = []
    for bundle in (SKILL, CLAUDE):
        for path in (bundle / "scripts").glob("*.py"):
            if path.resolve() not in expected:
                extra.append(path)
    for directory in ("references", "assets", "agents"):
        for path in (CLAUDE / directory).rglob("*"):
            if path.is_file() and path.resolve() not in expected:
                extra.append(path)
    for path in extra:
        if args.check:
            stale.append(path.relative_to(ROOT).as_posix() + " (unexpected generated file)")
        else:
            # Resolved boundary check protects the generated checkout even if a
            # directory was replaced with a symlink. This is a single-file delete.
            if not path.resolve().is_relative_to(ROOT):
                raise ValueError(f"Refusing to remove payload outside repository: {path}")
            path.unlink()
    for source, target in pairs:
        if args.check:
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                stale.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    if stale:
        raise SystemExit("Rebuild both skills with python tools/build_codex_skill.py:\n" + "\n".join(stale))
    print(f"Codex and Claude bundles are up to date ({len(SCRIPTS)} runtime modules)." if args.check
          else f"Built identical Codex/Claude payloads ({len(SCRIPTS)} runtime modules; no environment or media files).")


if __name__ == "__main__":
    main()
