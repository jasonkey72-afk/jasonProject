@echo off
REM ============================================================
REM AI Studio (업무 자동화 통합 도구) - Windows 실행파일(exe) 빌드 스크립트
REM
REM 사전 준비:
REM   1) Windows PC 에 Python 3.9 이상 설치
REM   2) 만든 exe 를 실제로 쓰려면 그 PC 에 Microsoft Excel / PowerPoint 설치
REM      (MP4 → GIF, 이름 목록 기능은 Office 없이도 동작합니다)
REM
REM 사용법:
REM   1) 이 폴더에서 build.bat 을 더블클릭 (또는 cmd 에서 실행)
REM   2) 빌드가 끝나면 dist\AI_Studio.exe 파일이 만들어집니다
REM   3) 그 exe 파일 하나만 부서원들에게 복사해 주면 됩니다
REM      (받는 사람은 Python 설치가 필요 없습니다)
REM ============================================================

setlocal

echo [1/4] 필요한 패키지를 설치합니다...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo 패키지 설치에 실패했습니다. Python 이 설치되어 있는지 확인해 주세요.
    pause
    exit /b 1
)

echo [2/4] pywin32 설치 후처리 스크립트를 실행합니다...
python -m pywin32_postinstall -install >nul 2>nul

echo [3/4] 통합 프로그램을 빌드합니다... (ffmpeg 포함, 수 분 걸릴 수 있습니다)
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "AI_Studio" ^
    --collect-binaries imageio_ffmpeg ^
    --hidden-import win32com.client ^
    --hidden-import pythoncom ^
    ai_studio.py

if errorlevel 1 (
    echo 빌드에 실패했습니다. 위의 오류 메시지를 확인해 주세요.
    pause
    exit /b 1
)

echo [4/4] (선택) 예전 Excel 전용 프로그램도 빌드하려면 아래 주석을 해제하세요.
REM python -m PyInstaller --noconfirm --onefile --windowed ^
REM     --name "Excel_to_PDF_변환기" excel_to_pdf_converter.py

echo.
echo 빌드가 완료되었습니다.
echo   결과물: dist\AI_Studio.exe
echo   이 파일만 부서원들에게 배포하면 됩니다.
echo.
pause
