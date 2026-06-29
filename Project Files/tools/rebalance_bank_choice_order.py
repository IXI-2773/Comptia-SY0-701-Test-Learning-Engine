import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage_utils import safe_write_json


DEFAULT_BANK_PATH = ROOT / 'public_sy0701_bank_v4_clean.json'

# Old choice letters in the new A/B/C/D order.
QUESTION_ORDER_OVERRIDES = {}

MAX_SINGLE_ANSWER_STREAK = 5

CORRECT_MARK_RE = re.compile(r'(source key marks )([A-F](?:\s+and\s+[A-F])?)( as correct)', re.I)
KEYED_ANSWER_RE = re.compile(r'(keyed answer:\s*)([A-F])(\.\s*.*)$', re.I)


def _remap_single_answer_explanation(text: str, new_correct_letter: str, new_correct_choice_text: str) -> str:
    text = CORRECT_MARK_RE.sub(rf'\1{new_correct_letter}\3', text)
    text = KEYED_ANSWER_RE.sub(
        rf'\1{new_correct_letter}. {new_correct_choice_text}',
        text,
    )
    return text


def _current_choice_letters(question: dict) -> list[str]:
    return [letter for letter in 'ABCDEF' if str((question.get('choices') or {}).get(letter, '')).strip()]


def _build_new_order(question: dict, move_correct_to_front: bool = True) -> list[str]:
    letters = _current_choice_letters(question)
    correct_letter = list(question.get('correct', []))[0]
    remaining = [letter for letter in letters if letter != correct_letter]
    if move_correct_to_front:
        return [correct_letter] + remaining
    return remaining + [correct_letter]


def _apply_reorder(question: dict, order: list[str]):
    old_choices = dict(question.get('choices', {}))
    if len(old_choices) != len(order):
        raise ValueError(
            f"Question {question.get('question_number')} expected {len(order)} choices, found {len(old_choices)}."
        )
    new_letters = list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')[:len(order)]
    new_by_old = {old_letter: new_letters[idx] for idx, old_letter in enumerate(order)}
    question['choices'] = {
        new_letters[idx]: old_choices[old_letter]
        for idx, old_letter in enumerate(order)
    }

    old_correct = list(question.get('correct', []))
    question['correct'] = sorted(new_by_old[old_letter] for old_letter in old_correct)

    if question.get('choice_explanations'):
        old_choice_explanations = dict(question.get('choice_explanations', {}))
        question['choice_explanations'] = {
            new_by_old.get(old_letter, old_letter): old_choice_explanations[old_letter]
            for old_letter in order
            if old_letter in old_choice_explanations
        }
        if len(question['correct']) == 1:
            correct_letter = question['correct'][0]
            correct_text = question['choices'][correct_letter]
            for key, text in list(question['choice_explanations'].items()):
                question['choice_explanations'][key] = _remap_single_answer_explanation(
                    str(text),
                    correct_letter,
                    correct_text,
                )


def _find_streak_questions(questions: list[dict]) -> list[int]:
    single_sequence = [
        question
        for question in sorted(questions, key=lambda item: int(item.get('question_number', 0)))
        if question.get('question_type') == 'single' and len(question.get('correct', [])) == 1
    ]
    streaks = []
    streak = []
    current_letter = None
    for question in single_sequence:
        letter = question['correct'][0]
        if letter == current_letter:
            streak.append(question)
        else:
            if len(streak) >= MAX_SINGLE_ANSWER_STREAK + 1:
                streaks.append(streak)
            current_letter = letter
            streak = [question]
    if len(streak) >= MAX_SINGLE_ANSWER_STREAK + 1:
        streaks.append(streak)

    selected = []
    for streak in streaks:
        midpoint = len(streak) // 2
        selected.append(int(streak[midpoint]['question_number']))
    return selected


def rebalance_bank_choice_order(path: Path = DEFAULT_BANK_PATH):
    path = Path(path)
    payload = json.loads(path.read_text(encoding='utf-8'))
    questions = list(payload.get('questions', []))
    auto_qnums = _find_streak_questions(questions)
    changed = []
    for question in questions:
        qnum = int(question.get('question_number', 0))
        order = QUESTION_ORDER_OVERRIDES.get(qnum)
        if order is None and qnum in auto_qnums:
            move_to_front = list(question.get('correct', []))[0] != 'A'
            order = _build_new_order(question, move_correct_to_front=move_to_front)
        if not order:
            continue

        _apply_reorder(question, order)

        changed.append(qnum)

    safe_write_json(path, payload)
    return changed


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BANK_PATH
    changed = rebalance_bank_choice_order(target)
    print(f'Rebalanced questions: {changed}')


if __name__ == '__main__':
    main()
