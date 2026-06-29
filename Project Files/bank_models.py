from typing import Any, TypedDict, cast


class BankQuestion(TypedDict, total=False):
    question_number: int
    prompt: str
    choices: dict[str, str]
    correct: list[str]
    general_explanation: str
    choice_explanations: dict[str, str]
    domain: str
    chapter: str
    subtitle: str
    question_type: str
    topics: list[str]
    flagged_issues: list[str]
    source_page: int | str
    choice_order: list[str]
    source_name: str
    objective_code: str
    study_focus: str
    duplicate_of: int | None


class QuestionBankData(TypedDict):
    title: str
    questions: list[BankQuestion]


def as_bank_question(payload: dict[str, Any]) -> BankQuestion:
    return cast(BankQuestion, payload)
