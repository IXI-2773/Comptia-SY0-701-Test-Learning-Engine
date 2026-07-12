from __future__ import annotations

import re
from typing import Any

from question_bank import sanitize_text


def normalized_study_label(value: str) -> str:
    text = " ".join(str(value or "").replace("&", "and").replace(",", " ").split()).casefold()
    aliases = {
        "security program management and oversight": "security program management and oversight",
        "threats vulnerabilities and mitigations": "threats vulnerabilities and mitigations",
        "threats vulnerability and mitigations": "threats vulnerabilities and mitigations",
    }
    return aliases.get(text, text)


def primary_topic_label(question: dict[str, Any]) -> str:
    topics = tuple(str(topic).strip() for topic in question.get("topics", []) if str(topic).strip())
    domain = str(question.get("domain") or "Unsorted")
    if topics:
        return normalized_study_label(topics[0])
    return normalized_study_label(domain)


def coverage_unit_for_question(question: dict[str, Any]) -> tuple[str, str]:
    objective_code = str(question.get("objective_code") or "").strip()
    if objective_code:
        return ("Objective", objective_code)
    topic = primary_topic_label(question)
    if topic and topic != "Unsorted":
        return ("Topic", topic)
    return ("Domain", normalized_study_label(str(question.get("domain") or "Unsorted")))


def stem_style_for_question(question: dict[str, Any]) -> str:
    prompt = sanitize_text(str(question.get("prompt") or "")).lower()
    if not prompt:
        return "General"
    if re.search(r"\b(except|least|not)\b", prompt):
        return "Exception"
    if re.search(r"\b(best|most|primary)\b", prompt):
        return "Best fit"
    if re.search(r"\b(first|next|initial|immediate)\b", prompt):
        return "Order"
    if re.search(r"\b(root cause|likely|why|cause|diagnos|issue|failure|problem)\b", prompt):
        return "Troubleshooting"
    if re.search(r"^(what|which)\s", prompt) and re.search(
        r"\b(defines?|describes?|term|acronym|stands for|known as)\b", prompt
    ):
        return "Definition"
    if len(prompt.split()) >= 22 or re.search(r"\b(should|implement|use|respond|handle|mitigate)\b", prompt):
        return "Scenario"
    return "General"


def question_mentions_label(question: dict[str, Any], label: str) -> bool:
    needle = str(label or "").strip()
    if not needle:
        return False
    haystack = " ".join(
        [str(question.get("prompt") or "")] + [str(text or "") for text in (question.get("choices") or {}).values()]
    )
    if needle.isupper() and len(needle) <= 8:
        return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
    return needle.lower() in haystack.lower()
