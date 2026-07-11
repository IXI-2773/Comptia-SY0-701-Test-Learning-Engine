import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Mapping

from progress_store import now_iso
from smart_practice_profile import SMART_PRACTICE_POLICY_VERSION

GRAPH_SCHEMA_VERSION = 1
GRAPH_VERSION = "smart-practice-graph-1"
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
VALID_EVIDENCE_LEVELS = {"explicit", "strong", "moderate", "weak", "fallback"}
VALID_EDGE_TYPES = {
    "prerequisite_of",
    "confusable_with",
    "related_to",
    "transfer_variant_of",
    "evidence_against",
}
VALID_EDGE_STATUSES = {"active", "provisional", "weakened", "rejected", "disabled"}
VALID_DIAGNOSES = {
    "missing_prerequisite",
    "target_concept_weakness",
    "concept_confusion",
    "transfer_failure",
    "item_specific_failure",
    "source_quality_problem",
    "insufficient_evidence",
}


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def normalize_label(value: Any) -> str:
    text = str(value or "").casefold()
    text = NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


def compact_label(value: Any) -> str:
    return normalize_label(value).replace(" ", "_")


def concept_key_for_question(question: Mapping[str, Any], coverage_unit: str | None = None) -> tuple[str, str]:
    qnum = int(question.get("question_number") or 0)
    objective = normalize_label(question.get("objective_code"))
    domain = normalize_label(question.get("domain"))
    topics = [str(topic) for topic in question.get("topics", []) if str(topic).strip()]
    topic = normalize_label(topics[0] if topics else question.get("topic", ""))
    repair_key = normalize_label(question.get("repair_concept_key"))
    twin = normalize_label(question.get("question_twin_group") or question.get("confusion_pair_group"))
    if coverage_unit:
        return f"coverage::{compact_label(coverage_unit)}", "explicit"
    if objective and topic:
        return f"objective_topic::{compact_label(objective)}::{compact_label(topic)}", "strong"
    if repair_key:
        return f"repair::{compact_label(repair_key)}", "strong"
    if twin:
        return f"group::{compact_label(twin)}", "moderate"
    if objective:
        return f"objective::{compact_label(objective)}", "moderate"
    if domain and topic:
        return f"domain_topic::{compact_label(domain)}::{compact_label(topic)}", "weak"
    return f"question::{qnum}", "fallback"


def concept_display(question: Mapping[str, Any]) -> str:
    topics = [str(topic) for topic in question.get("topics", []) if str(topic).strip()]
    if question.get("objective_code") and topics:
        return f"{question.get('objective_code')} - {topics[0]}"
    if topics:
        return topics[0]
    if question.get("domain"):
        return str(question.get("domain"))
    return f"Question {int(question.get('question_number') or 0)}"


def concept_record_for_question(question: Mapping[str, Any], coverage_unit: str | None = None, created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or now_iso()
    key, evidence = concept_key_for_question(question, coverage_unit=coverage_unit)
    topics = [str(topic) for topic in question.get("topics", []) if str(topic).strip()]
    return {
        "concept_key": key,
        "display_name": concept_display(question),
        "objective_code": str(question.get("objective_code") or ""),
        "domain": str(question.get("domain") or ""),
        "topic": topics[0] if topics else str(question.get("topic") or ""),
        "supporting_question_numbers": [int(question.get("question_number") or 0)],
        "source_count": 1 if question.get("source_name") or question.get("source_label") else 0,
        "stem_style_count": 1 if question.get("stem_style") else 0,
        "evidence_level": evidence,
        "created_at": created_at,
        "updated_at": created_at,
    }


def merge_concept_records(existing: Mapping[str, Any], incoming: Mapping[str, Any], updated_at: str | None = None) -> dict[str, Any]:
    updated_at = updated_at or now_iso()
    out = dict(existing)
    qnums = set(int(q) for q in out.get("supporting_question_numbers", []) if str(q).strip())
    qnums.update(int(q) for q in incoming.get("supporting_question_numbers", []) if str(q).strip())
    out["supporting_question_numbers"] = sorted(qnums)
    out["source_count"] = max(int(out.get("source_count", 0) or 0), int(incoming.get("source_count", 0) or 0))
    out["stem_style_count"] = max(int(out.get("stem_style_count", 0) or 0), int(incoming.get("stem_style_count", 0) or 0))
    out["updated_at"] = updated_at
    return out


def empty_graph(created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or now_iso()
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "concepts": {},
        "edges": {},
        "diagnoses": {},
        "graph_signature": stable_id("graph", GRAPH_SCHEMA_VERSION, created_at),
        "last_updated_at": created_at,
        "invalid_records": {},
    }


def edge_id(source: str, target: str, edge_type: str, evidence_sources: list[str] | None = None) -> str:
    return stable_id("edge", source, target, edge_type, ",".join(sorted(evidence_sources or [])))


def make_edge(
    source: str,
    target: str,
    edge_type: str,
    *,
    weight: float,
    evidence_level: str,
    evidence_sources: list[str] | None = None,
    support_count: int = 1,
    contradiction_count: int = 0,
    status: str = "active",
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at = created_at or now_iso()
    if evidence_level == "weak" and status == "active":
        status = "provisional"
    return {
        "edge_id": edge_id(source, target, edge_type, evidence_sources),
        "source_concept_key": source,
        "target_concept_key": target,
        "edge_type": edge_type,
        "weight": round(max(0.0, min(1.0, float(weight or 0.0))), 4),
        "evidence_level": evidence_level if evidence_level in VALID_EVIDENCE_LEVELS else "weak",
        "evidence_sources": [str(value) for value in evidence_sources or []],
        "support_count": int(support_count or 0),
        "contradiction_count": int(contradiction_count or 0),
        "weighted_support": round(max(0.0, float(support_count or 0)), 4),
        "weighted_contradiction": round(max(0.0, float(contradiction_count or 0)), 4),
        "last_evaluated_at": "",
        "calibration_status": "unevaluated",
        "confidence": 0.0,
        "created_at": created_at,
        "updated_at": created_at,
        "status": status if status in VALID_EDGE_STATUSES else "rejected",
    }


def calibration_store(created_at: str | None = None) -> dict[str, Any]:
    created_at = created_at or now_iso()
    return {
        "schema_version": 1,
        "edge_calibration": {},
        "graph_audits": {},
        "question_quality": {},
        "information_value_history": {},
        "last_updated_at": created_at,
        "invalid_records": {},
    }


def distinct_groups(outcomes: list[Mapping[str, Any]]) -> set[str]:
    return {
        str(row.get("group_id") or f"{row.get('session_id','')}:{row.get('question_number','')}:{row.get('concept_key','')}")
        for row in outcomes
        if str(row.get("created_at") or row.get("at") or "") < str(row.get("observed_at") or row.get("at") or "z")
    }


def calibrate_edge(
    edge: Mapping[str, Any],
    outcomes: list[Mapping[str, Any]],
    graph: Mapping[str, Any] | None = None,
    *,
    evaluated_at: str | None = None,
    minimum_support: int = 3,
    minimum_contradiction: int = 2,
    rejection_contradiction: int = 4,
    max_adjustment: float = 0.10,
) -> dict[str, Any]:
    evaluated_at = evaluated_at or now_iso()
    result = dict(edge)
    support_groups = distinct_groups([row for row in outcomes if row.get("supports_edge")])
    contradiction_groups = distinct_groups([row for row in outcomes if row.get("contradicts_edge")])
    support_delta = len(support_groups)
    contradiction_delta = len(contradiction_groups)
    old_weight = float(result.get("weight", 0.0) or 0.0)
    direction = 1 if support_delta >= minimum_support and support_delta > contradiction_delta else -1 if contradiction_delta >= minimum_contradiction else 0
    adjustment = max(-max_adjustment, min(max_adjustment, direction * max_adjustment))
    result["support_count"] = int(result.get("support_count", 0) or 0) + support_delta
    result["contradiction_count"] = int(result.get("contradiction_count", 0) or 0) + contradiction_delta
    result["weighted_support"] = round(float(result.get("weighted_support", 0.0) or 0.0) + support_delta, 4)
    result["weighted_contradiction"] = round(float(result.get("weighted_contradiction", 0.0) or 0.0) + contradiction_delta, 4)
    result["weight"] = round(max(0.0, min(1.0, old_weight + adjustment)), 4)
    result["last_evaluated_at"] = evaluated_at
    result["confidence"] = round(result["weighted_support"] / max(1.0, result["weighted_support"] + result["weighted_contradiction"]), 4)
    if contradiction_delta >= rejection_contradiction and result["weighted_support"] < minimum_support:
        result["status"] = "rejected"
        result["calibration_status"] = "rejected_by_contradiction"
    elif contradiction_delta >= minimum_contradiction and contradiction_delta >= support_delta:
        result["status"] = "weakened"
        result["calibration_status"] = "weakened"
    elif support_delta >= minimum_support:
        result["status"] = "active"
        result["calibration_status"] = "strengthened"
        if result.get("edge_type") == "prerequisite_of" and graph:
            test = dict((graph.get("edges") or {}))
            test[result["edge_id"]] = result
            if prerequisite_cycle(test):
                result["status"] = "provisional"
                result["calibration_status"] = "cycle_blocked"
    else:
        result["status"] = result.get("status") or "provisional"
        result["calibration_status"] = "insufficient_evidence"
    return result


def calibrate_edges(graph: Mapping[str, Any], outcomes: list[Mapping[str, Any]], *, evaluated_at: str | None = None, policy: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    values = dict((policy or {}).get("policy_values") or {})
    max_adjust = float(values.get("edge_weight_max_adjustment", 0.10) or 0.10)
    min_support = int(values.get("minimum_edge_support", 3) or 3)
    min_contra = int(values.get("minimum_edge_contradiction", 2) or 2)
    clean = normalize_graph(graph)
    metrics = {"edges_evaluated": 0, "edges_strengthened": 0, "edges_weakened": 0, "edges_rejected": 0, "provisional_to_active": 0, "cycle_blocked_activations": 0, "mean_edge_weight_change": 0.0, "support_outcomes": 0, "contradiction_outcomes": 0}
    changes = []
    for edge_id_value, edge in list(clean.get("edges", {}).items()):
        related = [row for row in outcomes if str(row.get("edge_id") or "") == edge_id_value]
        if not related:
            continue
        before = float(edge.get("weight", 0.0) or 0.0)
        before_status = str(edge.get("status") or "")
        calibrated = calibrate_edge(edge, related, clean, evaluated_at=evaluated_at, minimum_support=min_support, minimum_contradiction=min_contra, max_adjustment=max_adjust)
        clean["edges"][edge_id_value] = calibrated
        metrics["edges_evaluated"] += 1
        metrics["support_outcomes"] += len([row for row in related if row.get("supports_edge")])
        metrics["contradiction_outcomes"] += len([row for row in related if row.get("contradicts_edge")])
        changes.append(abs(float(calibrated.get("weight", 0.0) or 0.0) - before))
        if calibrated["calibration_status"] == "strengthened":
            metrics["edges_strengthened"] += 1
        if calibrated["calibration_status"] == "weakened":
            metrics["edges_weakened"] += 1
        if calibrated["calibration_status"] == "rejected_by_contradiction":
            metrics["edges_rejected"] += 1
        if before_status == "provisional" and calibrated["status"] == "active":
            metrics["provisional_to_active"] += 1
        if calibrated["calibration_status"] == "cycle_blocked":
            metrics["cycle_blocked_activations"] += 1
    metrics["mean_edge_weight_change"] = round(sum(changes) / len(changes), 4) if changes else 0.0
    return clean, metrics


def audit_graph(graph: Mapping[str, Any], questions: list[Mapping[str, Any]] | None = None, objectives: list[str] | None = None, *, max_active_edges: int = 12) -> dict[str, Any]:
    clean = normalize_graph(graph, questions or [])
    concepts = clean.get("concepts", {})
    edges = clean.get("edges", {})
    active = [e for e in edges.values() if e.get("status") == "active"]
    connected = {e.get("source_concept_key") for e in active} | {e.get("target_concept_key") for e in active}
    edge_counts = Counter([e.get("source_concept_key") for e in active] + [e.get("target_concept_key") for e in active])
    by_domain = Counter(str(c.get("domain") or "Unknown") for c in concepts.values())
    by_objective = Counter(str(c.get("objective_code") or "Unknown") for c in concepts.values())
    duplicate_candidates = []
    seen = {}
    for key, concept in concepts.items():
        sig = (normalize_label(concept.get("objective_code")), normalize_label(concept.get("topic")))
        if sig in seen and sig != ("", ""):
            duplicate_candidates.append([seen[sig], key])
        else:
            seen[sig] = key
    teaching = {concept_key_for_question(q)[0] for q in questions or []}
    prereq_without = sorted({e.get("source_concept_key") for e in active if e.get("edge_type") == "prerequisite_of" and e.get("source_concept_key") not in teaching})
    return {
        "total_concepts": len(concepts),
        "total_edges": len(edges),
        "active_edges": len(active),
        "provisional_edges": sum(1 for e in edges.values() if e.get("status") == "provisional"),
        "weakened_edges": sum(1 for e in edges.values() if e.get("status") == "weakened"),
        "rejected_edges": sum(1 for e in edges.values() if e.get("status") == "rejected"),
        "orphan_concepts": sorted(k for k, c in concepts.items() if k not in connected and len(c.get("supporting_question_numbers", [])) < 2),
        "single_question_concepts": sorted(k for k, c in concepts.items() if len(c.get("supporting_question_numbers", [])) <= 1),
        "single_source_concepts": sorted(k for k, c in concepts.items() if int(c.get("source_count", 0) or 0) <= 1),
        "concepts_without_transfer_items": sorted(k for k, c in concepts.items() if int(c.get("stem_style_count", 0) or 0) <= 1),
        "prerequisites_without_teaching_questions": prereq_without,
        "objectives_without_concepts": sorted(set(objectives or []) - {str(c.get("objective_code") or "") for c in concepts.values()}),
        "questions_without_meaningful_concepts": [int(q.get("question_number") or 0) for q in questions or [] if concept_key_for_question(q)[1] == "fallback"],
        "weak_evidence_edges": sorted(e.get("edge_id") for e in edges.values() if e.get("evidence_level") in {"weak", "fallback"}),
        "overconnected_concepts": sorted(k for k, count in edge_counts.items() if count > max_active_edges),
        "duplicate_candidate_concepts": duplicate_candidates,
        "active_cycle_count": 1 if prerequisite_cycle(edges) else 0,
        "invalid_record_count": len(clean.get("invalid_records", {})),
        "coverage_by_domain": dict(by_domain),
        "coverage_by_objective": dict(by_objective),
    }


def select_prerequisite_path(target_key: str, graph: Mapping[str, Any], states: Mapping[str, Mapping[str, Any]], *, max_depth: int = 2, max_parents: int = 3) -> list[str]:
    clean = normalize_graph(graph)
    edges = [e for e in active_edges(clean, "prerequisite_of") if e.get("target_concept_key") == target_key]
    edges = sorted(edges, key=lambda e: (-float(e.get("weight", 0.0) or 0.0), float(states.get(str(e.get("source_concept_key")), {}).get("lowest_retrievability", 1.0) or 1.0), str(e.get("source_concept_key"))))[:max_parents]
    path = [str(e.get("source_concept_key")) for e in edges[:max_depth]]
    return path[:max_depth]


def validate_edge(edge: Mapping[str, Any], concepts: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    source = str(edge.get("source_concept_key") or "")
    target = str(edge.get("target_concept_key") or "")
    if not source or not target:
        reasons.append("missing_concept_key")
    if source == target:
        reasons.append("self_edge")
    if edge.get("edge_type") not in VALID_EDGE_TYPES:
        reasons.append("unknown_edge_type")
    if edge.get("evidence_level") not in VALID_EVIDENCE_LEVELS:
        reasons.append("unknown_evidence_level")
    if edge.get("status") not in VALID_EDGE_STATUSES:
        reasons.append("unknown_status")
    if concepts and (source not in concepts or target not in concepts):
        reasons.append("missing_concept")
    return not reasons, reasons


def prerequisite_cycle(edges: Mapping[str, Mapping[str, Any]]) -> bool:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges.values():
        if edge.get("edge_type") == "prerequisite_of" and edge.get("status") == "active":
            graph[str(edge.get("source_concept_key"))].append(str(edge.get("target_concept_key")))
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for child in graph.get(node, []):
            if visit(child):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in list(graph))


def normalize_graph(graph: Mapping[str, Any] | None, questions: list[Mapping[str, Any]] | None = None, created_at: str | None = None) -> dict[str, Any]:
    clean = empty_graph(created_at=created_at)
    if isinstance(graph, Mapping):
        clean["concepts"] = dict(graph.get("concepts") or {})
        clean["edges"] = dict(graph.get("edges") or {})
        clean["diagnoses"] = dict(graph.get("diagnoses") or {})
        clean["last_updated_at"] = str(graph.get("last_updated_at") or clean["last_updated_at"])
        clean["invalid_records"] = dict(graph.get("invalid_records") or {})
    for question in questions or []:
        concept = concept_record_for_question(question, created_at=clean["last_updated_at"])
        key = concept["concept_key"]
        clean["concepts"][key] = merge_concept_records(clean["concepts"][key], concept) if key in clean["concepts"] else concept
    active_edges: dict[str, Mapping[str, Any]] = {}
    normalized_edges: dict[str, dict[str, Any]] = {}
    for edge_key, raw in list(clean["edges"].items()):
        edge = make_edge(
            str(raw.get("source_concept_key") or ""),
            str(raw.get("target_concept_key") or ""),
            str(raw.get("edge_type") or ""),
            weight=float(raw.get("weight", 0.0) or 0.0),
            evidence_level=str(raw.get("evidence_level") or "weak"),
            evidence_sources=list(raw.get("evidence_sources") or []),
            support_count=int(raw.get("support_count", 0) or 0),
            contradiction_count=int(raw.get("contradiction_count", 0) or 0),
            status=str(raw.get("status") or "rejected"),
            created_at=str(raw.get("created_at") or clean["last_updated_at"]),
        )
        edge["edge_id"] = str(raw.get("edge_id") or edge["edge_id"])
        ok, reasons = validate_edge(edge, clean["concepts"])
        duplicate_key = (edge["source_concept_key"], edge["target_concept_key"], edge["edge_type"])
        if edge["status"] == "active" and duplicate_key in active_edges:
            ok = False
            reasons.append("duplicate_active_edge")
        if not ok:
            edge["status"] = "disabled"
            clean["invalid_records"][edge["edge_id"]] = reasons
        if edge.get("edge_type") == "prerequisite_of" and edge.get("status") == "active":
            test_edges = dict(active_edges)
            test_edges[edge["edge_id"]] = edge
            if prerequisite_cycle(test_edges):
                edge["status"] = "rejected" if edge.get("evidence_level") in {"weak", "moderate"} else "disabled"
                clean["invalid_records"][edge["edge_id"]] = ["prerequisite_cycle"]
        normalized_edges[edge["edge_id"]] = edge
        if edge["status"] == "active":
            active_edges[duplicate_key] = edge
    clean["edges"] = normalized_edges
    clean["graph_signature"] = stable_id("graph", json.dumps(clean["concepts"], sort_keys=True, default=str), json.dumps(clean["edges"], sort_keys=True, default=str))
    return clean


def add_edge(graph: Mapping[str, Any], edge: Mapping[str, Any]) -> tuple[dict[str, Any], bool, list[str]]:
    clean = normalize_graph(graph)
    candidate = dict(edge)
    clean["edges"][str(candidate.get("edge_id") or edge_id(candidate.get("source_concept_key"), candidate.get("target_concept_key"), candidate.get("edge_type")))] = candidate
    normalized = normalize_graph(clean)
    stored = normalized["edges"].get(str(candidate.get("edge_id") or ""))
    reasons = list(normalized.get("invalid_records", {}).get(str(candidate.get("edge_id") or ""), []))
    return normalized, bool(stored and stored.get("status") == "active"), reasons


def aggregate_concept_state(concept_key: str, questions: list[Mapping[str, Any]], records: Mapping[str, Mapping[str, Any]], history: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    concept_questions = [q for q in questions if concept_key_for_question(q)[0] == concept_key or q.get("smart_concept_key") == concept_key]
    per_question = []
    sources = set()
    styles = set()
    for question in concept_questions:
        qnum = int(question.get("question_number") or 0)
        rec = dict(records.get(str(qnum), {}) or records.get(qnum, {}) or {})
        memory = dict(rec.get("learner_memory") or {})
        attempts = int(rec.get("attempts", 0) or 0)
        correct = int(rec.get("correct_count", 0) or 0)
        wrong = int(rec.get("wrong_count", 0) or 0)
        if attempts or correct or wrong:
            per_question.append(
                {
                    "retrievability": float(memory.get("retrievability", 0.35) or 0.35),
                    "stability": float(memory.get("stability", 0.0) or 0.0),
                    "uncertainty": float(memory.get("uncertainty", 0.65) or 0.65),
                    "attempts": attempts,
                    "correct": correct,
                    "wrong": wrong,
                    "last": str(memory.get("last_reviewed_at") or rec.get("last_seen") or ""),
                    "next": str(memory.get("next_review_at") or rec.get("next_review") or ""),
                }
            )
        if question.get("source_name") or question.get("source_label"):
            sources.add(str(question.get("source_name") or question.get("source_label")))
        if question.get("stem_style"):
            styles.add(str(question.get("stem_style")))
    if not per_question:
        return {
            "concept_key": concept_key,
            "stability": 0.0,
            "lowest_retrievability": 0.0,
            "mean_retrievability": 0.0,
            "uncertainty": 1.0,
            "attempt_count": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "high_confidence_wrong_count": 0,
            "distinct_question_count": len(concept_questions),
            "distinct_source_count": len(sources),
            "distinct_stem_style_count": len(styles),
            "last_reviewed_at": "",
            "next_review_at": "",
            "evidence_strength": "insufficient_evidence",
        }
    high_conf_wrong = sum(
        1
        for event in history or []
        if str(event.get("smart_concept_key") or "") == concept_key
        and event.get("correct") is False
        and str(event.get("confidence") or "") == "Sure"
    )
    attempts = sum(min(1, row["attempts"]) for row in per_question)
    correct = sum(1 for row in per_question if row["correct"] > 0)
    wrong = sum(1 for row in per_question if row["wrong"] > 0)
    return {
        "concept_key": concept_key,
        "stability": round(sum(row["stability"] for row in per_question) / len(per_question), 4),
        "lowest_retrievability": round(min(row["retrievability"] for row in per_question), 4),
        "mean_retrievability": round(sum(row["retrievability"] for row in per_question) / len(per_question), 4),
        "uncertainty": round(sum(row["uncertainty"] for row in per_question) / len(per_question), 4),
        "attempt_count": attempts,
        "correct_count": correct,
        "wrong_count": wrong,
        "high_confidence_wrong_count": high_conf_wrong,
        "distinct_question_count": len(per_question),
        "distinct_source_count": len(sources),
        "distinct_stem_style_count": len(styles),
        "last_reviewed_at": max((row["last"] for row in per_question), default=""),
        "next_review_at": min((row["next"] for row in per_question if row["next"]), default=""),
        "evidence_strength": "strong" if len(per_question) >= 3 else "moderate" if len(per_question) >= 2 else "weak",
    }


def active_edges(graph: Mapping[str, Any], edge_type: str | None = None) -> list[Mapping[str, Any]]:
    edges = []
    for edge in (graph.get("edges") or {}).values():
        if edge.get("status") == "active" and (edge_type is None or edge.get("edge_type") == edge_type):
            edges.append(edge)
    return sorted(edges, key=lambda e: (str(e.get("source_concept_key")), str(e.get("target_concept_key")), str(e.get("edge_type"))))


def diagnose_root_cause(
    question: Mapping[str, Any],
    graph: Mapping[str, Any],
    concept_states: Mapping[str, Mapping[str, Any]],
    item_history: list[Mapping[str, Any]] | None = None,
    *,
    source_trust: Mapping[str, Any] | None = None,
    feedback: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    diagnosed_at: str | None = None,
) -> dict[str, Any]:
    diagnosed_at = diagnosed_at or now_iso()
    policy_values = dict((policy or {}).get("policy_values") or {})
    graph_enabled = bool(policy_values.get("graph_enabled", True))
    minimum_confidence = float(policy_values.get("minimum_diagnosis_confidence", 0.45) or 0.45)
    target_key = concept_key_for_question(question)[0]
    target_state = dict(concept_states.get(target_key) or {})
    history = list(item_history or [])
    source_trust = dict(source_trust or {})
    evidence: list[str] = []
    counter: list[str] = []
    diagnosis = "insufficient_evidence"
    confidence = 0.0
    supporting: list[str] = []
    if not graph_enabled:
        return _diagnosis(diagnosis, 0.0, target_key, supporting, ["graph_disabled"], counter, "collect_more_evidence", diagnosed_at)
    weak_target = int(target_state.get("wrong_count", 0) or 0) > int(target_state.get("correct_count", 0) or 0) or float(target_state.get("lowest_retrievability", 0.0) or 0.0) < 0.45
    repeated = int(target_state.get("distinct_question_count", 0) or 0) >= 2 or len(history) >= 2
    prereqs = [edge for edge in active_edges(graph, "prerequisite_of") if edge.get("target_concept_key") == target_key]
    for edge in prereqs:
        source_key = str(edge.get("source_concept_key"))
        source_state = dict(concept_states.get(source_key) or {})
        weak_source = int(source_state.get("wrong_count", 0) or 0) > int(source_state.get("correct_count", 0) or 0) or float(source_state.get("lowest_retrievability", 1.0) or 1.0) < 0.45
        if weak_target and weak_source and float(edge.get("weight", 0.0) or 0.0) >= 0.45 and repeated:
            diagnosis = "missing_prerequisite"
            confidence = min(0.95, 0.45 + float(edge.get("weight", 0.0) or 0.0) * 0.4)
            supporting = [source_key]
            evidence = ["target_weak", "prerequisite_weak", "supported_prerequisite_edge"]
            break
        if source_state and not weak_source:
            counter.append("prerequisite_stable")
    if diagnosis == "insufficient_evidence":
        confusions = [edge for edge in active_edges(graph, "confusable_with") if edge.get("source_concept_key") == target_key or edge.get("target_concept_key") == target_key]
        repeated_confusion = any(str(event.get("wrong_answer_family") or event.get("selected_concept_key") or "") for event in history if event.get("correct") is False)
        if confusions and repeated_confusion and len([event for event in history if event.get("correct") is False]) >= 2:
            diagnosis = "concept_confusion"
            confidence = 0.78
            supporting = [str(confusions[0].get("target_concept_key"))]
            evidence = ["confusable_edge", "repeated_distractor_substitution"]
    if diagnosis == "insufficient_evidence":
        exact_success = any(event.get("correct") and str(event.get("stem_style") or "") == str(question.get("stem_style") or "") for event in history)
        transfer_fail = any(event.get("correct") is False and str(event.get("stem_style") or "") != str(question.get("stem_style") or "") for event in history)
        if exact_success and transfer_fail:
            diagnosis = "transfer_failure"
            confidence = 0.72
            evidence = ["familiar_item_success", "different_context_failure"]
    if diagnosis == "insufficient_evidence" and weak_target and repeated and counter:
        diagnosis = "target_concept_weakness"
        confidence = 0.68
        evidence = ["target_repeated_weakness", "prerequisites_stable"]
    if diagnosis == "insufficient_evidence":
        qnum = int(question.get("question_number") or 0)
        item_wrong = sum(1 for event in history if int(event.get("question_number") or 0) == qnum and event.get("correct") is False)
        other_correct = sum(1 for event in history if int(event.get("question_number") or 0) != qnum and event.get("correct"))
        if item_wrong >= 2 and other_correct >= 2:
            diagnosis = "item_specific_failure"
            confidence = 0.7
            evidence = ["isolated_item_failures", "other_concept_items_successful"]
    if diagnosis == "insufficient_evidence":
        trust_label = str(source_trust.get("label") or question.get("source_label") or "")
        item_source_fail = any(event.get("correct") is False and int(event.get("question_number") or 0) == int(question.get("question_number") or 0) for event in history)
        healthy_success = any(event.get("correct") and str(event.get("source_label") or "") not in {trust_label, "Source conflict", "Decayed"} for event in history)
        if item_source_fail and healthy_success and trust_label in {"Source conflict", "Decayed", "Low trust"}:
            diagnosis = "source_quality_problem"
            confidence = 0.66
            evidence = ["risky_source_failure", "healthier_source_success"]
    if confidence < minimum_confidence or diagnosis not in VALID_DIAGNOSES:
        diagnosis = "insufficient_evidence"
        confidence = 0.0
    action = {
        "missing_prerequisite": "repair_prerequisite_first",
        "target_concept_weakness": "repair_target_concept",
        "concept_confusion": "contrast_repair",
        "transfer_failure": "transfer_check",
        "item_specific_failure": "use_alternative_item",
        "source_quality_problem": "prefer_healthier_source",
        "insufficient_evidence": "collect_more_evidence",
    }[diagnosis]
    return _diagnosis(diagnosis, confidence, target_key, supporting, evidence, counter, action, diagnosed_at)


def _diagnosis(diagnosis, confidence, target_key, supporting, evidence, counter, action, diagnosed_at):
    return {
        "diagnosis": diagnosis,
        "confidence": round(float(confidence or 0.0), 4),
        "target_concept_key": target_key,
        "supporting_concept_keys": list(supporting or []),
        "evidence": list(evidence or []),
        "counterevidence": list(counter or []),
        "recommended_action": action,
        "policy_version": SMART_PRACTICE_POLICY_VERSION,
        "graph_version": GRAPH_VERSION,
        "diagnosed_at": diagnosed_at,
    }


def store_diagnosis(graph: Mapping[str, Any], diagnosis: Mapping[str, Any]) -> dict[str, Any]:
    clean = normalize_graph(graph)
    diag_id = stable_id(
        "diagnosis",
        diagnosis.get("target_concept_key"),
        diagnosis.get("diagnosis"),
        diagnosis.get("diagnosed_at"),
        diagnosis.get("evidence"),
    )
    row = dict(diagnosis)
    row["diagnosis_id"] = diag_id
    clean["diagnoses"][diag_id] = row
    clean["last_updated_at"] = str(diagnosis.get("diagnosed_at") or clean["last_updated_at"])
    clean["graph_signature"] = stable_id("graph", json.dumps(clean["concepts"], sort_keys=True, default=str), json.dumps(clean["edges"], sort_keys=True, default=str), json.dumps(clean["diagnoses"], sort_keys=True, default=str))
    return clean


def diagnosis_measurement(graph: Mapping[str, Any], history: list[Mapping[str, Any]]) -> dict[str, Any]:
    diagnoses = list((graph.get("diagnoses") or {}).values())
    by_type = Counter(str(row.get("diagnosis") or "insufficient_evidence") for row in diagnoses)
    observed = 0
    supported = 0
    for row in diagnoses:
        created = str(row.get("diagnosed_at") or "")
        later = [event for event in history if str(event.get("at") or "") > created]
        if not later:
            continue
        observed += 1
        diag = row.get("diagnosis")
        if diag == "missing_prerequisite" and any(event.get("repair_stage") in {"contrast", "transfer", "spaced_retrieval"} and event.get("correct") for event in later):
            supported += 1
        elif diag == "concept_confusion" and any(event.get("repair_stage") == "contrast" and event.get("correct") for event in later):
            supported += 1
        elif diag == "transfer_failure" and any(event.get("repair_stage") == "transfer" and event.get("correct") for event in later):
            supported += 1
        elif diag == "item_specific_failure" and any(event.get("correct") for event in later):
            supported += 1
        elif diag == "source_quality_problem" and any(event.get("correct") and str(event.get("source_label") or "") not in {"Source conflict", "Decayed"} for event in later):
            supported += 1
    total = max(1, len(diagnoses))
    return {
        "diagnosis_count_by_type": dict(by_type),
        "diagnosis_accuracy": "unobserved" if observed == 0 else round(supported / observed, 4),
        "prerequisite_repair_success": _rate(diagnoses, history, "missing_prerequisite", "contrast"),
        "confusion_repair_success": _rate(diagnoses, history, "concept_confusion", "contrast"),
        "transfer_failure_recovery": _rate(diagnoses, history, "transfer_failure", "transfer"),
        "item_specific_false_positive_rate": round(by_type.get("item_specific_failure", 0) / total, 4),
        "source_problem_confirmation_rate": _rate(diagnoses, history, "source_quality_problem", ""),
        "insufficient_evidence_rate": round(by_type.get("insufficient_evidence", 0) / total, 4),
    }


def _rate(diagnoses, history, diagnosis, repair_stage):
    rows = [row for row in diagnoses if row.get("diagnosis") == diagnosis]
    if not rows:
        return "unobserved"
    observed = 0
    success = 0
    for row in rows:
        later = [event for event in history if str(event.get("at") or "") > str(row.get("diagnosed_at") or "")]
        if not later:
            continue
        observed += 1
        if any(event.get("correct") and (not repair_stage or event.get("repair_stage") == repair_stage) for event in later):
            success += 1
    return "unobserved" if observed == 0 else round(success / observed, 4)
