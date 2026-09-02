@echo off
REM Start the PDF -> Confluence-ready Word converter on Windows.
REM First run creates a virtualenv and installs dependencies; later runs just start.
REM
REM Setup is written as plain lines with a goto instead of one big if-block:
REM cmd.exe expands %PY% when it parses a block, before "set PY=" has run,
REM so "%PY% -m venv" inside the block would turn into a bare "-m venv".
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :start

set "PY="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python 3.10 or newer is required.
    echo Install it from https://www.python.org/downloads/ or run: winget install Python.Python.3.13
    exit /b 1
)

echo Setting up ^(one time only^) using %PY% ...
%PY% -m venv .venv || exit /b 1
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet pymupdf python-docx pillow || exit /b 1
REM Optional API backends; only used when the matching key is set.
".venv\Scripts\python.exe" -m pip install --quiet anthropic openai >nul 2>&1
echo Setup complete.

:start
".venv\Scripts\python.exe" server.py %*
