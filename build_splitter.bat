@echo off
REM ============================================================
REM  Office File Splitter - build the Windows exe
REM
REM  IMPORTANT (for maintainers):
REM  Keep this file ASCII-only and CRLF.  cmd.exe reads .bat files
REM  with the OEM code page (949 on Korean Windows), so UTF-8 Korean
REM  text or LF-only line endings break the file and cause
REM  "not recognized as an internal or external command" errors.
REM  All Korean messages and the real work live in build_exe.py.
REM ============================================================

setlocal
cd /d "%~dp0"

set "PYCMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)

if defined PYCMD (
    %PYCMD% "build_exe.py" splitter
) else (
    echo.
    echo [ERROR] Python was not found on this PC.
    echo         Python 3.9 or newer is required to build the exe.
    echo         Download: https://www.python.org/downloads/
    echo         Turn ON "Add python.exe to PATH" in the installer.
    echo.
    if exist "docs\help_python_ko.txt" (
        chcp 65001 >nul
        type "docs\help_python_ko.txt"
    )
)

echo.
pause
