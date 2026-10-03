"""Batch processing, final-file QA and explicit human/agent review evidence."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from project_workspace import read_json, write_json

WORKFLOW_COMMANDS = {"verify", "review-export", "batch-render", "batch-analyze"}


def register_workflow_commands(sub):
    verify = sub.add_parser("verify", help="Decode and inspect the actual exported MP4, including black/silent ranges")
    verify.add_argument("video")
    verify.add_argument("--project")
    verify.add_argument("--work", help="QA reports and contact sheets directory")
    review = sub.add_parser("review-export", help="Record supplied review observations against an unchanged export hash")
    review.add_argument("report")
    review.add_argument("--observations", required=True)
    review.add_argument("-o", "--output")
    batch = sub.add_parser("batch-render", help="Export a manifest of projects with a shared content-addressed shot cache")
    batch.add_argument("manifest", help='JSON {"jobs":[{"project":"...","output":"...","preview":false}]}')
    batch.add_argument("--work", required=True)
    batch.add_argument("--continue-on-error", action="store_true")
    analyze = sub.add_parser("batch-analyze", help="Analyze inputs as one reusable library for multiple edits")
    analyze.add_argument("inputs", nargs="+")
    analyze.add_argument("--work", required=True)
    analyze.add_argument("--annotations")
    analyze.add_argument("-o", "--output")


def render_with_qa(plan, output, preview=False, cache_dir=None, qa_dir=None, project_path=None):
    import hashlib
    import json
    from cli_contract import tool_signature
    from render_qa import file_hash
    from project_render import render_project
    from render_qa import verify_export, guard_export_outputs
    from speech_project import refresh_source_captions
    from timeline_map import refresh_anchors
    plan = deepcopy(plan)
    refresh_source_captions(plan)
    refresh_anchors(plan)
    protected = [project_path] if project_path else []
    guard_export_outputs(plan, output, qa_dir, protected)
    result = render_project(plan, output, preview=preview, cache_dir=cache_dir, protected_paths=protected)
    result["provenance"] = {"tool": tool_signature(),
                            "project_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
                            "output_sha256": file_hash(output)}
    expected = deepcopy(plan)
    expected["output"].update(width=result["width"], height=result["height"])
    qa = verify_export(output, expected, output_dir=qa_dir, protected_paths=protected)
    result["qa"] = {k: qa[k] for k in ("technical_pass", "report", "contact_sheets", "review_notes", "visual_review", "playback_review")}
    write_json(Path(output).with_suffix(".verification.json"), result)
    if not qa["technical_pass"]:
        raise RuntimeError(f"Export failed technical QA; inspect {qa['report']}")
    return result


def record_review(report, observations):
    from render_qa import file_hash
    if file_hash(report["path"]) != report["sha256"]:
        raise ValueError("Export changed since QA; verify the current file first")
    if not isinstance(observations, dict) or not isinstance(observations.get("reviewer"), str) or not observations["reviewer"].strip():
        raise ValueError("Review observations require reviewer and explicit evidence")
    allowed = {"reviewer", "visual", "editorial", "playback"}
    if set(observations) - allowed:
        raise ValueError("Unknown review observation fields")
    result = deepcopy(report)
    for key in ("visual", "editorial", "playback"):
        if key not in observations:
            continue
        value = observations[key]
        if not isinstance(value, dict) or value.get("status") not in ("pass", "fail", "not_reviewed"):
            raise ValueError("Review status must be pass, fail or not_reviewed")
        if value["status"] != "not_reviewed" and (not isinstance(value.get("evidence"), str) or not value["evidence"].strip()):
            raise ValueError("A completed review needs concrete evidence, such as inspected timestamps or playback observations")
        result[key + "_review"] = value["status"]
    result.setdefault("review_history", []).append(deepcopy(observations))
    return result


def run_workflow_command(args):
    if args.command == "verify":
        from render_qa import verify_export
        return verify_export(args.video, read_json(args.project) if args.project else None, args.work,
                             protected_paths=[args.project] if args.project else [])
    if args.command == "review-export":
        result = record_review(read_json(args.report), read_json(args.observations))
        destination = args.output or args.report
        if Path(destination).resolve() == Path(result["path"]).resolve():
            raise ValueError("Review report cannot overwrite the video")
        write_json(destination, result)
        return {"report": str(Path(destination).resolve()), **{k: result[k] for k in ("visual_review", "editorial_review", "playback_review")}}
    if args.command == "batch-analyze":
        from media_library import analyze_library
        work = Path(args.work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        library = analyze_library(args.inputs, str(work), annotations_path=args.annotations)
        output = Path(args.output).resolve() if args.output else work / "library.json"
        write_json(output, library)
        return {"library": str(output), "assets": len(library["assets"]), "clips": len(library["clips"]),
                "analysis_cache": library.get("analysis_cache"), "semantic_review": library.get("semantic_review")}
    if args.command == "batch-render":
        from project_plan import validate_plan
        manifest = Path(args.manifest).resolve()
        data = read_json(manifest)
        jobs = data.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            raise ValueError("Batch manifest needs a nonempty jobs list")
        work = Path(args.work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        prepared, outputs, protected = [], set(), {manifest}
        for job in jobs:
            if not isinstance(job, dict) or set(job) - {"project", "output", "preview"}:
                raise ValueError("Each job accepts project, output and preview")
            project, output = (Path(job[key]) for key in ("project", "output"))
            project = (manifest.parent / project).resolve()
            output = (manifest.parent / output).resolve()
            if output in outputs or output.suffix.lower() != ".mp4":
                raise ValueError("Each job needs a distinct .mp4 output")
            plan = read_json(project)
            validate_plan(plan)
            protected.add(project)
            from cli_contract import fingerprint_inputs
            from argparse import Namespace
            protected.update(Path(p) for p in fingerprint_inputs(Namespace(project=str(project)))["files"])
            outputs.add(output)
            prepared.append((project, output, plan, bool(job.get("preview", False))))
        if outputs & protected:
            raise ValueError("A batch output would overwrite an input")
        if (work / "batch-report.json") in protected:
            raise ValueError("Batch report would overwrite an input")
        from render_qa import guard_export_outputs
        for project, output, plan, preview in prepared:
            guard_export_outputs(plan, output, extra_protected=protected)
        results = []
        for project, output, plan, preview in prepared:
            try:
                result = render_with_qa(plan, str(output), preview, str(work / "cache"), project_path=project)
                results.append({"project": str(project), "ok": True, "result": result})
            except (ValueError, OSError, RuntimeError) as exc:
                results.append({"project": str(project), "ok": False, "error": str(exc)})
                if not args.continue_on_error:
                    break
            finally:
                write_json(work / "batch-report.json", {"jobs": results, "planned": len(prepared), "completed": len(results)})
        return {"report": str(work / "batch-report.json"), "jobs": results,
                "all_succeeded": len(results) == len(prepared) and all(j["ok"] for j in results)}
    raise ValueError(f"Unknown workflow command {args.command}")
