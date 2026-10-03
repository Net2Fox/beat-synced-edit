"""Explainable local selection, auditable feedback, and held-out calibration.

Scores rank candidates; they do not predict popularity or assert visual truth.
Semantic terms only come from editor annotations or imported transcripts.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re


def tokens(value):
    return set(re.findall(r"[^\W_]+", str(value).casefold(), flags=re.UNICODE))


def candidate_key(clip):
    identity = [clip.get("source_sha256") or clip.get("source") or clip.get("asset_id"),
                clip.get("kind", "video"), clip.get("start", 0), clip.get("end", 0)]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def candidate_features(clip):
    result = {"quality": float(clip.get("quality", .5)), "energy": float(clip.get("energy", .5)),
              "motion": float(clip.get("motion", 0)), "has_action": float(clip.get("action_time") is not None),
              "annotated": float(clip.get("semantic_source") == "annotation")}
    for name in ("wide", "medium", "close", "detail", "action"):
        result["shot:"+name] = float(clip.get("shot_type") == name)
    for tag in clip.get("tags", []):
        result["tag:"+str(tag).casefold()] = 1.
    if any(not math.isfinite(value) for value in result.values()):
        raise ValueError("Candidate features must be finite")
    return result


def validate_preferences(profile):
    if not isinstance(profile, dict):
        raise ValueError("preferences must be an object")
    for name in ("tag_weights", "shot_weights", "asset_weights"):
        if not isinstance(profile.get(name, {}), dict):
            raise ValueError(f"{name} must be an object")
        for value in profile.get(name, {}).values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 20:
                raise ValueError(f"{name} values must be finite between -20 and 20")
    if not isinstance(profile.get("events", []), list):
        raise ValueError("Feedback events must be a list")
    for event in profile.get("events", []):
        if not isinstance(event, dict) or event.get("decision") not in ("accept", "reject", "clear") or not event.get("candidate_key"):
            raise ValueError("Malformed feedback event")
    return profile


def latest_decisions(profile):
    validate_preferences(profile)
    result = {}
    for event in profile.get("events", []):
        result[event["candidate_key"]] = event
    return {key: event for key, event in result.items() if event["decision"] != "clear"}


def excluded_by_feedback(clip, profile):
    return latest_decisions(profile).get(candidate_key(clip), {}).get("decision") == "reject"


def record_feedback(profile, clip, decision, reason, reviewer="user", project=None):
    """Append rather than overwrite. A clear event reverses a previous decision."""
    validate_preferences(profile)
    if decision not in ("accept", "reject", "clear"):
        raise ValueError("decision must be accept, reject or clear")
    if not isinstance(reason, str) or not reason.strip() or not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Feedback requires a reason and reviewer")
    result = deepcopy(profile)
    events = result.setdefault("events", [])
    event = {"id": f"feedback-{len(events)+1:06d}", "at": datetime.now(timezone.utc).isoformat(),
             "candidate_key": candidate_key(clip), "clip_id": str(clip["id"]), "decision": decision,
             "reason": reason, "reviewer": reviewer, "project": project,
             "group": clip.get("source_sha256") or clip.get("source") or str(clip.get("asset_id")),
             "source": clip.get("source"), "start": clip.get("start"), "end": clip.get("end"),
             "features": candidate_features(clip)}
    event["previous_event"] = next((e["id"] for e in reversed(events) if e["candidate_key"] == event["candidate_key"]), None)
    events.append(event)
    result["version"] = 1
    return result


def predict(model, features):
    if model.get("version") != 1 or not isinstance(model.get("weights"), dict):
        raise ValueError("Invalid editorial model")
    values = [model.get("intercept", 0), *model["weights"].values()]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("Model coefficients must be finite")
    z = model.get("intercept", 0) + sum(weight * features.get(key, 0) for key, weight in model["weights"].items())
    return 1 / (1 + math.exp(-max(-40, min(40, z))))


def preference_score(clip, profile=None, query="", model=None):
    profile = validate_preferences(profile or {})
    tags = {str(t).casefold() for t in clip.get("tags", [])}
    query_terms = tokens(query)
    observed = tokens(" ".join([*map(str, clip.get("tags", [])), str(clip.get("notes", "")), str(clip.get("transcript", ""))]))
    matched = sorted(query_terms & observed)
    components = {
        "tag_preferences": sum(float(profile.get("tag_weights", {}).get(tag, 0)) for tag in tags),
        "shot_preference": float(profile.get("shot_weights", {}).get(clip.get("shot_type"), 0)),
        "asset_preference": float(profile.get("asset_weights", {}).get(str(clip.get("asset_id")), 0)),
        "query_match": 3. * len(matched) / max(1, len(query_terms)),
        "accepted_feedback": 2. if latest_decisions(profile).get(candidate_key(clip), {}).get("decision") == "accept" else 0.,
        "calibrated_preference": 2 * (predict(model, candidate_features(clip)) - .5) if model else 0.,
    }
    return {"total": sum(components.values()), "components": components, "matched_query_terms": matched,
            "unmatched_query_terms": sorted(query_terms-observed), "excluded": excluded_by_feedback(clip, profile)}


def explain_candidate(clip, base_score=0., base_components=None, profile=None, query="", model=None):
    preference = preference_score(clip, profile, query, model)
    components = {**(base_components or {"base": base_score}), **preference["components"]}
    measured = {key: clip[key] for key in ("motion", "brightness", "energy", "visual_hash") if key in clip}
    observed = {key: clip[key] for key in ("tags", "notes", "shot_type", "action_time", "quality") if key in clip}
    return {"candidate_key": candidate_key(clip), "clip_id": str(clip["id"]),
            "score": round(base_score + preference["total"], 6),
            "components": {k: round(v, 6) for k, v in components.items()},
            "reason": [f"{key}: {value:+.3f}" for key, value in components.items() if abs(value) > 1e-8],
            "matched_query_terms": preference["matched_query_terms"], "unmatched_query_terms": preference["unmatched_query_terms"],
            "excluded": preference["excluded"] or clip.get("exclude") is True,
            "evidence": {"source": clip.get("source"), "source_sha256": clip.get("source_sha256"),
                         "source_start": clip.get("start"), "source_end": clip.get("end"),
                         "measurements": measured, "observations": observed,
                         "observation_origin": clip.get("semantic_source", "unverified-library-fields"),
                         "thumbnail": clip.get("thumb"), "annotation_evidence": clip.get("annotation_evidence", {})}}


def rank_candidates(library, profile=None, query="", model=None):
    result = []
    for clip in library.get("clips", []):
        base = {"quality": float(clip.get("quality", .5)) * 2, "energy": float(clip.get("energy", .5))}
        result.append(explain_candidate(clip, sum(base.values()), base, profile, query, model))
    return sorted(result, key=lambda item: (item["excluded"], -item["score"], item["clip_id"]))


def _metrics(rows, predictions):
    tp = sum(y == 1 and p >= .5 for (_, y), p in zip(rows, predictions))
    fp = sum(y == 0 and p >= .5 for (_, y), p in zip(rows, predictions))
    fn = sum(y == 1 and p < .5 for (_, y), p in zip(rows, predictions))
    tn = len(rows)-tp-fp-fn
    return {"n": len(rows), "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
            "precision": tp/(tp+fp) if tp+fp else None, "recall": tp/(tp+fn) if tp+fn else None,
            "accuracy": (tp+tn)/len(rows) if rows else None,
            "brier_score": sum((p-y)**2 for (_, y), p in zip(rows, predictions))/len(rows) if rows else None}


def calibrate(profile, holdout_fraction=.25, seed="beat-sync", iterations=500):
    """Train only on train sources, evaluate on disjoint held-out sources.

    Candidate scenes from one source never straddle the split. The returned model
    is the evaluated train model, not an unmeasured refit on all observations.
    """
    if not .1 <= holdout_fraction <= .5:
        raise ValueError("holdout_fraction must be between .1 and .5")
    events = list(latest_decisions(profile).values())
    groups = sorted({e["group"] for e in events}, key=lambda value: hashlib.sha256((seed+value).encode()).hexdigest())
    if len(events) < 6 or len(groups) < 3 or len({e["decision"] for e in events}) < 2:
        return {"status": "insufficient_data", "model": None, "reason": "Need at least six reviewed candidates, three independent sources and both accept/reject labels"}
    count = max(1, round(len(groups)*holdout_fraction))
    held_out = set(groups[:count])
    train = [(e, int(e["decision"] == "accept")) for e in events if e["group"] not in held_out]
    test = [(e, int(e["decision"] == "accept")) for e in events if e["group"] in held_out]
    if len({y for _, y in train}) < 2:
        return {"status": "insufficient_data", "model": None, "reason": "Training sources need both accept/reject labels; collect more independent examples"}
    vocabulary = sorted({name for e, _ in train for name in e["features"]})
    model = {"version": 1, "weights": {name: 0. for name in vocabulary}, "intercept": 0.,
             "training_candidate_keys": [e["candidate_key"] for e, _ in train], "training_groups": sorted(set(groups)-held_out)}
    for _ in range(iterations):
        errors = [(e, predict(model, e["features"])-y) for e, y in train]
        model["intercept"] -= .15 * sum(error for _, error in errors)/len(train)
        for name in vocabulary:
            gradient = sum(error*e["features"].get(name, 0) for e, error in errors)/len(train) + .02*model["weights"][name]
            model["weights"][name] -= .15*gradient
    predictions = [predict(model, e["features"]) for e, _ in test]
    baseline = sum(y for _, y in train)/len(train)
    return {"status": "evaluated", "model": model, "split": {"method": "deterministic-source-group-holdout", "seed": seed,
            "train_count": len(train), "test_count": len(test), "holdout_groups": sorted(held_out),
            "holdout_candidate_keys": [e["candidate_key"] for e, _ in test]},
            "metrics": _metrics(test, predictions), "baseline_metrics": _metrics(test, [baseline]*len(test)),
            "limitations": ["Small personal preference dataset; report is not a claim about virality or visual quality.",
                            "Held-out sources were not used for training or vocabulary selection."]}


def evaluate_selection(plan, labels, minimum_overlap=.5):
    """Evaluate annotated source moments; unknown moments are never negatives."""
    if not 0 < minimum_overlap <= 1:
        raise ValueError("minimum_overlap must be in (0,1]")
    records = labels.get("labels", labels) if isinstance(labels, dict) else labels
    if not isinstance(records, list):
        raise ValueError("labels must be a list")
    selected, missed, false, rejected, unreviewed = [], [], [], [], []
    covered_shots = set()
    for index, label in enumerate(records):
        if not isinstance(label, dict):
            raise ValueError("Selection labels must be objects")
        if label.get("decision") not in ("accept", "reject"):
            raise ValueError("Selection labels require accept or reject decisions")
        matches, overlaps = [], []
        if label.get("clip_id") is None and label.get("asset_id") is None:
            raise ValueError("Selection labels require clip_id or asset_id")
        bounded = "start" in label or "end" in label
        if bounded:
            begin, end = label.get("start"), label.get("end")
            if isinstance(begin, bool) or isinstance(end, bool) or not isinstance(begin, (int, float)) or not isinstance(end, (int, float)) or not math.isfinite(begin+end) or not 0 <= begin < end:
                raise ValueError("Selection label range must have finite positive duration")
        for shot in plan.get("edits", []):
            if label.get("clip_id") is not None and str(label["clip_id"]) != str(shot.get("clip_id")):
                continue
            if label.get("asset_id") is not None and str(label["asset_id"]) != str(shot.get("asset_id")):
                continue
            if bounded:
                left, right = max(begin, shot["source_start"]), min(end, shot["source_end"])
                if right <= left:
                    continue
                overlaps.append((left, right))
            matches.append(shot["id"])
        coverage = None
        if bounded:
            last, total = -math.inf, 0.
            for left, right in sorted(overlaps):
                total += max(0., right-max(left, last))
                last = max(last, right)
            coverage = total/(end-begin)
            if coverage+1e-8 < minimum_overlap:
                matches = []
        result = {"label_id": str(label.get("id", index)), "clip_id": label.get("clip_id"), "asset_id": label.get("asset_id"), "shots": matches}
        if bounded:
            result["source_range_coverage"] = coverage
        covered_shots.update(matches)
        if label["decision"] == "accept":
            (selected if matches else missed).append(result)
        else:
            (false if matches else rejected).append(result)
    unreviewed = [s["id"] for s in plan.get("edits", []) if s["id"] not in covered_shots]
    return {"status": "evaluated" if records else "not_reviewed", "true_selections": selected, "missed_moments": missed,
            "false_selections": false, "correct_rejections": rejected, "unreviewed_shots": unreviewed,
            "precision": len(selected)/(len(selected)+len(false)) if selected or false else None,
            "recall": len(selected)/(len(selected)+len(missed)) if selected or missed else None,
            "minimum_overlap": minimum_overlap, "scope": "Supplied labels only; unlabeled material is not judged"}
