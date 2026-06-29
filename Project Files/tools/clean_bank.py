from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from question_bank import load_bank, sanitize_text
from storage_utils import safe_write_json
from tools.validate_bank import validate_bank


DEFAULT_SOURCE = ROOT / 'public_sy0701_bank_v4.json'
DEFAULT_OUTPUT = ROOT / 'public_sy0701_bank_v4_clean.json'
REPORT_DIR = ROOT / 'reports'
REPORT_PATH = REPORT_DIR / 'bank_cleanup_report.md'


def _field_notes(label, raw_value, trim_embedded=False):
    _cleaned, notes = sanitize_text(raw_value, trim_embedded_questions=trim_embedded, collect_notes=True)
    return [f'{label}: {note}' for note in notes]


def build_cleanup_summary(raw_data, cleaned_data):
    note_counter = Counter()
    examples = []
    touched_questions = set()
    raw_questions = list(raw_data.get('questions', []))
    cleaned_questions = list(cleaned_data.get('questions', []))

    for idx, (raw_q, cleaned_q) in enumerate(zip(raw_questions, cleaned_questions), start=1):
        qnum = cleaned_q.get('question_number', raw_q.get('question_number', idx))
        notes = []
        notes.extend(_field_notes('prompt', raw_q.get('prompt', ''), trim_embedded=False))
        notes.extend(_field_notes('general explanation', raw_q.get('general_explanation', ''), trim_embedded=True))
        for letter, raw_choice in (raw_q.get('choices') or {}).items():
            notes.extend(_field_notes(f'choice {letter}', raw_choice, trim_embedded=False))
        for letter, raw_expl in (raw_q.get('choice_explanations') or {}).items():
            notes.extend(_field_notes(f'choice {letter} explanation', raw_expl, trim_embedded=True))
        if notes:
            touched_questions.add(qnum)
            compact_notes = list(dict.fromkeys(notes))
            for note in compact_notes:
                note_counter[note.split(': ', 1)[1]] += 1
            if len(examples) < 16:
                examples.append(f"Q{qnum}: {'; '.join(compact_notes[:4])}")

    return {
        'question_count': len(cleaned_questions),
        'touched_questions': len(touched_questions),
        'note_counter': dict(sorted(note_counter.items(), key=lambda item: (-item[1], item[0]))),
        'examples': examples,
    }


def write_cleanup_report(summary, validation_result, source_path, output_path, report_path=REPORT_PATH):
    REPORT_DIR.mkdir(exist_ok=True)
    lines = [
        '# Bank Cleanup Report',
        '',
        f"- Source bank: `{source_path.name}`",
        f"- Cleaned bank: `{output_path.name}`",
        f"- Questions: **{summary['question_count']}**",
        f"- Questions touched by cleanup: **{summary['touched_questions']}**",
        f"- Cleaned-bank validation issues: **{len(validation_result['issues'])}**",
        f"- Cleaned-bank validation warnings: **{len(validation_result.get('warnings', []))}**",
        '',
        '## Cleanup Types',
        '',
    ]
    if summary['note_counter']:
        for note, count in summary['note_counter'].items():
            lines.append(f'- **{note}**: {count}')
    else:
        lines.append('No cleanup changes were needed.')
    lines.extend(['', '## Cleanup Examples', ''])
    if summary['examples']:
        for example in summary['examples']:
            lines.append(f'- {example}')
    else:
        lines.append('No examples captured.')
    lines.extend(['', '## Remaining Validator Warnings', ''])
    if validation_result.get('warnings'):
        for title, body in validation_result['warnings'][:20]:
            lines.append(f'- **{title}**: {body}')
    else:
        lines.append('No warnings remain on the cleaned bank.')
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report_path


def clean_bank(source_path=DEFAULT_SOURCE, output_path=DEFAULT_OUTPUT):
    with open(source_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
    cleaned_data = load_bank(source_path)
    if isinstance(raw_data, dict) and 'title' in raw_data:
        cleaned_data['title'] = sanitize_text(raw_data.get('title', ''))
    safe_write_json(output_path, cleaned_data)
    summary = build_cleanup_summary(raw_data, cleaned_data)
    validation_result = validate_bank(output_path)
    report_path = write_cleanup_report(summary, validation_result, Path(source_path), Path(output_path))
    return cleaned_data, summary, validation_result, report_path


def main():
    source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    _cleaned, summary, validation_result, report_path = clean_bank(source_path, output_path)
    print(f'Cleaned bank written: {output_path}')
    print(f"Questions touched: {summary['touched_questions']}")
    print(f"Remaining warnings on cleaned bank: {len(validation_result.get('warnings', []))}")
    print(f'Report: {report_path}')


if __name__ == '__main__':
    main()
