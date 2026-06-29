from collections.abc import Mapping
from typing import TypedDict

from analytics_models import SourceAgreementRow, SourceTrustRow


class SourceTrustWarning(TypedDict):
    level: str
    text: str
    background: str
    foreground: str


def derive_source_trust_warning(
    question: Mapping[str, object],
    agreement_map: Mapping[int, SourceAgreementRow],
    trust_map: Mapping[str, SourceTrustRow],
) -> SourceTrustWarning | None:
    raw_question_number = question.get("question_number")
    question_number = int(raw_question_number) if isinstance(raw_question_number, (int, str)) else 0
    agreement = agreement_map.get(question_number)
    if agreement and agreement.get("label") == "Source conflict":
        return {
            "level": "conflict",
            "text": "Source conflict",
            "background": "#f9e4e4",
            "foreground": "#9d2f2f",
        }

    source_name = str(question.get("source_name") or "").strip()
    trust = trust_map.get(source_name)
    if trust and trust.get("label") == "Decayed":
        return {
            "level": "decayed",
            "text": "Source decayed",
            "background": "#fff1d6",
            "foreground": "#8a5a08",
        }
    return None
