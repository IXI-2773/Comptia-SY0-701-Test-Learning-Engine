import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = BASE_DIR / 'dist'
RELEASE_DIR = BASE_DIR / 'release' / 'SecurityTestingEngine'
LEGACY_SOURCE_DIR = BASE_DIR / 'Project Files'
LEGACY_LAYOUT = (LEGACY_SOURCE_DIR / 'app.py').exists()
APP_SHELL_DIR = BASE_DIR.parent if LEGACY_LAYOUT else BASE_DIR
ROOT_EXE = APP_SHELL_DIR / 'SecurityTestingEngine.exe'
START_HERE = APP_SHELL_DIR / 'README - Start Here.txt'


def start_here_text() -> str:
    lines = [
        'Security Testing Engine v8',
        '',
        'Double-click SecurityTestingEngine.exe to study.',
        '',
        'What is in this folder:',
        '- SecurityTestingEngine.exe: the app you run.',
    ]
    if LEGACY_LAYOUT:
        lines.append('- Project Files: source code, tests, banks, tools, reports, and build files.')
    else:
        lines.append('- Source files, banks, tests, tools, and reports live alongside the executable in this checkout.')
    lines.extend(
        [
            '',
            'Progress and history:',
            '- The packaged EXE stores XP, history, sessions, and settings in:',
            '  %LOCALAPPDATA%\\SecurityTestingEngine',
            '- The app can automatically import older progress from user_data or the older Project Files\\user_data layout when the packaged EXE has little or no progress.',
            '',
            'For normal use, you only need SecurityTestingEngine.exe.',
        ]
    )
    return '\n'.join(lines)


def copy_required(src: Path, dst: Path):
    if not src.exists():
        raise FileNotFoundError(f'Missing required release file: {src}')
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build_release(_bank_path=None):
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True)
    copy_required(DIST_DIR / 'SecurityTestingEngine.exe', RELEASE_DIR / 'SecurityTestingEngine.exe')
    copy_required(DIST_DIR / 'SecurityTestingEngine.exe', ROOT_EXE)
    START_HERE.write_text(start_here_text(), encoding='utf-8')
    return RELEASE_DIR


def main():
    path = build_release()
    print(f'Release folder ready: {path}')


if __name__ == '__main__':
    main()
