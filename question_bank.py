import copy
import hashlib
import json
import random
import re
from functools import lru_cache
from pathlib import Path
from typing import cast

from bank_models import BankQuestion, QuestionBankData, as_bank_question

EMBEDDED_QUESTION_RE = re.compile(r"\bQUESTION\s+\d+\b")
INLINE_WHITESPACE_RE = re.compile(r"[ \t]+")
LINE_WHITESPACE_RE = re.compile(r" *\n *")
EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
MOJIBAKE_MARKERS = ("\u00e2", "\u00c3", "\u00c2")
PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u0091": "'",
        "\u0092": "'",
        "\u0093": '"',
        "\u0094": '"',
    }
)


def infer_source_name(question: BankQuestion, default_title: str = "Practice Test") -> str:
    source_name = sanitize_text(question.get("source_name", ""))
    if source_name:
        return source_name
    subtitle = str(question.get("subtitle", "") or "")
    chapter = str(question.get("chapter", "") or "")
    if "Free Study Guide A5" in subtitle or "Free Study Guide A5" in chapter:
        return "Free Study Guide A5"
    if "Pre-Assessment" in chapter or "Post-Assessment" in chapter or chapter.startswith("Chapter "):
        return "Free Study Guide A5"
    return (
        "Public SY0-701 Questions"
        if default_title.startswith("Public SY0-701")
        else (sanitize_text(default_title) or "Unknown source")
    )


def _repair_mojibake(text):
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text, False
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return text, False
    return repaired, repaired != text


@lru_cache(maxsize=32768)
def _sanitize_text_cached(text: str, trim_embedded_questions: bool) -> tuple[str, tuple[str, ...]]:
    notes: list[str] = []
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "", tuple()

    text, repaired = _repair_mojibake(text)
    if repaired:
        notes.append("encoding artifacts repaired")

    translated = text.translate(PUNCTUATION_TRANSLATION)
    punctuation_normalized = translated != text
    text = translated
    if punctuation_normalized and not repaired:
        notes.append("smart punctuation normalized")

    if trim_embedded_questions:
        match = EMBEDDED_QUESTION_RE.search(text)
        if match:
            text = text[: match.start()].rstrip()
            notes.append("embedded follow-on question removed")

    text = INLINE_WHITESPACE_RE.sub(" ", text)
    text = LINE_WHITESPACE_RE.sub("\n", text)
    text = EXCESS_BLANK_LINES_RE.sub("\n\n", text).strip()
    return text, tuple(notes)


def sanitize_text(value, trim_embedded_questions=False, collect_notes=False):
    text, notes = _sanitize_text_cached(str(value or ""), bool(trim_embedded_questions))
    if collect_notes:
        return text, list(notes)
    return text


def sanitize_explanation_text(value):
    return sanitize_text(value, trim_embedded_questions=True)


def load_bank(path: Path) -> QuestionBankData:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError("Question bank must be a JSON object with a 'questions' list.")
    questions = data.get("questions", [])
    if not questions:
        raise ValueError("Question bank contains no questions.")
    typed_questions: list[BankQuestion] = []
    for idx, raw_question in enumerate(questions, start=1):
        q = as_bank_question(raw_question)
        if "prompt" not in q or "choices" not in q or "correct" not in q:
            raise ValueError(f"Question {idx} is missing prompt, choices, or correct.")
        if not isinstance(q["choices"], dict) or not q["choices"]:
            raise ValueError(f"Question {idx} choices must be a non-empty object.")
        if isinstance(q["correct"], str):
            q["correct"] = [q["correct"]]
        if not isinstance(q["correct"], list):
            raise ValueError(f"Question {idx} correct answer must be a list or string.")
        for letter in q["correct"]:
            if letter not in q["choices"]:
                raise ValueError(f"Question {idx} correct answer '{letter}' must exist in choices.")

        q.setdefault("question_number", idx)
        q.setdefault("general_explanation", "")
        q.setdefault("choice_explanations", {})
        q.setdefault("domain", "Unsorted")
        q.setdefault("chapter", data.get("title", "Practice Test"))
        q.setdefault("question_type", "multi" if len(q["correct"]) > 1 else "single")
        q.setdefault("topics", [])
        q.setdefault("flagged_issues", [])
        q.setdefault("source_page", "")
        q.setdefault("source_name", "")
        q.setdefault("objective_code", "")
        q.setdefault("study_focus", "")
        q.setdefault("duplicate_of", None)

        q["prompt"] = sanitize_text(q.get("prompt", ""))
        q["choices"] = {key: sanitize_text(value) for key, value in q.get("choices", {}).items()}
        q["general_explanation"] = sanitize_explanation_text(q.get("general_explanation", ""))
        q["choice_explanations"] = {
            key: sanitize_explanation_text(value) for key, value in q.get("choice_explanations", {}).items()
        }
        q["domain"] = sanitize_text(q.get("domain", "Unsorted")) or "Unsorted"
        q["chapter"] = sanitize_text(q.get("chapter", data.get("title", "Practice Test"))) or data.get(
            "title", "Practice Test"
        )
        q["subtitle"] = sanitize_text(q.get("subtitle", ""))
        q["source_name"] = infer_source_name(q, data.get("title", "Practice Test"))
        q["objective_code"] = sanitize_text(q.get("objective_code", "") or q.get("objective", ""))
        q["study_focus"] = sanitize_explanation_text(q.get("study_focus", ""))
        duplicate_of = q.get("duplicate_of")
        if isinstance(duplicate_of, (list, tuple)):
            duplicate_of = next((value for value in duplicate_of if value not in (None, "")), None)
        q["duplicate_of"] = int(str(duplicate_of)) if duplicate_of not in (None, "") else None

        sanitized_topics = []
        for topic in q.get("topics", []):
            cleaned_topic = sanitize_text(topic)
            if cleaned_topic:
                sanitized_topics.append(cleaned_topic)
        q["topics"] = sanitized_topics

        sanitized_issues = []
        for issue in q.get("flagged_issues", []):
            cleaned_issue = sanitize_explanation_text(issue)
            if cleaned_issue:
                sanitized_issues.append(cleaned_issue)
        q["flagged_issues"] = sanitized_issues

        typed_questions.append(q)
    data["questions"] = typed_questions
    return cast(QuestionBankData, data)


def stable_shuffle_question(question: BankQuestion) -> BankQuestion:
    q = copy.deepcopy(question)
    letters = [letter for letter in ["A", "B", "C", "D", "E", "F"] if q["choices"].get(letter)]
    if len(q.get("correct", [])) > 1:
        q["choice_order"] = letters
        return q
    seed_src = f"{q.get('question_number')}::{q.get('prompt', '')[:80]}"
    rng = random.Random(int(hashlib.md5(seed_src.encode("utf-8")).hexdigest(), 16))
    shuffled = letters[:]
    rng.shuffle(shuffled)
    mapping = {old: new for old, new in zip(letters, shuffled, strict=False)}
    q["choices"] = {mapping[k]: v for k, v in q["choices"].items() if k in mapping}
    q["choice_explanations"] = {mapping.get(k, k): v for k, v in q.get("choice_explanations", {}).items()}
    q["correct"] = sorted(mapping[k] for k in q["correct"])
    q["choice_order"] = shuffled
    return q


def adaptive_shuffle_question(question: BankQuestion, seed_src) -> BankQuestion:
    q = copy.deepcopy(question)
    letters = [letter for letter in ["A", "B", "C", "D", "E", "F"] if q["choices"].get(letter)]
    if len(q.get("correct", [])) > 1 or len(letters) <= 1:
        q["choice_order"] = letters
        return q
    rng = random.Random(int(hashlib.md5(str(seed_src).encode("utf-8")).hexdigest(), 16))
    shuffled = letters[:]
    rng.shuffle(shuffled)
    mapping = {old: new for old, new in zip(letters, shuffled, strict=False)}
    q["choices"] = {mapping[k]: v for k, v in q["choices"].items() if k in mapping}
    q["choice_explanations"] = {mapping.get(k, k): v for k, v in q.get("choice_explanations", {}).items()}
    q["correct"] = sorted(mapping[k] for k in q["correct"])
    q["choice_order"] = shuffled
    return q
