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

echo Running focused release tests...
%PYTHON_CMD% -m unittest -v tests.test_release_tools
if errorlevel 1 (
  echo Tests failed.
  pause
  exit /b 1
)

%PYTHON_CMD% -m pip install pyinstaller
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

%PYTHON_CMD% tools\build_release.py --prepare-build "%BANK_FILE%"
if errorlevel 1 (
  echo Build receipt preparation failed.
  pause
  exit /b 1
)

%PYTHON_CMD% -m PyInstaller --clean --noconfirm --onefile --windowed --name SecurityTestingEngine ^
  --add-data "%BANK_FILE%;." ^
  app.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

%PYTHON_CMD% tools\build_release.py --record-built "%BANK_FILE%"
if errorlevel 1 (
  echo Build receipt finalization failed.
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
