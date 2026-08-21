@echo off
REM ============================================================
REM Office 파일 분할기 - Windows 실행파일(exe) 빌드 스크립트
REM
REM 사전 준비:
REM   Windows PC에 Python 3.9 이상 설치 (Microsoft Office는 필요 없습니다)
REM
REM 사용법:
REM   1) 이 폴더에서 build_splitter.bat 파일을 더블클릭 (또는 cmd에서 실행)
REM   2) 빌드가 끝나면 dist\Office_파일_분할기.exe 파일이 생성됩니다
REM   3) 그 exe 파일 하나만 부서원들에게 복사해서 배포하면 됩니다
REM      (부서원 PC에는 Python도, Office도 설치할 필요가 없습니다)
REM ============================================================

setlocal

echo [1/3] 필요한 패키지를 설치합니다...
python -m pip install --upgrade pip
python -m pip install openpyxl python-docx python-pptx pyinstaller
if errorlevel 1 (
    echo 패키지 설치에 실패했습니다. Python이 설치되어 있는지 확인해 주세요.
    pause
    exit /b 1
)

echo [2/3] 드래그 앤 드롭 기능을 설치합니다 (실패해도 프로그램은 동작합니다)...
python -m pip install tkinterdnd2
python -c "import tkinterdnd2" >nul 2>nul
if errorlevel 1 (
    set "DND="
    echo     - tkinterdnd2 를 사용할 수 없어 드래그 앤 드롭 없이 빌드합니다.
) else (
    set "DND=--collect-all tkinterdnd2"
    echo     - 드래그 앤 드롭을 포함해서 빌드합니다.
)

echo [3/3] 실행파일을 빌드합니다...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "Office_파일_분할기" ^
    --collect-data docx ^
    --collect-data pptx ^
    --collect-data openpyxl ^
    %DND% ^
    office_file_splitter.py

if errorlevel 1 (
    echo 빌드에 실패했습니다. 위의 오류 메시지를 확인해 주세요.
    pause
    exit /b 1
)

echo.
echo 빌드가 완료되었습니다.
echo   결과물: dist\Office_파일_분할기.exe
echo   이 파일만 부서원들에게 배포하면 됩니다.
echo.
pause
