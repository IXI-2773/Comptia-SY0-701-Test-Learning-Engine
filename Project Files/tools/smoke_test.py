from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'release' / 'SecurityTestingEngine'
REPORT = ROOT / 'reports' / 'bank_validation_report.md'


def require(path: Path, label: str):
    if not path.exists():
        raise AssertionError(f'Missing {label}: {path}')


def main():
    require(RELEASE / 'SecurityTestingEngine.exe', 'release EXE')
    release_items = [path.name for path in RELEASE.iterdir()]
    if release_items != ['SecurityTestingEngine.exe']:
        raise AssertionError(f'Release folder should contain only the EXE, found: {release_items}')
    require(REPORT, 'bank validation report')
    text = REPORT.read_text(encoding='utf-8')
    if 'Issues: **0**' not in text:
        raise AssertionError('Bank validation report does not show 0 issues.')
    print('Smoke test passed.')
    print(f'Release: {RELEASE}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Smoke test failed: {e}', file=sys.stderr)
        sys.exit(1)
