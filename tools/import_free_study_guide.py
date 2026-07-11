import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from question_bank import sanitize_text
from storage_utils import safe_write_json
from tools.rebalance_bank_choice_order import rebalance_bank_choice_order


PDF_PATH = Path(r'F:\CyberSecurity\Ecurity+\Free Study Guide_A5.pdf')
BASE_BANK_PATH = ROOT / 'public_sy0701_bank_v4_clean.json'
SUPPLEMENTAL_BANK_PATH = ROOT / 'free_study_guide_a5_import_bank.json'
LEGACY_SUPPLEMENTAL_BANK_PATH = ROOT / 'free_study_guide_a5_assessments_bank.json'
MERGED_BANK_PATH = ROOT / 'public_sy0701_bank_v4_plus_studyguide_clean.json'
REPORT_PATH = ROOT / 'reports' / 'free_study_guide_import_report.md'

DOMAIN_BY_PREFIX = {
    '1': 'General Security Concepts',
    '2': 'Threats, Vulnerabilities, and Mitigations',
    '3': 'Security Architecture',
    '4': 'Security Operations',
    '5': 'Security Program Management and Oversight',
}

OBJECTIVE_TOPIC_MAP = {
    '1.1': ['General Review'],
    '1.2': ['General Review', 'Physical Security'],
    '1.4': ['Encryption / PKI'],
    '2.1': ['Threats / Malware'],
    '2.2': ['Threats / Malware', 'Cloud / Network Design'],
    '2.3': ['Threats / Malware', 'AppSec / Web'],
    '2.4': ['Threats / Malware', 'Operations / IR'],
    '2.5': ['Threats / Malware', 'AppSec / Web'],
    '3.1': ['Cloud / Network Design', 'General Review'],
    '3.2': ['Cloud / Network Design'],
    '3.4': ['Cloud / Network Design', 'General Review'],
    '4.1': ['AppSec / Web', 'Operations / IR'],
    '4.2': ['General Review', 'Governance / Risk / Compliance'],
    '4.3': ['Operations / IR', 'Security Tools / Commands'],
    '4.4': ['Operations / IR', 'Security Tools / Commands'],
    '4.5': ['Cloud / Network Design', 'Operations / IR'],
    '4.6': ['Identity / Access Control'],
    '4.7': ['Operations / IR', 'AppSec / Web'],
    '4.8': ['Operations / IR'],
    '4.9': ['Operations / IR', 'Security Tools / Commands'],
    '5.1': ['Governance / Risk / Compliance'],
    '5.2': ['Governance / Risk / Compliance', 'General Review'],
    '5.3': ['Governance / Risk / Compliance'],
}

OBJECTIVE_FOCUS_MAP = {
    '1.1': 'Security controls and their categories.',
    '1.2': 'Core security principles and physical protection.',
    '1.4': 'Cryptography, certificates, and confidentiality controls.',
    '2.1': 'Threat actors and likely motivations.',
    '2.2': 'Attack vectors, attack surfaces, and delivery methods.',
    '2.3': 'Common vulnerabilities and exploitation patterns.',
    '2.4': 'Indicators of malicious activity and attack recognition.',
    '2.5': 'Mitigation and hardening techniques.',
    '3.1': 'Architecture models, resiliency, and availability tradeoffs.',
    '3.2': 'Enterprise infrastructure security design.',
    '3.4': 'Resilience, backup, recovery, and continuity design.',
    '4.1': 'Host, application, and endpoint protection techniques.',
    '4.2': 'Asset lifecycle, ownership, and data handling.',
    '4.3': 'Vulnerability scanning, validation, and remediation workflow.',
    '4.4': 'Monitoring, SIEM, SOAR, and alert handling.',
    '4.5': 'Security capability tuning and control adjustments.',
    '4.6': 'Identity, authentication, authorization, and account management.',
    '4.7': 'Automation, CI/CD, and orchestration in secure operations.',
    '4.8': 'Incident response and forensics process steps.',
    '4.9': 'Data sources and tools used in investigations.',
    '5.1': 'Governance, policy, and personnel security.',
    '5.2': 'Risk management, BIA, and recovery metrics.',
    '5.3': 'Vendor management, contracts, and third-party risk.',
}

CHAPTER_IMPORT_META = {
    1: {
        'title': 'Mastering Security Basics',
        'domain': 'General Security Concepts',
        'topics': ['General Review', 'Operations / IR', 'Security Tools / Commands'],
        'study_focus': 'Core security principles, controls, risk basics, and monitoring.',
    },
    2: {
        'title': 'Understanding Identity and Access Management',
        'domain': 'Security Operations',
        'topics': ['Identity / Access Control', 'General Review'],
        'study_focus': 'Authentication, authorization, account management, and access control models.',
    },
    3: {
        'title': 'Exploring Network Technologies and Tools',
        'domain': 'Security Architecture',
        'topics': ['Cloud / Network Design', 'Security Tools / Commands', 'General Review'],
        'study_focus': 'Network design, segmentation, protocols, and core security tooling.',
    },
    4: {
        'title': 'Securing Your Network',
        'domain': 'Security Architecture',
        'topics': ['Cloud / Network Design', 'Threats / Malware', 'Operations / IR'],
        'study_focus': 'Wireless, VPNs, IDS/IPS, network attacks, and defensive network controls.',
    },
    5: {
        'title': 'Securing Hosts and Data',
        'domain': 'Security Architecture',
        'topics': ['AppSec / Web', 'Operations / IR', 'Cloud / Network Design'],
        'study_focus': 'Endpoint hardening, host protections, data protection, and cloud service controls.',
    },
    6: {
        'title': 'Comparing Threats, Vulnerabilities, and Common Attacks',
        'domain': 'Threats, Vulnerabilities, and Mitigations',
        'topics': ['Threats / Malware', 'General Review'],
        'study_focus': 'Threat actors, social engineering, malware, and attack path recognition.',
    },
    7: {
        'title': 'Protecting Against Advanced Attacks',
        'domain': 'Threats, Vulnerabilities, and Mitigations',
        'topics': ['AppSec / Web', 'Threats / Malware', 'Operations / IR'],
        'study_focus': 'Advanced attacks, secure coding, validation, and automation use cases.',
    },
    8: {
        'title': 'Using Risk Management Tools',
        'domain': 'Security Program Management and Oversight',
        'topics': ['Governance / Risk / Compliance', 'General Review'],
        'study_focus': 'Risk analysis, vulnerability management, supply chain, and audit concepts.',
    },
    9: {
        'title': 'Implementing Controls to Protect Assets',
        'domain': 'Security Architecture',
        'topics': ['Physical Security', 'Cloud / Network Design', 'Operations / IR', 'General Review'],
        'study_focus': 'Physical controls, resiliency, backups, recovery planning, and continuity.',
    },
    10: {
        'title': 'Understanding Cryptography and PKI',
        'domain': 'Security Architecture',
        'topics': ['Encryption / PKI', 'General Review'],
        'study_focus': 'Cryptography, hashing, certificates, PKI, and trust models.',
    },
    11: {
        'title': 'Implementing Policies to Mitigate Risks',
        'domain': 'Security Program Management and Oversight',
        'topics': ['Governance / Risk / Compliance', 'Operations / IR', 'General Review'],
        'study_focus': 'Policies, change management, data governance, incident response, and awareness.',
    },
}

SECTION_SPECS = [
    {
        'name': 'Pre-Assessment',
        'kind': 'assessment',
        'question_pages': (1, 19),
        'answer_pages': (20, 42),
        'expected_count': 50,
    },
    {
        'name': 'Post-Assessment',
        'kind': 'assessment',
        'question_pages': (930, 961),
        'answer_pages': (962, 999),
        'expected_count': 90,
    },
    {
        'name': 'Chapter 1 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 1,
        'question_pages': (87, 93),
        'answer_pages': (94, 100),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 2 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 2,
        'question_pages': (168, 174),
        'answer_pages': (175, 181),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 3 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 3,
        'question_pages': (244, 251),
        'answer_pages': (252, 258),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 4 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 4,
        'question_pages': (327, 333),
        'answer_pages': (334, 340),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 5 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 5,
        'question_pages': (421, 426),
        'answer_pages': (427, 433),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 6 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 6,
        'question_pages': (505, 511),
        'answer_pages': (512, 517),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 7 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 7,
        'question_pages': (570, 576),
        'answer_pages': (577, 582),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 8 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 8,
        'question_pages': (648, 653),
        'answer_pages': (654, 659),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 9 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 9,
        'question_pages': (724, 730),
        'answer_pages': (731, 737),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 10 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 10,
        'question_pages': (832, 837),
        'answer_pages': (838, 843),
        'expected_count': 15,
    },
    {
        'name': 'Chapter 11 Practice Questions',
        'kind': 'chapter',
        'chapter_number': 11,
        'question_pages': (917, 923),
        'answer_pages': (924, 929),
        'expected_count': 15,
    },
]

QUESTION_START_RE = re.compile(r'^(\d{1,3})\.\s+(.*)$')
CHOICE_RE = re.compile(r'^([A-F])\.\s*(.*)$')
OBJECTIVE_RE = re.compile(r'(?:exam\s+)?objective\s+([1-5]\.\d)', re.I)
CHAPTER_RE = re.compile(r'covered in Chapter\s+(\d+)', re.I)
ANSWER_PREFIX_RE = re.compile(
    r'^([A-F](?:\s*,\s*[A-F])*(?:\s*,?\s+and\s+[A-F])?)\s+(?:is|are)\s+correct\.\s*(.*)$',
    re.I | re.S,
)
META_SENTENCE_RE = re.compile(
    r'\s*This question comes from.*?covered in Chapter\s+\d+\.',
    re.I | re.S,
)
TRAILING_CHAPTER_HEADING_RE = re.compile(
    r'\s*Chapter\s+\d+\s+.*?CompTIA Security\+ objectives covered in this chapter:.*$',
    re.I | re.S,
)


def _clean_line(text: str) -> str:
    return sanitize_text(text, trim_embedded_questions=False).strip()


def _normalize_text(value: str) -> str:
    value = sanitize_text(value, trim_embedded_questions=True).lower()
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _prompt_key(prompt: str) -> str:
    return _normalize_text(prompt)


def _question_signature(prompt: str, choices: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    ordered_choices = tuple(
        _normalize_text(choices.get(letter, ''))
        for letter in sorted(choices)
        if str(choices.get(letter, '')).strip()
    )
    return _prompt_key(prompt), ordered_choices


def _split_inline_choice_runs(line: str) -> list[str]:
    matches = list(re.finditer(r'([A-F])\.\s*', line))
    if len(matches) <= 1 or matches[0].start() != 0:
        return [line]
    parts = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
        parts.append(line[start:end].strip())
    return [part for part in parts if part]


def _parse_question_section(reader: PdfReader, start_page: int, end_page: int):
    blocks = []
    current = None
    for page_idx in range(start_page, min(end_page + 1, len(reader.pages))):
        text = reader.pages[page_idx].extract_text() or ''
        for raw_line in text.splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            match = QUESTION_START_RE.match(line)
            if match:
                if current is not None:
                    blocks.append(current)
                current = {
                    'number': int(match.group(1)),
                    'page': page_idx + 1,
                    'lines': [match.group(2).strip()],
                }
                continue
            if current is not None:
                current['lines'].append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _parse_question_block(block):
    prompt_parts = []
    choices = {}
    current_choice = None
    for raw_line in block['lines']:
        for line in _split_inline_choice_runs(raw_line):
            choice_match = CHOICE_RE.match(line)
            if choice_match:
                current_choice = choice_match.group(1).upper()
                if current_choice in choices:
                    current_choice = next(
                        (letter for letter in 'ABCDEF' if letter not in choices),
                        current_choice,
                    )
                choices[current_choice] = choice_match.group(2).strip()
                continue
            if current_choice and current_choice in choices:
                choices[current_choice] = f"{choices[current_choice]} {line}".strip()
            else:
                prompt_parts.append(line)
    prompt = sanitize_text(' '.join(prompt_parts), trim_embedded_questions=True)
    ordered_choice_texts = [
        sanitize_text(text, trim_embedded_questions=True)
        for text in choices.values()
        if str(text).strip()
    ]
    normalized_choices = {
        chr(ord('A') + idx): text
        for idx, text in enumerate(ordered_choice_texts)
    }
    return {
        'source_question_number': int(block['number']),
        'source_page': int(block['page']),
        'prompt': prompt,
        'choices': normalized_choices,
    }


def _parse_answer_section(reader: PdfReader, start_page: int, end_page: int):
    blocks = []
    current = None
    for page_idx in range(start_page, min(end_page + 1, len(reader.pages))):
        text = reader.pages[page_idx].extract_text() or ''
        for raw_line in text.splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            match = QUESTION_START_RE.match(line)
            if match:
                if current is not None:
                    blocks.append(current)
                current = {
                    'number': int(match.group(1)),
                    'page': page_idx + 1,
                    'lines': [match.group(2).strip()],
                }
                continue
            if current is not None:
                current['lines'].append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _parse_answer_block(block):
    text = sanitize_text(' '.join(block['lines']), trim_embedded_questions=False)
    match = ANSWER_PREFIX_RE.match(text)
    if not match:
        raise ValueError(f"Could not parse answer block {block['number']}")
    letters_text = match.group(1)
    body = match.group(2).strip()
    correct = list(dict.fromkeys(re.findall(r'\b[A-F]\b', letters_text.upper())))
    objective_match = OBJECTIVE_RE.search(text)
    chapter_match = CHAPTER_RE.search(text)
    objective = objective_match.group(1) if objective_match else ''
    chapter = chapter_match.group(1) if chapter_match else ''
    explanation = META_SENTENCE_RE.sub('', body).strip()
    explanation = TRAILING_CHAPTER_HEADING_RE.sub('', explanation).strip()
    explanation = sanitize_text(explanation, trim_embedded_questions=True)
    return {
        'source_question_number': int(block['number']),
        'answer_page': int(block['page']),
        'correct': correct,
        'objective': objective,
        'chapter_number': chapter,
        'explanation': explanation,
    }


def _topics_for_objective(objective: str):
    topics = list(OBJECTIVE_TOPIC_MAP.get(objective, ['General Review']))
    seen = set()
    ordered = []
    for topic in topics:
        if topic not in seen:
            ordered.append(topic)
            seen.add(topic)
    return ordered


def _domain_for_objective(objective: str):
    prefix = str(objective).split('.', 1)[0]
    return DOMAIN_BY_PREFIX.get(prefix, 'General Security Concepts')


def _study_focus_for_objective(objective: str):
    return OBJECTIVE_FOCUS_MAP.get(objective, 'Security+ assessment remediation.')


def _question_type(prompt: str, correct: list[str]):
    if len(correct) > 1:
        return 'multi'
    normalized = prompt.lower()
    if any(token in normalized for token in ('select two', 'choose two', 'select three', 'choose three')):
        return 'multi'
    return 'single'


def _choice_explanations(choices: dict[str, str], correct: list[str], explanation: str):
    correct_text = ' and '.join(correct)
    keyed_choice_preview = ', '.join(f"{letter}. {choices.get(letter, '')}".strip() for letter in correct)
    rows = {}
    for letter, text in choices.items():
        if letter in correct:
            rows[letter] = f"Correct option. The source key marks {correct_text} as correct. {explanation}".strip()
        else:
            rows[letter] = f"Not keyed as correct in the source. Compare this choice against the keyed answer: {keyed_choice_preview}".strip()
    return rows


def _build_assessment_question(spec: dict, q: dict, a: dict, question_number: int):
    objective = a['objective']
    return {
        'question_number': question_number,
        'source_page': q['source_page'],
        'prompt': q['prompt'],
        'choices': q['choices'],
        'correct': list(a['correct']),
        'question_type': _question_type(q['prompt'], a['correct']),
        'general_explanation': a['explanation'],
        'choice_explanations': _choice_explanations(q['choices'], a['correct'], a['explanation']),
        'chapter': spec['name'],
        'subtitle': f"Free Study Guide A5 • {spec['name']} Q{q['source_question_number']} • Page {q['source_page']}",
        'source_name': 'Free Study Guide A5',
        'objective_code': objective,
        'domain': _domain_for_objective(objective),
        'topics': _topics_for_objective(objective),
        'study_focus': _study_focus_for_objective(objective),
        'flagged_issues': [],
        'duplicate_of': None,
    }


def _build_chapter_question(spec: dict, q: dict, a: dict, question_number: int):
    chapter_number = int(spec['chapter_number'])
    chapter_meta = CHAPTER_IMPORT_META[chapter_number]
    chapter_label = f"Chapter {chapter_number}: {chapter_meta['title']}"
    return {
        'question_number': question_number,
        'source_page': q['source_page'],
        'prompt': q['prompt'],
        'choices': q['choices'],
        'correct': list(a['correct']),
        'question_type': _question_type(q['prompt'], a['correct']),
        'general_explanation': a['explanation'],
        'choice_explanations': _choice_explanations(q['choices'], a['correct'], a['explanation']),
        'chapter': chapter_label,
        'subtitle': f"Free Study Guide A5 • Chapter {chapter_number} Practice Q{q['source_question_number']} • Page {q['source_page']}",
        'source_name': 'Free Study Guide A5',
        'objective_code': '',
        'domain': chapter_meta['domain'],
        'topics': list(chapter_meta['topics']),
        'study_focus': chapter_meta['study_focus'],
        'flagged_issues': [],
        'duplicate_of': None,
    }


def _build_imported_questions(base_bank: list[dict], reader: PdfReader):
    imported = []
    next_qnum = max(int(q.get('question_number', 0)) for q in base_bank) + 1
    section_summary = []
    existing_prompt_keys = {_prompt_key(q.get('prompt', '')) for q in base_bank}
    existing_signatures = {
        _question_signature(q.get('prompt', ''), q.get('choices', {}) or {})
        for q in base_bank
    }

    for spec in SECTION_SPECS:
        qblocks = _parse_question_section(reader, *spec['question_pages'])
        ablocks = _parse_answer_section(reader, *spec['answer_pages'])
        questions = {}
        for item in qblocks:
            parsed = _parse_question_block(item)
            if parsed['choices']:
                questions[parsed['source_question_number']] = parsed
        answers = {}
        for item in ablocks:
            raw_text = sanitize_text(' '.join(item['lines']), trim_embedded_questions=False)
            if ANSWER_PREFIX_RE.match(raw_text):
                parsed = _parse_answer_block(item)
                answers[parsed['source_question_number']] = parsed

        shared_numbers = sorted(set(questions) & set(answers))
        if len(shared_numbers) != spec['expected_count']:
            raise ValueError(
                f"{spec['name']} parse mismatch: expected {spec['expected_count']}, "
                f"got {len(shared_numbers)} questions with answers."
            )

        imported_count = 0
        skipped_numbers = []
        for source_number in shared_numbers:
            q = questions[source_number]
            a = answers[source_number]
            prompt_key = _prompt_key(q['prompt'])
            signature = _question_signature(q['prompt'], q['choices'])
            if prompt_key in existing_prompt_keys or signature in existing_signatures:
                skipped_numbers.append(source_number)
                continue
            if spec['kind'] == 'assessment':
                built = _build_assessment_question(spec, q, a, next_qnum)
            else:
                built = _build_chapter_question(spec, q, a, next_qnum)
            imported.append(built)
            existing_prompt_keys.add(prompt_key)
            existing_signatures.add(signature)
            next_qnum += 1
            imported_count += 1

        section_summary.append(
            {
                'name': spec['name'],
                'kind': spec['kind'],
                'parsed_count': len(shared_numbers),
                'imported_count': imported_count,
                'duplicate_count': len(skipped_numbers),
                'duplicate_examples': skipped_numbers[:12],
                'first_page': min(questions[number]['source_page'] for number in shared_numbers),
                'last_page': max(questions[number]['source_page'] for number in shared_numbers),
            }
        )
    return imported, section_summary


def _write_report(base_count: int, imported: list[dict], merged_count: int, section_summary: list[dict]):
    domain_counts = {}
    topic_counts = {}
    for q in imported:
        domain_counts[q['domain']] = domain_counts.get(q['domain'], 0) + 1
        for topic in q.get('topics', []):
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    parsed_total = sum(row['parsed_count'] for row in section_summary)
    duplicate_total = sum(row['duplicate_count'] for row in section_summary)
    lines = [
        '# Free Study Guide Import Report',
        '',
        f'- Source PDF: `{PDF_PATH}`',
        f'- Base engine bank count: **{base_count}**',
        f'- Parsed structured study-guide questions: **{parsed_total}**',
        f'- Imported non-duplicate study-guide questions: **{len(imported)}**',
        f'- Skipped duplicate questions: **{duplicate_total}**',
        f'- Merged bank count: **{merged_count}**',
        '',
        '## Imported Sections',
        '',
    ]
    for row in section_summary:
        detail = (
            f"- `{row['name']}`: parsed {row['parsed_count']}, "
            f"imported {row['imported_count']}, duplicates skipped {row['duplicate_count']} "
            f"(pages {row['first_page']}-{row['last_page']})"
        )
        lines.append(detail)
        if row['duplicate_examples']:
            sample = ', '.join(f"Q{number}" for number in row['duplicate_examples'])
            lines.append(f"  Duplicate examples: {sample}")
    lines.extend(['', '## Imported Domain Counts', ''])
    for domain, count in sorted(domain_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f'- {domain}: {count}')
    lines.extend(['', '## Imported Topic Counts', ''])
    for topic, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f'- {topic}: {count}')
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def build_free_study_guide_import(
    pdf_path: Path = PDF_PATH,
    base_bank_path: Path = BASE_BANK_PATH,
    supplemental_path: Path = SUPPLEMENTAL_BANK_PATH,
    merged_path: Path = MERGED_BANK_PATH,
):
    if not pdf_path.exists():
        raise FileNotFoundError(f'Missing study guide PDF: {pdf_path}')
    base_data = json.loads(base_bank_path.read_text(encoding='utf-8'))
    base_questions = list(base_data.get('questions', []))
    reader = PdfReader(str(pdf_path))
    imported_questions, section_summary = _build_imported_questions(base_questions, reader)
    supplemental_payload = {
        'title': 'Free Study Guide A5 Imported Questions',
        'questions': imported_questions,
    }
    merged_payload = {
        'title': base_data.get('title', 'Security Testing Engine Bank') + ' + Free Study Guide Imported Questions',
        'questions': list(base_questions) + imported_questions,
    }
    safe_write_json(supplemental_path, supplemental_payload)
    safe_write_json(LEGACY_SUPPLEMENTAL_BANK_PATH, supplemental_payload)
    safe_write_json(merged_path, merged_payload)
    rebalance_bank_choice_order(supplemental_path)
    rebalance_bank_choice_order(LEGACY_SUPPLEMENTAL_BANK_PATH)
    rebalance_bank_choice_order(merged_path)
    _write_report(len(base_questions), imported_questions, len(merged_payload['questions']), section_summary)
    return {
        'supplemental_path': supplemental_path,
        'merged_path': merged_path,
        'imported_count': len(imported_questions),
        'merged_count': len(merged_payload['questions']),
        'section_summary': section_summary,
    }


def main():
    result = build_free_study_guide_import()
    print(f"Imported {result['imported_count']} study guide questions.")
    print(f"Supplemental bank: {result['supplemental_path']}")
    print(f"Merged bank: {result['merged_path']}")


if __name__ == '__main__':
    main()
