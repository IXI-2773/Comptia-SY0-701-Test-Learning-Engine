import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = BASE_DIR / 'dist'
RELEASE_DIR = BASE_DIR / 'release' / 'SecurityTestingEngine'
APP_SHELL_DIR = BASE_DIR.parent if BASE_DIR.name == 'Project Files' else BASE_DIR
ROOT_EXE = APP_SHELL_DIR / 'SecurityTestingEngine.exe'
START_HERE = APP_SHELL_DIR / 'README - Start Here.txt'
START_HERE_TEXT = """Security Testing Engine v8

Double-click SecurityTestingEngine.exe to study.

What is in this folder:
- SecurityTestingEngine.exe: the app you run.
- Project Files: source code, tests, banks, tools, reports, and build files.

Progress and history:
- The packaged EXE stores XP, history, sessions, and settings in:
  %LOCALAPPDATA%\\SecurityTestingEngine
- The app can automatically import older progress from Project Files\\user_data when the packaged EXE has little or no progress.

For normal use, you only need SecurityTestingEngine.exe.
"""


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
    START_HERE.write_text(START_HERE_TEXT, encoding='utf-8')
    return RELEASE_DIR


def main():
    path = build_release()
    print(f'Release folder ready: {path}')


if __name__ == '__main__':
    main()
