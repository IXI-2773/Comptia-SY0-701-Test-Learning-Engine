@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw app.py
  goto :eof
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw app.py
  goto :eof
)
where py >nul 2>nul
if %errorlevel%==0 (
  py app.py
  goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
  python app.py
  goto :eof
)
echo Python was not found. Use Anaconda Prompt, py launcher, or install Python.
pause
