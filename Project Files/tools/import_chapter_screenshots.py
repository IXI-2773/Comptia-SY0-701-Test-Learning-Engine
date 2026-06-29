import argparse
import asyncio
import difflib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from question_bank import sanitize_text  # noqa: E402
from storage_utils import safe_write_json  # noqa: E402

DEFAULT_SOURCE_FOLDER = Path(r"C:\Users\14422\Downloads\Ch_1_Domain_1.0_General_Security_Concepts")
DEFAULT_BANK_PATH = ROOT / "public_sy0701_bank_v4_plus_studyguide_clean.json"
DEFAULT_REVIEW_PATH = ROOT / "reports" / "chapter1_screenshot_import_review.json"
DEFAULT_IMPORT_PATH = ROOT / "chapter1_screenshot_import_bank.json"
DEFAULT_MERGED_PATH = ROOT / "public_sy0701_bank_v4_plus_chapter1_screenshots_reviewed.json"
DEFAULT_DRAFT_PATH = ROOT / "chapter_screenshot_ocr_draft_bank.json"

DEFAULT_CHAPTER = "Chapter 1"
DEFAULT_DOMAIN = "General Security Concepts"
DEFAULT_DOMAIN_CODE = "1.0"
DEFAULT_TOPIC = "General Review"
QUESTION_NUMBER_RE = re.compile(r"Question\s+(\d+)", re.IGNORECASE)
CHAPTER_RE = re.compile(r"(?:Ch|Chapter)[_\s-]*(\d+)", re.IGNORECASE)
DOMAIN_RE = re.compile(r"Domain[_\s-]*(\d+(?:\.\d+)?)", re.IGNORECASE)
CHOICE_MARKER_RE = re.compile(r"(?:^|\s|[(@])([A-D])[\).]?\s+")
RADIO_CHOICE_MARKER_RE = re.compile(r"(?:^|\s)(?:[O0@]|C\))\s*([A-D8])[\).]?\s*", re.IGNORECASE)
ANSWER_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "in",
    "is",
    "it",
    "of",
    "or",
    "the",
    "to",
    "with",
}


def parse_source_question_number(path: str | Path) -> int | None:
    match = QUESTION_NUMBER_RE.search(Path(path).name)
    return int(match.group(1)) if match else None


def ocr_is_available() -> bool:
    if not shutil.which("tesseract"):
        try:
            from winrt.windows.media.ocr import OcrEngine

            return OcrEngine.try_create_from_user_profile_languages() is not None
        except Exception:
            return False
    try:
        import pytesseract  # noqa: F401

        return True
    except ImportError:
        pass
    return False


async def _extract_windows_ocr_text(path: Path) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return ""
    file = await StorageFile.get_file_from_path_async(str(path))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return str(result.text or "")


def extract_ocr_text(path: str | Path) -> str:
    path = Path(path)
    if shutil.which("tesseract"):
        try:
            import pytesseract

            with Image.open(path) as image:
                return str(pytesseract.image_to_string(image) or "")
        except Exception:
            pass
    try:
        return asyncio.run(_extract_windows_ocr_text(path))
    except Exception:
        return ""


def screenshot_files(source_folder: str | Path = DEFAULT_SOURCE_FOLDER) -> list[Path]:
    return sorted(Path(source_folder).glob("*.png"), key=lambda path: path.name.lower())


def _title_from_slug(value: str) -> str:
    cleaned = re.sub(r"[_-]+", " ", value).strip()
    return " ".join(part.capitalize() if not part.isupper() else part for part in cleaned.split())


def infer_metadata_from_source_folder(source_folder: str | Path) -> dict[str, str]:
    name = Path(source_folder).name
    chapter_match = CHAPTER_RE.search(name)
    domain_match = DOMAIN_RE.search(name)
    domain_code = domain_match.group(1) if domain_match else DEFAULT_DOMAIN_CODE
    chapter_number = chapter_match.group(1) if chapter_match else "1"
    domain_tail = ""
    if domain_match:
        domain_tail = name[domain_match.end() :]
    if not domain_tail:
        domain_tail = DEFAULT_DOMAIN
    domain = _title_from_slug(domain_tail) or DEFAULT_DOMAIN
    chapter = f"Chapter {chapter_number}"
    return {
        "chapter": chapter,
        "domain": domain,
        "domain_code": domain_code,
        "topic": "General Review",
        "subtitle": f"{chapter} screenshot bank - Domain {domain_code}",
        "source_label": f"{chapter} screenshot bank",
    }


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _normalize_for_match(value: Any) -> str:
    text = sanitize_text(str(value or "")).lower()
    text = re.sub(r"\b8\s*pa\b", "bpa", text)
    text = re.sub(r"\b81a\b", "bia", text)
    text = re.sub(r"\b8\b", "b", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _question_match_text(question: dict[str, Any]) -> str:
    choices = question.get("choices") or {}
    choice_text = " ".join(str(choices.get(letter, "")) for letter in sorted(choices))
    return _normalize_for_match(f"{question.get('prompt', '')} {choice_text}")


def _strip_ocr_chrome(text: str) -> str:
    text = re.sub(r"Chapter\s+\d+:\s*Domain\s+\d+(?:\.\d+)?:\s*[^?]+?(?=\s+(?:Correct|Incorrect|[A-Z][a-z]))", "", text)
    text = re.sub(r"\bQUESTION\s+\d+\s*of\s*\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCONTENT FEEDBACK\b|\bPREVIOUS\b|\bNEXT\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _clean_ocr_prompt(prompt: str) -> str:
    prompt = re.sub(r"^Overall Time Spent:\s*\S+\s+", "", str(prompt or "").strip(), flags=re.IGNORECASE)
    prompt = re.sub(r"^(?:General\s+)?Security Concepts\s+", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"^Security Operations\s+", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"^Architecture\s+", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"^[O0]?\s*(Correct|Incorrect)\s+", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"^.*?\b[O0]?\s*(Correct|Incorrect)\s+", "", prompt, count=1, flags=re.IGNORECASE)
    return sanitize_text(prompt)


def _split_choice_segments(text: str) -> list[tuple[str, str]]:
    text = re.sub(r"\b([A-D8])\.(?=\S)", r"\1. ", text, flags=re.IGNORECASE)
    text = RADIO_CHOICE_MARKER_RE.sub(
        lambda match: f" {'B' if match.group(1).upper() == '8' else match.group(1).upper()}. ",
        text,
    )
    matches = list(CHOICE_MARKER_RE.finditer(text))
    segments = []
    for idx, match in enumerate(matches):
        letter = match.group(1).upper()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[start:end].strip(" :;,-")
        if value:
            segments.append((letter, value))
    return segments


def _meaningful_tokens(value: str) -> set[str]:
    normalized = _normalize_for_match(value)
    return {token for token in normalized.split() if len(token) >= 3 and token not in ANSWER_STOPWORDS}


def _infer_correct_from_explanation(choices: dict[str, str], explanation: str) -> list[str]:
    if not choices or not explanation:
        return []
    evidence = explanation
    evidence_normalized = _normalize_for_match(evidence)
    evidence_words = evidence_normalized.split()
    token_frequency: dict[str, int] = {}
    choice_tokens = {letter: _meaningful_tokens(value) for letter, value in choices.items()}
    for tokens in choice_tokens.values():
        for token in tokens:
            token_frequency[token] = token_frequency.get(token, 0) + 1
    ranked: list[tuple[float, str]] = []
    for letter, value in choices.items():
        tokens = {token for token in choice_tokens[letter] if token_frequency.get(token, 0) == 1}
        if not tokens:
            tokens = choice_tokens[letter]
        if not tokens:
            continue
        phrase_position = _choice_match_position(value, evidence)
        token_positions = []
        fuzzy_hits = 0
        for token in tokens:
            token_match = re.search(rf"\b{re.escape(token)}\b", evidence_normalized)
            if token_match:
                token_positions.append(token_match.start())
                fuzzy_hits += 1
                continue
            for idx, word in enumerate(evidence_words):
                if abs(len(word) - len(token)) <= 3 and difflib.SequenceMatcher(None, token, word).ratio() >= 0.78:
                    token_positions.append(len(" ".join(evidence_words[:idx])))
                    fuzzy_hits += 1
                    break
        earliest = min(([phrase_position] if phrase_position is not None else []) + token_positions, default=None)
        score = fuzzy_hits / max(len(tokens), 1)
        if phrase_position is not None:
            score += 2.0
        if earliest is not None:
            score += max(0.0, 3.0 - min(earliest, 600) / 200)
        if score > 0 and earliest is not None:
            ranked.append((score, letter))
    ranked.sort(reverse=True)
    if not ranked:
        return []
    if len(ranked) == 1 or ranked[0][0] >= ranked[1][0] + 0.05:
        return [ranked[0][1]]
    return []


def _choice_match_position(choice: str, explanation: str) -> int | None:
    normalized_choice = _normalize_for_match(choice)
    normalized_explanation = _normalize_for_match(explanation)
    if not normalized_choice or not normalized_explanation:
        return None
    positions = []
    direct = normalized_explanation.find(normalized_choice)
    if direct >= 0:
        positions.append(direct)
    tokens = normalized_choice.split()
    if tokens:
        first_token = tokens[0]
        if len(first_token) >= 3:
            match = re.search(rf"\b{re.escape(first_token)}\b", normalized_explanation)
            if match:
                positions.append(match.start())
    return min(positions) if positions else None


def parse_ocr_draft(text: str) -> dict[str, Any]:
    cleaned = _strip_ocr_chrome(text)
    explanation = ""
    before_explanation = cleaned
    if re.search(r"\bExplanation\b", cleaned, flags=re.IGNORECASE):
        before_explanation, explanation = re.split(r"\bExplanation\b", cleaned, maxsplit=1, flags=re.IGNORECASE)
    before_explanation = re.sub(r"^\s*(Correct|Incorrect)\b", "", before_explanation, flags=re.IGNORECASE).strip()
    choice_segments = _split_choice_segments(before_explanation)
    choices = {letter: sanitize_text(value) for letter, value in choice_segments if letter in "ABCD"}
    prompt = before_explanation
    if choice_segments:
        first_match = CHOICE_MARKER_RE.search(before_explanation)
        if first_match:
            prompt = before_explanation[: first_match.start()].strip()
    prompt = _clean_ocr_prompt(prompt)
    explanation = sanitize_text(explanation, trim_embedded_questions=True)
    correct = []
    first_explanation_sentence = re.split(r"(?<=[.!?])\s+", explanation, maxsplit=1)[0] if explanation else ""
    if first_explanation_sentence and choices:
        ranked: list[tuple[int, str]] = []
        for letter, value in choices.items():
            position = _choice_match_position(value, first_explanation_sentence)
            if position is not None:
                ranked.append((position, letter))
        ranked.sort()
        if ranked and (len(ranked) == 1 or ranked[1][0] - ranked[0][0] >= 3):
            correct = [ranked[0][1]]
    if not correct:
        correct = _infer_correct_from_explanation(choices, explanation)
    return {
        "prompt": prompt,
        "choices": choices,
        "correct": correct,
        "general_explanation": explanation,
        "parse_warnings": [
            warning
            for warning, missing in (
                ("missing prompt", not sanitize_text(prompt)),
                ("missing four choices", len(choices) != 4),
                ("missing inferred correct answer", not correct),
                ("missing explanation", not explanation),
            )
            if missing
        ],
    }


def build_review_manifest(
    source_folder: str | Path = DEFAULT_SOURCE_FOLDER,
    output_path: str | Path = DEFAULT_REVIEW_PATH,
    *,
    expected_count: int | None = 31,
    metadata: dict[str, str] | None = None,
    extract_ocr: bool = False,
) -> dict[str, Any]:
    files = screenshot_files(source_folder)
    ocr_ready = ocr_is_available()
    metadata = metadata or infer_metadata_from_source_folder(source_folder)
    screenshots = []
    for path in files:
        width, height = _image_size(path)
        ocr_text = extract_ocr_text(path) if extract_ocr and ocr_ready else ""
        draft = parse_ocr_draft(ocr_text) if ocr_text else {}
        parse_warnings = list(draft.get("parse_warnings", []))
        status = "ocr_draft" if draft and not parse_warnings else ("needs_review" if ocr_ready else "needs_ocr_setup")
        screenshots.append(
            {
                "filename": path.name,
                "path": str(path),
                "source_question_number": parse_source_question_number(path),
                "image_width": width,
                "image_height": height,
                "domain": metadata["domain"],
                "chapter": metadata["chapter"],
                "topic": metadata["topic"],
                "domain_code": metadata["domain_code"],
                "source_label": metadata["source_label"],
                "status": status,
                "ocr_available": ocr_ready,
                "ocr_text": ocr_text,
                "prompt": draft.get("prompt", ""),
                "choices": draft.get("choices", {}),
                "correct": draft.get("correct", []),
                "general_explanation": draft.get("general_explanation", ""),
                "parse_warnings": parse_warnings,
                "review_notes": (
                    "OCR is not available on this machine; verify/transcribe before merging."
                    if not ocr_ready
                    else "OCR draft requires human verification before merging."
                ),
            }
        )
    manifest = {
        "source_folder": str(Path(source_folder)),
        "expected_count": expected_count,
        "found_count": len(files),
        "ocr_available": ocr_ready,
        "ready_to_merge_count": sum(1 for row in screenshots if row["status"] == "verified"),
        "ocr_draft_count": sum(1 for row in screenshots if row["status"] == "ocr_draft"),
        "metadata": metadata,
        "screenshots": screenshots,
    }
    safe_write_json(Path(output_path), manifest)
    return manifest


def _validate_verified_record(record: dict[str, Any]) -> list[str]:
    errors = []
    choices = record.get("choices") or {}
    correct = [str(letter).strip().upper() for letter in record.get("correct", []) if str(letter).strip()]
    if not str(record.get("prompt", "")).strip():
        errors.append("missing prompt")
    for letter in ("A", "B", "C", "D"):
        if not str(choices.get(letter, "")).strip():
            errors.append(f"missing choice {letter}")
    if not correct:
        errors.append("missing correct answer")
    if any(letter not in choices for letter in correct):
        errors.append("correct answer is not present in choices")
    if not str(record.get("general_explanation", "")).strip():
        errors.append("missing explanation")
    return errors


def _metadata_from_record(record: dict[str, Any]) -> dict[str, str]:
    metadata = {
        "chapter": str(record.get("chapter") or DEFAULT_CHAPTER),
        "domain": str(record.get("domain") or DEFAULT_DOMAIN),
        "domain_code": str(record.get("domain_code") or DEFAULT_DOMAIN_CODE),
        "topic": str(record.get("topic") or DEFAULT_TOPIC),
    }
    metadata["subtitle"] = str(
        record.get("subtitle") or f"{metadata['chapter']} screenshot bank - Domain {metadata['domain_code']}"
    )
    metadata["source_label"] = str(record.get("source_label") or f"{metadata['chapter']} screenshot bank")
    return metadata


def build_question_from_verified_record(record: dict[str, Any], question_number: int) -> dict[str, Any]:
    choices = {
        letter: sanitize_text(str((record.get("choices") or {}).get(letter, ""))) for letter in ("A", "B", "C", "D")
    }
    correct = [str(letter).strip().upper() for letter in record.get("correct", []) if str(letter).strip()]
    metadata = _metadata_from_record(record)
    return {
        "question_number": int(question_number),
        "source_question_number": record.get("source_question_number"),
        "source_image": record.get("filename") or Path(str(record.get("path", ""))).name,
        "source_label": metadata["source_label"],
        "source_page": record.get("source_question_number") or "",
        "prompt": sanitize_text(str(record.get("prompt", ""))),
        "choices": choices,
        "correct": correct,
        "question_type": "multiple" if len(correct) > 1 else "single",
        "general_explanation": sanitize_text(str(record.get("general_explanation", "")), trim_embedded_questions=True),
        "choice_explanations": {
            letter: (
                f"Correct answer from verified {metadata['chapter']} screenshot."
                if letter in correct
                else f"Not keyed as correct in the verified screenshot. Compare against: {', '.join(correct)}."
            )
            for letter in choices
        },
        "chapter": metadata["chapter"],
        "subtitle": metadata["subtitle"],
        "domain": metadata["domain"],
        "topics": [metadata["topic"]],
        "study_focus": [metadata["domain"], metadata["topic"]],
        "flagged_issues": [],
        "duplicate_of": [],
    }


def build_question_from_review_record(record: dict[str, Any], question_number: int) -> dict[str, Any]:
    metadata = _metadata_from_record(record)
    source_question_number = record.get("source_question_number")
    filename = record.get("filename") or Path(str(record.get("path", ""))).name
    prompt_hint = sanitize_text(str(record.get("prompt", "")))
    review_label = (
        f"{metadata['chapter']} screenshot" f"{f' Q{source_question_number}' if source_question_number else ''}"
    )
    prompt = prompt_hint or (
        f"{review_label} needs transcription from the source image before it is used as a study question."
    )
    explanation = sanitize_text(str(record.get("general_explanation", "")), trim_embedded_questions=True) or (
        "This screenshot has been imported as a quarantined review item. Verify the prompt, choices, keyed answer, "
        "and explanation against the source image before enabling it for practice."
    )
    return {
        "question_number": int(question_number),
        "source_question_number": source_question_number,
        "source_image": filename,
        "source_image_path": str(record.get("path", "")),
        "source_label": metadata["source_label"],
        "source_page": source_question_number or "",
        "prompt": prompt,
        "choices": {
            "A": "Review source screenshot before studying",
            "B": "Needs prompt transcription",
            "C": "Needs answer-key verification",
            "D": "Needs explanation verification",
        },
        "correct": ["A"],
        "question_type": "single",
        "general_explanation": explanation,
        "choice_explanations": {
            "A": "Placeholder only. This item is suspended until the screenshot is verified.",
            "B": "Placeholder only. Do not study this as a real answer choice.",
            "C": "Placeholder only. Do not study this as a real answer choice.",
            "D": "Placeholder only. Do not study this as a real answer choice.",
        },
        "chapter": metadata["chapter"],
        "subtitle": metadata["subtitle"],
        "domain": metadata["domain"],
        "topics": [metadata["topic"]],
        "study_focus": [metadata["domain"], metadata["topic"]],
        "flagged_issues": [
            "Screenshot imported as review-needed placeholder; verify OCR/transcription before enabling."
        ],
        "duplicate_of": [],
        "suspended": True,
        "import_status": "screenshot_review_needed",
    }


def find_duplicate_candidates(
    question: dict[str, Any],
    base_questions: list[dict[str, Any]],
    *,
    threshold: float = 0.88,
) -> list[dict[str, Any]]:
    target = _question_match_text(question)
    if not target:
        return []
    matches = []
    for existing in base_questions:
        ratio = difflib.SequenceMatcher(None, target, _question_match_text(existing)).ratio()
        if ratio >= threshold:
            matches.append(
                {
                    "question_number": existing.get("question_number"),
                    "ratio": round(ratio, 4),
                    "same_correct": sorted(existing.get("correct", [])) == sorted(question.get("correct", [])),
                }
            )
    return sorted(matches, key=lambda row: row["ratio"], reverse=True)


def merge_verified_records(
    base_payload: dict[str, Any],
    verified_records: list[dict[str, Any]],
    *,
    output_path: str | Path | None = None,
    import_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_questions = list(base_payload.get("questions", []))
    next_qnum = max([int(q.get("question_number", 0) or 0) for q in base_questions] or [0]) + 1
    imported = []
    skipped = []
    for record in verified_records:
        errors = _validate_verified_record(record)
        if errors:
            skipped.append(
                {"source_question_number": record.get("source_question_number"), "reason": "; ".join(errors)}
            )
            continue
        built = build_question_from_verified_record(record, next_qnum)
        duplicates = find_duplicate_candidates(built, base_questions + imported)
        if duplicates:
            skipped.append(
                {
                    "source_question_number": record.get("source_question_number"),
                    "reason": "duplicate_or_near_duplicate",
                    "matches": duplicates[:5],
                }
            )
            continue
        imported.append(built)
        next_qnum += 1
    import_payload = {"title": "Screenshot import - reviewed", "questions": imported}
    merged_payload = {
        "title": str(base_payload.get("title") or "Security Testing Engine Bank"),
        "questions": base_questions + imported,
    }
    summary = {
        "base_count": len(base_questions),
        "verified_count": len(verified_records),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "merged_count": len(merged_payload["questions"]),
    }
    if import_path is not None:
        safe_write_json(Path(import_path), import_payload)
    if output_path is not None:
        safe_write_json(Path(output_path), merged_payload)
    return merged_payload, summary


def merge_review_records(
    base_payload: dict[str, Any],
    review_records: list[dict[str, Any]],
    *,
    output_path: str | Path | None = None,
    import_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_questions = list(base_payload.get("questions", []))
    next_qnum = max([int(q.get("question_number", 0) or 0) for q in base_questions] or [0]) + 1
    existing_images = {
        (str(q.get("source_label", "")), str(q.get("source_image", "")))
        for q in base_questions
        if str(q.get("source_image", "")).strip()
    }
    imported = []
    skipped = []
    for record in review_records:
        image_key = (str(record.get("source_label", "")), str(record.get("filename", "")))
        if image_key in existing_images:
            skipped.append(
                {
                    "source_question_number": record.get("source_question_number"),
                    "filename": record.get("filename"),
                    "reason": "source_image_already_imported",
                }
            )
            continue
        built = build_question_from_review_record(record, next_qnum)
        if str(record.get("status")) in {"ocr_draft", "verified"}:
            duplicates = find_duplicate_candidates(built, base_questions + imported)
            if duplicates:
                skipped.append(
                    {
                        "source_question_number": record.get("source_question_number"),
                        "filename": record.get("filename"),
                        "reason": "duplicate_or_near_duplicate",
                        "matches": duplicates[:5],
                    }
                )
                continue
        imported.append(built)
        existing_images.add((str(built.get("source_label", "")), str(built.get("source_image", ""))))
        next_qnum += 1
    import_payload = {"title": "Screenshot import - quarantined review items", "questions": imported}
    merged_payload = {
        "title": str(base_payload.get("title") or "Security Testing Engine Bank"),
        "questions": base_questions + imported,
    }
    summary = {
        "base_count": len(base_questions),
        "review_count": len(review_records),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "merged_count": len(merged_payload["questions"]),
    }
    if import_path is not None:
        safe_write_json(Path(import_path), import_payload)
    if output_path is not None:
        safe_write_json(Path(output_path), merged_payload)
    return merged_payload, summary


def build_draft_bank_from_manifest(
    manifest: dict[str, Any],
    *,
    output_path: str | Path | None = None,
    start_question_number: int = 900000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    draft_questions = []
    skipped = []
    next_qnum = int(start_question_number)
    for row in manifest.get("screenshots", []):
        if str(row.get("status")) not in {"ocr_draft", "verified"}:
            skipped.append({"source_question_number": row.get("source_question_number"), "reason": row.get("status")})
            continue
        built = build_question_from_verified_record(row, next_qnum)
        built["flagged_issues"] = [
            "OCR draft from screenshot - verify prompt, choices, correct answer, and explanation before merging."
        ]
        draft_questions.append(built)
        next_qnum += 1
    payload = {"title": "Screenshot OCR draft bank - review before merge", "questions": draft_questions}
    summary = {
        "draft_count": len(draft_questions),
        "skipped_count": len(skipped),
        "skipped": skipped,
    }
    if output_path is not None:
        safe_write_json(Path(output_path), payload)
    return payload, summary


def load_verified_records(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    return [dict(row) for row in payload.get("screenshots", []) if str(row.get("status", "")).lower() == "verified"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a review-first import manifest for screenshot questions.")
    parser.add_argument("--source-folder", type=Path, default=DEFAULT_SOURCE_FOLDER)
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK_PATH)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_PATH)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--extract-ocr", action="store_true")
    parser.add_argument("--draft-output", type=Path)
    parser.add_argument("--chapter")
    parser.add_argument("--domain")
    parser.add_argument("--domain-code")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--verified-records", type=Path)
    parser.add_argument("--include-review-stubs", action="store_true")
    parser.add_argument("--merged-output", type=Path, default=DEFAULT_MERGED_PATH)
    parser.add_argument("--import-output", type=Path, default=DEFAULT_IMPORT_PATH)
    args = parser.parse_args()

    metadata = infer_metadata_from_source_folder(args.source_folder)
    if args.chapter:
        metadata["chapter"] = args.chapter
    if args.domain:
        metadata["domain"] = args.domain
    if args.domain_code:
        metadata["domain_code"] = args.domain_code
    if args.topic:
        metadata["topic"] = args.topic
    metadata["subtitle"] = f"{metadata['chapter']} screenshot bank - Domain {metadata['domain_code']}"
    metadata["source_label"] = f"{metadata['chapter']} screenshot bank"

    manifest = build_review_manifest(
        args.source_folder,
        args.review_output,
        expected_count=args.expected_count,
        metadata=metadata,
        extract_ocr=args.extract_ocr,
    )
    print(f"Found {manifest['found_count']} screenshots. Review manifest: {args.review_output}")
    if args.draft_output:
        _draft, draft_summary = build_draft_bank_from_manifest(manifest, output_path=args.draft_output)
        print(f"Wrote {draft_summary['draft_count']} OCR draft questions: {args.draft_output}")
    if args.verified_records:
        base_payload = json.loads(args.bank.read_text(encoding="utf-8"))
        records = load_verified_records(args.verified_records)
        _merged, summary = merge_verified_records(
            base_payload,
            records,
            output_path=args.merged_output,
            import_path=args.import_output,
        )
        print(f"Imported {summary['imported_count']} reviewed screenshots; skipped {summary['skipped_count']}.")
        print(f"Merged output: {args.merged_output}")
    if args.include_review_stubs:
        base_payload = json.loads(args.bank.read_text(encoding="utf-8"))
        _merged, summary = merge_review_records(
            base_payload,
            list(manifest.get("screenshots", [])),
            output_path=args.merged_output,
            import_path=args.import_output,
        )
        print(f"Imported {summary['imported_count']} quarantined screenshot review items.")
        print(f"Skipped {summary['skipped_count']} already imported or duplicate screenshots.")
        print(f"Merged output: {args.merged_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
