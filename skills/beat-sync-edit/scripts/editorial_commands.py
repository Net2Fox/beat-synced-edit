"""Music-map corrections, explainable candidate ranking and selection feedback."""
from pathlib import Path

from editorial_feedback import rank_candidates, record_feedback
from music_structure import apply_overrides
from project_workspace import read_json, write_json


EDITORIAL_COMMANDS = {"music-override", "candidates", "feedback"}


def register_editorial_commands(sub):
    p = sub.add_parser("music-override", help="Correct measured music map with an auditable JSON override")
    p.add_argument("beatmap")
    p.add_argument("--overrides", required=True)
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("candidates", help="Rank clips with source evidence and explicit preferences")
    p.add_argument("library")
    p.add_argument("--preferences")
    p.add_argument("--query", default="")
    p.add_argument("-o", "--output")
    p = sub.add_parser("feedback", help="Append accept/reject/clear review decision; affects future plans")
    p.add_argument("library")
    p.add_argument("--profile", required=True)
    p.add_argument("--clip", required=True)
    p.add_argument("--decision", choices=("accept", "reject", "clear"), required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--reviewer", default="user")


def run_editorial_command(args):
    if args.command == "music-override":
        result = apply_overrides(read_json(args.beatmap), read_json(args.overrides))
    elif args.command == "candidates":
        result = {"candidates": rank_candidates(read_json(args.library), read_json(args.preferences) if args.preferences else {}, args.query)}
    elif args.command == "feedback":
        library = read_json(args.library)
        clip = next((c for c in library.get("clips", []) if str(c["id"]) == args.clip), None)
        if clip is None:
            raise ValueError(f"Unknown clip: {args.clip}")
        profile = read_json(args.profile) if Path(args.profile).is_file() else {}
        result = record_feedback(profile, clip, args.decision, args.reason, args.reviewer, str(Path(args.library).resolve()))
        write_json(args.profile, result)
        return {"profile": str(Path(args.profile).resolve()), "event": result["events"][-1]}
    else:
        raise ValueError(f"Unknown editorial command: {args.command}")
    if getattr(args, "output", None):
        write_json(args.output, result)
    return result
