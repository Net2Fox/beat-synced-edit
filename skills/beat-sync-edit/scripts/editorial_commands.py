"""Public music correction, candidate review, preference training and evaluation."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from editorial_feedback import (calibrate, evaluate_selection, rank_candidates,
                                record_feedback)
from music_structure import apply_overrides
from project_workspace import read_json, write_json


EDITORIAL_COMMANDS = {"music-override", "candidates", "feedback", "calibrate", "evaluate-selection",
                      "review-manifest", "record-case-review", "evaluate-manifest"}

SCENARIOS = {
    "musical-edit": ["musical_accents", "chosen_actions", "crop_identity", "audio_balance"],
    "multiple-people": ["crop_identity", "occlusion_recovery", "chosen_actions"],
    "fast-motion": ["crop_identity", "action_timing", "speed_quality"],
    "quiet-speech": ["word_accuracy", "speech_audibility", "caption_timing"],
    "names-and-languages": ["word_accuracy", "proper_names", "glyph_rendering"],
    "variable-frame-rate": ["source_sync", "caption_timing", "frame_continuity"],
    "ambiguous-rhythm": ["musical_accents", "phrase_pacing", "intentional_silence"],
}


def register_editorial_commands(sub):
    p = sub.add_parser("music-override", help="Correct measured music map with an auditable JSON override")
    p.add_argument("beatmap")
    p.add_argument("--overrides", required=True)
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("candidates", help="Rank clips with source evidence and explicit preferences")
    p.add_argument("library")
    p.add_argument("--preferences")
    p.add_argument("--query", default="")
    p.add_argument("--model")
    p.add_argument("-o", "--output")
    p = sub.add_parser("feedback", help="Append accept/reject/clear review decision; affects future plans")
    p.add_argument("library")
    p.add_argument("--profile", required=True)
    p.add_argument("--clip", required=True)
    p.add_argument("--decision", choices=("accept", "reject", "clear"), required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--reviewer", default="user")
    p = sub.add_parser("calibrate", help="Fit personal preference model; evaluate on disjoint source groups")
    p.add_argument("profile")
    p.add_argument("--holdout", type=float, default=.25)
    p.add_argument("--seed", default="beat-sync")
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("evaluate-selection", help="Report missed/false selections against reviewed moments")
    p.add_argument("project")
    p.add_argument("--labels", required=True)
    p.add_argument("--minimum-overlap", type=float, default=.5)
    p.add_argument("-o", "--output")
    p = sub.add_parser("review-manifest", help="Create reusable input-bound real/synthetic evaluation cases")
    p.add_argument("projects", nargs="+")
    p.add_argument("--kind", choices=("real", "synthetic"), default="real")
    p.add_argument("--scenario", choices=tuple(SCENARIOS), default="musical-edit")
    p.add_argument("--render", action="append", help="Exported video corresponding to each project, repeat in project order")
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("record-case-review", help="Record actual reviewer observations; never inferred from metadata")
    p.add_argument("manifest")
    p.add_argument("--case", required=True)
    p.add_argument("--observations", required=True, help="JSON check->pass/fail/not_reviewed")
    p.add_argument("--reviewer", required=True)
    p.add_argument("--notes", required=True)
    p.add_argument("--labels", help="Optional JSON reviewed source moments")
    p = sub.add_parser("evaluate-manifest", help="Check a review dataset; missing materials/reviews remain unverified")
    p.add_argument("manifest")
    p.add_argument("-o", "--output")


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model(path):
    value = read_json(path) if path else None
    return value.get("model", value) if value else None


def create_manifest(projects, kind="real", scenario="musical-edit", renders=None):
    if kind not in ("real", "synthetic") or scenario not in SCENARIOS:
        raise ValueError("Invalid evaluation kind or scenario")
    cases = []
    if renders is not None and len(renders) != len(projects):
        raise ValueError("Provide one --render for each project, in the same order")
    for index, path in enumerate(projects):
        path = Path(path).resolve()
        plan = read_json(path)
        from render_qa import referenced_files
        sources = sorted(str(source) for source in referenced_files(plan))
        render = str(Path(renders[index]).resolve()) if renders else None
        cases.append({"id": f"case-{index+1:03d}", "project": str(path), "project_sha256": _hash(path),
                      "render": render, "render_sha256": _hash(render) if render and Path(render).is_file() else None,
                      "kind": kind, "scenario": scenario, "required_checks": SCENARIOS[scenario],
                      "sources": [{"path": s, "sha256": _hash(s) if Path(s).is_file() else None} for s in sources],
                      "labels": None, "review": None})
    return {"version": 1, "cases": cases, "review_history": [],
            "policy": "Synthetic mechanics do not establish real-media editorial, identity or recognition quality."}


def evaluate_manifest(manifest):
    if manifest.get("version") != 1 or not isinstance(manifest.get("cases"), list):
        raise ValueError("Expected a version 1 review manifest with cases")
    results = []
    for case in manifest["cases"]:
        result = {"id": case["id"], "kind": case["kind"], "scenario": case["scenario"], "status": "not_reviewed", "issues": []}
        project = Path(case["project"])
        missing = [entry["path"] for entry in case.get("sources", []) if not Path(entry["path"]).is_file()]
        if not project.is_file() or missing:
            result.update(status="missing_materials", issues=["Missing project or source material", *missing])
            results.append(result)
            continue
        changed = _hash(project) != case["project_sha256"]
        changed_sources = [entry["path"] for entry in case.get("sources", []) if not entry.get("sha256") or _hash(entry["path"]) != entry["sha256"]]
        if changed or changed_sources:
            result.update(status="stale", issues=["Inputs changed or were unavailable at manifest creation; recreate and review", *changed_sources])
            results.append(result)
            continue
        plan = read_json(project)
        render = case.get("render")
        if not render:
            result["issues"].append("No exported video bound to this case; supply --render before final review")
        elif not Path(render).is_file():
            result.update(status="missing_materials", issues=["Exported video is missing", render])
            results.append(result)
            continue
        elif not case.get("render_sha256") or _hash(render) != case["render_sha256"]:
            result.update(status="stale", issues=["Export changed or was missing when manifest was created"])
            results.append(result)
            continue
        labels = case.get("labels")
        if labels and Path(labels).is_file():
            if case.get("labels_sha256") and _hash(labels) != case["labels_sha256"]:
                result.update(status="stale", issues=["Reviewed selection labels changed"])
                results.append(result)
                continue
            result["selection"] = evaluate_selection(plan, read_json(labels))
        elif labels:
            result["issues"].append("Selection label file is missing")
        fps = plan["output"]["fps"]
        beats = plan.get("beat_frames", [])
        cuts = [shot["timeline_start_frame"] for shot in plan.get("edits", [])[1:]]
        errors = [min(abs(cut-beat) for beat in beats)/fps for cut in cuts] if beats else []
        result["measured_beat_distance"] = {"n": len(errors), "mean_seconds": sum(errors)/len(errors) if errors else None,
                                           "max_seconds": max(errors) if errors else None,
                                           "scope": "Distance to supplied beat map; does not verify that map by listening"}
        review = case.get("review")
        if review:
            checks = review.get("observations", {})
            result["review"] = review
            if any(checks.get(key) == "fail" for key in case["required_checks"]):
                result["status"] = "failed"
            elif all(checks.get(key) == "pass" for key in case["required_checks"]) and not result["issues"]:
                result["status"] = "reviewed"
        results.append(result)
    counts = {status: sum(case["status"] == status for case in results)
              for status in ("reviewed", "failed", "not_reviewed", "missing_materials", "stale")}
    return {"status": "reviewed" if results and counts["reviewed"] == len(results) else "incomplete",
            "cases": results, "counts": counts, "real_cases": sum(c["kind"] == "real" for c in results),
            "limitation": "Review status records supplied reviewer observations; automated metadata is not visual or listening review."}


def run_editorial_command(args):
    if args.command == "music-override":
        result = apply_overrides(read_json(args.beatmap), read_json(args.overrides))
    elif args.command == "candidates":
        result = {"candidates": rank_candidates(read_json(args.library), read_json(args.preferences) if args.preferences else {}, args.query, _model(args.model))}
    elif args.command == "feedback":
        library = read_json(args.library)
        clip = next((c for c in library.get("clips", []) if str(c["id"]) == args.clip), None)
        if clip is None:
            raise ValueError(f"Unknown clip: {args.clip}")
        profile = read_json(args.profile) if Path(args.profile).is_file() else {}
        result = record_feedback(profile, clip, args.decision, args.reason, args.reviewer, str(Path(args.library).resolve()))
        write_json(args.profile, result)
        return {"profile": str(Path(args.profile).resolve()), "event": result["events"][-1]}
    elif args.command == "calibrate":
        result = calibrate(read_json(args.profile), args.holdout, args.seed)
    elif args.command == "evaluate-selection":
        result = evaluate_selection(read_json(args.project), read_json(args.labels), args.minimum_overlap)
    elif args.command == "review-manifest":
        result = create_manifest(args.projects, args.kind, args.scenario, args.render)
    elif args.command == "record-case-review":
        result = read_json(args.manifest)
        case = next((c for c in result.get("cases", []) if c["id"] == args.case), None)
        if case is None:
            raise ValueError("Unknown manifest case")
        if not args.notes.strip() or not args.reviewer.strip():
            raise ValueError("Review requires nonempty reviewer and notes")
        observations = read_json(args.observations)
        if not isinstance(observations, dict) or set(observations) != set(case["required_checks"]) or any(v not in ("pass", "fail", "not_reviewed") for v in observations.values()):
            raise ValueError("Observations must include exactly the required checks with pass/fail/not_reviewed values")
        case["review"] = {"reviewer": args.reviewer, "notes": args.notes, "reviewed_at": datetime.now(timezone.utc).isoformat(), "observations": observations}
        if args.labels:
            evaluate_selection(read_json(case["project"]), read_json(args.labels))
            case["labels"], case["labels_sha256"] = str(Path(args.labels).resolve()), _hash(args.labels)
        result.setdefault("review_history", []).append({"case": args.case, **case["review"], "project_sha256": case["project_sha256"]})
        write_json(args.manifest, result)
        return {"manifest": str(Path(args.manifest).resolve()), "case": args.case, "review": case["review"]}
    elif args.command == "evaluate-manifest":
        result = evaluate_manifest(read_json(args.manifest))
    else:
        raise ValueError(f"Unknown editorial command: {args.command}")
    if getattr(args, "output", None):
        write_json(args.output, result)
    return result
