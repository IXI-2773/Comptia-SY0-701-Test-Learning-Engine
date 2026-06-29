@echo off
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set PYTHON_CMD=py
  goto :have_python
)

where python >nul 2>nul
if %errorlevel%==0 (
  set PYTHON_CMD=python
  goto :have_python
)

echo Python was not found.
pause
exit /b 1

:have_python
if "%~1"=="" (
  set BANK_FILE=public_sy0701_bank_v4_plus_studyguide_clean.json
) else (
  set BANK_FILE=%~1
)

echo Running bank validation...
%PYTHON_CMD% tools\validate_bank.py "%BANK_FILE%"
if errorlevel 1 (
  echo Bank validation failed.
  pause
  exit /b 1
)

echo Running tests...
%PYTHON_CMD% -m unittest discover -s tests -v
if errorlevel 1 (
  echo Tests failed.
  pause
  exit /b 1
)

%PYTHON_CMD% -m pip install pyinstaller
%PYTHON_CMD% -m PyInstaller --onefile --windowed --name SecurityTestingEngine ^
  --add-data "%BANK_FILE%;." ^
  app.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

%PYTHON_CMD% tools\build_release.py "%BANK_FILE%"
if errorlevel 1 (
  echo Release packaging failed.
  pause
  exit /b 1
)

echo Running smoke test...
%PYTHON_CMD% tools\smoke_test.py
if errorlevel 1 (
  echo Smoke test failed.
  pause
  exit /b 1
)

echo Build finished.
echo EXE path: dist\SecurityTestingEngine.exe
echo Release folder: release\SecurityTestingEngine
pause
