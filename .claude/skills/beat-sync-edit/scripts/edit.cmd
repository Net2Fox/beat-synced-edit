@echo off
rem Run the beat-sync-edit CLI with the skill's own .venv; needs no shell state.
rem   edit COMMAND [ARGS...]        -> edit_project.py COMMAND ...
rem   edit tool TOOL.py [ARGS...]   -> a bundled helper such as beat_map.py
rem BEAT_SYNC_PYTHON overrides the interpreter.
setlocal
set "here=%~dp0"
if "%here:~-1%"=="\" set "here=%here:~0,-1%"
for %%I in ("%here%") do set "base=%%~nxI"
set "root=%here%"
if /I "%base%"=="scripts" for %%I in ("%here%\..") do set "root=%%~fI"
set "py=%BEAT_SYNC_PYTHON%"
if not defined py set "py=%root%\.venv\Scripts\python.exe"
if not defined BEAT_SYNC_PYTHON if not exist "%py%" (
  echo beat-sync-edit: no environment at "%root%\.venv". Run: python "%here%\bootstrap.py" 1>&2
  exit /b 3
)
"%py%" -X utf8 "%here%\edit_project.py" %*
exit /b %ERRORLEVEL%
