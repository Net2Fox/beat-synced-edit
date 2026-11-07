"""Explainable local selection and auditable accept/reject feedback.

Scores rank candidates; they do not predict popularity or assert visual truth.
Semantic terms only come from editor annotations or imported transcripts.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re


# One shot-type vocabulary for annotations, planning, ranking and feedback.
SHOT_TYPES = ("wide", "medium", "close", "detail", "action", "unknown")
_SHOT_ALIASES = {"establishing": "wide", "long": "wide", "wideshot": "wide", "mediumshot": "medium",
                 "closeup": "close", "extremecloseup": "detail", "macro": "detail"}


def normalize_shot_type(value):
    """Canonical shot type: "close-up"/"closeup" -> "close", "establishing" -> "wide", etc."""
    key = str(value or "unknown").casefold().replace("-", "").replace("_", "").replace(" ", "")
    return _SHOT_ALIASES.get(key, key)


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
        result["shot:"+name] = float(normalize_shot_type(clip.get("shot_type")) == name)
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
    seen = {}
    for key in profile.get("shot_weights", {}):
        canonical = normalize_shot_type(key)
        if canonical not in SHOT_TYPES:
            raise ValueError(f"Unknown shot_weights key: {key}; use one of {', '.join(SHOT_TYPES)}")
        if canonical in seen:
            raise ValueError(f"shot_weights lists {seen[canonical]!r} and {key!r}, which are the same shot type")
        seen[canonical] = key
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


def preference_score(clip, profile=None, query=""):
    profile = validate_preferences(profile or {})
    tags = {str(t).casefold() for t in clip.get("tags", [])}
    query_terms = tokens(query)
    observed = tokens(" ".join([*map(str, clip.get("tags", [])), str(clip.get("notes", "")), str(clip.get("transcript", ""))]))
    matched = sorted(query_terms & observed)
    components = {
        "tag_preferences": sum(float(profile.get("tag_weights", {}).get(tag, 0)) for tag in tags),
        "shot_preference": next((float(weight) for name, weight in profile.get("shot_weights", {}).items()
                                 if normalize_shot_type(name) == normalize_shot_type(clip.get("shot_type"))), 0.),
        "asset_preference": float(profile.get("asset_weights", {}).get(str(clip.get("asset_id")), 0)),
        "query_match": 3. * len(matched) / max(1, len(query_terms)),
        "accepted_feedback": 2. if latest_decisions(profile).get(candidate_key(clip), {}).get("decision") == "accept" else 0.,
    }
    return {"total": sum(components.values()), "components": components, "matched_query_terms": matched,
            "unmatched_query_terms": sorted(query_terms-observed), "excluded": excluded_by_feedback(clip, profile)}


def explain_candidate(clip, base_score=0., base_components=None, profile=None, query=""):
    preference = preference_score(clip, profile, query)
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


def rank_candidates(library, profile=None, query=""):
    result = []
    for clip in library.get("clips", []):
        base = {"quality": float(clip.get("quality", .5)) * 2, "energy": float(clip.get("energy", .5))}
        result.append(explain_candidate(clip, sum(base.values()), base, profile, query))
    return sorted(result, key=lambda item: (item["excluded"], -item["score"], item["clip_id"]))
