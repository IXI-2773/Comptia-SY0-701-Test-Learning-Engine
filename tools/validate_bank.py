from collections import Counter
import difflib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from question_bank import load_bank, sanitize_text


BASE_DIR = ROOT
DEFAULT_BANK = BASE_DIR / "public_sy0701_bank_v4.json"
REPORT_DIR = BASE_DIR / "reports"
REPORT_PATH = REPORT_DIR / "bank_validation_report.md"


def normalize_text(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def choice_signature(question):
    return tuple(
        normalize_text(question.get("choices", {}).get(letter, ""))
        for letter in sorted(question.get("choices", {}))
        if str(question.get("choices", {}).get(letter, "")).strip()
    )


def prompt_quality_notes(question):
    prompt = str(question.get("prompt", "")).strip()
    normalized = normalize_text(prompt)
    words = [word for word in normalized.split() if word]
    notes = []
    if prompt and len(prompt) < 28:
        notes.append("prompt is very short")
    if prompt and len(words) < 5:
        notes.append("prompt has very few words")
    if prompt and prompt[-1] not in ("?", ":") and len(words) < 8:
        notes.append("prompt reads like a fragment")
    return notes


def is_active_fragment_prompt(question, quality_notes):
    return (
        not bool(question.get("suspended"))
        and not is_quarantined_review_item(question)
        and "prompt reads like a fragment" in quality_notes
    )


def is_quarantined_review_item(question):
    return question.get("suspended") and question.get("import_status") == "screenshot_review_needed"


def validate_bank(path: Path = DEFAULT_BANK):
    issues = []
    warnings = []
    with open(path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    raw_questions = list(raw_data.get("questions", [])) if isinstance(raw_data, dict) else []
    data = load_bank(path)
    questions = data["questions"]
    raw_by_qnum = {}
    for idx, raw_q in enumerate(raw_questions, start=1):
        qnum = raw_q.get("question_number", idx)
        raw_by_qnum[qnum] = raw_q
    normalized = []
    for q in questions:
        prompt_key = normalize_text(q.get("prompt", ""))
        if is_quarantined_review_item(q):
            prompt_key = f"screenshot-review-placeholder-{q.get('question_number')}"
        normalized.append(
            {
                "question": q,
                "prompt_key": prompt_key,
                "choice_signature": choice_signature(q),
            }
        )
    normalized_by_qid = {id(item["question"]): item for item in normalized}
    qnums = [q.get("question_number") for q in questions]
    duplicates = [qnum for qnum, count in Counter(qnums).items() if count > 1]
    if duplicates:
        issues.append(("Duplicate question numbers", ", ".join(map(str, duplicates))))

    prompt_groups = {}
    answer_letters = Counter()
    missing_general = []
    missing_choice = []
    low_quality_prompts = []
    answer_pattern_streaks = []
    text_cleanup_artifacts = []
    explanation_anomalies = []
    choice_explanation_mismatches = []

    for item in normalized:
        q = item["question"]
        qnum = q.get("question_number")
        prompt_key = item["prompt_key"]
        raw_q = raw_by_qnum.get(qnum, {})
        prompt_groups.setdefault(prompt_key, []).append(q)
        if not str(q.get("prompt", "")).strip():
            issues.append((f"Q{qnum}", "Prompt is empty."))
        if not str(q.get("general_explanation", "")).strip():
            issues.append((f"Q{qnum}", "General explanation is empty."))
            missing_general.append(qnum)
        if not q.get("topics"):
            issues.append((f"Q{qnum}", "Topics list is empty."))
        if is_quarantined_review_item(q):
            continue
        quality_notes = prompt_quality_notes(q)
        if quality_notes:
            low_quality_prompts.append((qnum, "; ".join(quality_notes)))
        if is_active_fragment_prompt(q, quality_notes):
            warnings.append((f"Q{qnum}", "Active question prompt appears fragmentary and needs correction."))
        if len(set(item["choice_signature"])) != len(item["choice_signature"]):
            warnings.append((f"Q{qnum}", "Two or more choices normalize to the same text."))
        if q.get("question_type") == "single" and len(q.get("correct", [])) == 1:
            answer_letters[q["correct"][0]] += 1
        artifact_notes = []
        for field_name, raw_value, trim in (
            ("prompt", raw_q.get("prompt", ""), False),
            ("general explanation", raw_q.get("general_explanation", ""), True),
        ):
            _cleaned, notes = sanitize_text(raw_value, trim_embedded_questions=trim, collect_notes=True)
            artifact_notes.extend(f"{field_name}: {note}" for note in notes)
        for letter, raw_value in (raw_q.get("choices") or {}).items():
            _cleaned, notes = sanitize_text(raw_value, collect_notes=True)
            artifact_notes.extend(f"choice {letter}: {note}" for note in notes)
        for letter, raw_value in (raw_q.get("choice_explanations") or {}).items():
            _cleaned, notes = sanitize_text(raw_value, trim_embedded_questions=True, collect_notes=True)
            artifact_notes.extend(f"choice {letter} explanation: {note}" for note in notes)

        raw_general = str(raw_q.get("general_explanation", "") or "").strip()
        if re.search(r"\bQUESTION\s+\d+\b", raw_general):
            explanation_anomalies.append((qnum, "general explanation contains an embedded follow-on question"))
            artifact_notes.append("general explanation contains an embedded follow-on question")
        if len(raw_general) >= 900:
            explanation_anomalies.append((qnum, "general explanation is unusually long"))
            artifact_notes.append("general explanation is unusually long")
        if raw_general.count("Answer:") > 1 or raw_general.count("Explanation:") > 1:
            explanation_anomalies.append(
                (qnum, "general explanation contains multiple embedded answer/explanation blocks")
            )
            artifact_notes.append("general explanation contains multiple embedded answer blocks")
        if artifact_notes:
            compact_notes = list(dict.fromkeys(artifact_notes))
            text_cleanup_artifacts.append((qnum, compact_notes))
            warnings.append((f"Q{qnum}", "; ".join(compact_notes[:4])))

        for letter, text in q.get("choices", {}).items():
            if not str(text).strip():
                issues.append((f"Q{qnum}", f"Choice {letter} is empty."))
            choice_explanation = str(q.get("choice_explanations", {}).get(letter, "") or "").strip()
            if letter not in q.get("choice_explanations", {}) or not choice_explanation:
                issues.append((f"Q{qnum}", f"Choice {letter} explanation is empty."))
                missing_choice.append((qnum, letter))
                continue
            explanation_lower = choice_explanation.lower()
            is_correct_letter = letter in q.get("correct", [])
            if is_correct_letter and explanation_lower.startswith("not keyed as correct"):
                choice_explanation_mismatches.append(
                    (qnum, letter, "correct choice explanation is marked as incorrect")
                )
                warnings.append((f"Q{qnum}", f"Choice {letter} explanation conflicts with the keyed answer."))
            if not is_correct_letter and explanation_lower.startswith("correct option"):
                choice_explanation_mismatches.append(
                    (qnum, letter, "incorrect choice explanation is marked as correct")
                )
                warnings.append((f"Q{qnum}", f"Choice {letter} explanation conflicts with the keyed answer."))

    duplicate_candidates = []
    conflict_groups = []
    repeated_prompt_groups = []
    prompt_items = [
        (key, group[0].get("question_number"), group[0].get("prompt", ""))
        for key, group in prompt_groups.items()
        if key
    ]
    prompt_buckets = {}
    for key, qnum, prompt in prompt_items:
        bucket_key = " ".join(key.split()[:6])
        prompt_buckets.setdefault(bucket_key, []).append((key, qnum, prompt))
    for key, group in prompt_groups.items():
        if len(group) <= 1:
            continue
        qnum_list = [q.get("question_number") for q in group]
        correct_sets = {tuple(sorted(q.get("correct", []))) for q in group}
        choice_sets = {normalized_by_qid[id(q)]["choice_signature"] for q in group}
        if len(correct_sets) > 1:
            conflict_groups.append(qnum_list)
            issues.append(
                (
                    "Conflicting keyed answers",
                    f"Questions {', '.join(map(str, qnum_list))} share the same normalized prompt but different correct answers.",
                )
            )
        elif len(choice_sets) == 1:
            repeated_prompt_groups.append(qnum_list)
            warnings.append(
                (
                    "Repeated question prompt",
                    f"Questions {', '.join(map(str, qnum_list))} share the same normalized prompt and choices.",
                )
            )
        else:
            warnings.append(
                (
                    "Repeated question prompt",
                    f"Questions {', '.join(map(str, qnum_list))} share the same normalized prompt.",
                )
            )

    for bucket in prompt_buckets.values():
        if len(bucket) <= 1:
            continue
        for idx, (left_key, left_qnum, _left_prompt) in enumerate(bucket):
            for right_key, right_qnum, _right_prompt in bucket[idx + 1 :]:
                if left_key == right_key:
                    continue
                if abs(len(left_key) - len(right_key)) > 20:
                    continue
                ratio = difflib.SequenceMatcher(a=left_key, b=right_key).ratio()
                if ratio < 0.965:
                    continue
                duplicate_candidates.append((left_qnum, right_qnum, ratio))
                if len(duplicate_candidates) >= 10:
                    break
            if len(duplicate_candidates) >= 10:
                break
        if len(duplicate_candidates) >= 10:
            break

    if duplicate_candidates:
        warnings.append(
            (
                "Near-duplicate prompts",
                "; ".join([f"Q{left}/Q{right} ({ratio:.2f})" for left, right, ratio in duplicate_candidates]),
            )
        )

    total_single = sum(answer_letters.values())
    if total_single:
        dominant_letter, dominant_count = answer_letters.most_common(1)[0]
        dominant_ratio = dominant_count / total_single
        if dominant_ratio >= 0.55:
            warnings.append(
                (
                    "Suspicious answer distribution",
                    f"Single-answer key {dominant_letter} appears {dominant_count}/{total_single} times ({dominant_ratio:.1%}).",
                )
            )
        single_answer_sequence = [
            (q.get("question_number"), q["correct"][0])
            for q in questions
            if q.get("question_type") == "single"
            and len(q.get("correct", [])) == 1
            and not is_quarantined_review_item(q)
        ]
        streak_letter = None
        streak_qnums = []
        longest_streak = []
        longest_letter = None
        for qnum, letter in single_answer_sequence:
            if letter == streak_letter:
                streak_qnums.append(qnum)
            else:
                streak_letter = letter
                streak_qnums = [qnum]
            if len(streak_qnums) > len(longest_streak):
                longest_streak = list(streak_qnums)
                longest_letter = letter
        if len(longest_streak) >= 6:
            answer_pattern_streaks.append(
                f"{longest_letter} streak on Q{longest_streak[0]}-Q{longest_streak[-1]} ({len(longest_streak)} in a row)"
            )
            warnings.append(
                (
                    "Repeated answer-pattern bias",
                    answer_pattern_streaks[0],
                )
            )

    return {
        "bank_file": path.name,
        "question_count": len(questions),
        "domain_count": len({q.get("domain", "Unsorted") for q in questions}),
        "topic_count": len({str(t).strip() for q in questions for t in q.get("topics", []) if str(t).strip()}),
        "issues": issues,
        "warnings": warnings,
        "lint": {
            "missing_explanations": {
                "general_count": len(missing_general),
                "general_examples": missing_general[:10],
                "choice_count": len(missing_choice),
                "choice_examples": [f"Q{qnum}{letter}" for qnum, letter in missing_choice[:12]],
            },
            "suspicious_duplicates": {
                "repeated_prompt_groups": [list(group) for group in repeated_prompt_groups[:10]],
                "near_duplicate_pairs": [
                    f"Q{left}/Q{right} ({ratio:.2f})" for left, right, ratio in duplicate_candidates[:10]
                ],
                "conflicting_groups": [list(group) for group in conflict_groups[:10]],
            },
            "short_or_low_quality_prompts": {
                "count": len(low_quality_prompts),
                "examples": [f"Q{qnum}: {note}" for qnum, note in low_quality_prompts[:12]],
            },
            "text_cleanup_artifacts": {
                "count": len(text_cleanup_artifacts),
                "examples": [f"Q{qnum}: {'; '.join(notes[:3])}" for qnum, notes in text_cleanup_artifacts[:12]],
            },
            "explanation_anomalies": {
                "count": len(explanation_anomalies),
                "examples": [f"Q{qnum}: {note}" for qnum, note in explanation_anomalies[:12]],
            },
            "choice_explanation_mismatches": {
                "count": len(choice_explanation_mismatches),
                "examples": [f"Q{qnum}{letter}: {note}" for qnum, letter, note in choice_explanation_mismatches[:12]],
            },
            "repeated_answer_pattern_bias": {
                "distribution": dict(answer_letters),
                "longest_streaks": answer_pattern_streaks[:5],
            },
        },
    }


def write_markdown_report(result, path: Path = REPORT_PATH):
    REPORT_DIR.mkdir(exist_ok=True)
    lines = [
        "# Bank Validation Report",
        "",
        f"- Bank file: `{result['bank_file']}`",
        f"- Questions: **{result['question_count']}**",
        f"- Domains: **{result['domain_count']}**",
        f"- Topics: **{result['topic_count']}**",
        f"- Issues: **{len(result['issues'])}**",
        f"- Warnings: **{len(result.get('warnings', []))}**",
        "",
    ]
    if result["issues"]:
        lines.append("## Issues")
        lines.append("")
        for title, body in result["issues"]:
            lines.append(f"- **{title}**: {body}")
        lines.append("")
    if result.get("warnings"):
        lines.append("## Warnings")
        lines.append("")
        for title, body in result["warnings"]:
            lines.append(f"- **{title}**: {body}")
        lines.append("")
    lint = result.get("lint") or {}
    if lint:
        lines.append("## Lint Report")
        lines.append("")
        missing = lint.get("missing_explanations", {})
        lines.append(f"- Missing general explanations: **{missing.get('general_count', 0)}**")
        if missing.get("general_examples"):
            lines.append(f"  Examples: {', '.join('Q' + str(qnum) for qnum in missing['general_examples'])}")
        lines.append(f"- Missing choice explanations: **{missing.get('choice_count', 0)}**")
        if missing.get("choice_examples"):
            lines.append(f"  Examples: {', '.join(missing['choice_examples'])}")
        dupes = lint.get("suspicious_duplicates", {})
        repeated_groups = dupes.get("repeated_prompt_groups", [])
        near_pairs = dupes.get("near_duplicate_pairs", [])
        conflict_groups = dupes.get("conflicting_groups", [])
        lines.append(
            f"- Suspicious duplicate groups: **{len(repeated_groups) + len(near_pairs) + len(conflict_groups)}**"
        )
        if repeated_groups:
            lines.append(
                f"  Repeated prompt groups: {', '.join('[' + ', '.join('Q' + str(qnum) for qnum in group) + ']' for group in repeated_groups[:5])}"
            )
        if near_pairs:
            lines.append(f"  Near-duplicate pairs: {', '.join(near_pairs[:5])}")
        if conflict_groups:
            lines.append(
                f"  Conflicting prompt groups: {', '.join('[' + ', '.join('Q' + str(qnum) for qnum in group) + ']' for group in conflict_groups[:5])}"
            )
        prompts = lint.get("short_or_low_quality_prompts", {})
        lines.append(f"- Short or low-quality prompts: **{prompts.get('count', 0)}**")
        if prompts.get("examples"):
            lines.append(f"  Examples: {', '.join(prompts['examples'][:6])}")
        cleanup = lint.get("text_cleanup_artifacts", {})
        lines.append(f"- Text cleanup artifacts: **{cleanup.get('count', 0)}**")
        if cleanup.get("examples"):
            lines.append(f"  Examples: {', '.join(cleanup['examples'][:6])}")
        anomalies = lint.get("explanation_anomalies", {})
        lines.append(f"- Explanation anomalies: **{anomalies.get('count', 0)}**")
        if anomalies.get("examples"):
            lines.append(f"  Examples: {', '.join(anomalies['examples'][:6])}")
        mismatches = lint.get("choice_explanation_mismatches", {})
        lines.append(f"- Choice explanation mismatches: **{mismatches.get('count', 0)}**")
        if mismatches.get("examples"):
            lines.append(f"  Examples: {', '.join(mismatches['examples'][:6])}")
        patterns = lint.get("repeated_answer_pattern_bias", {})
        lines.append(f"- Answer-pattern distribution: `{json.dumps(patterns.get('distribution', {}), sort_keys=True)}`")
        if patterns.get("longest_streaks"):
            lines.append(f"  Longest streaks: {', '.join(patterns['longest_streaks'][:5])}")
    else:
        if not result["issues"]:
            lines.append("No validation issues found.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    bank_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BANK
    result = validate_bank(bank_path)
    report = write_markdown_report(result)
    print(f"Validated {result['question_count']} questions.")
    print(f"Issues found: {len(result['issues'])}")
    print(f"Warnings found: {len(result.get('warnings', []))}")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
