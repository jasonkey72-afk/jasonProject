@echo off
REM ============================================================
REM Excel to PDF 변환기 - Windows 실행파일(exe) 빌드 스크립트
REM
REM 사전 준비:
REM   1) Windows PC에 Python 3.9 이상 설치
REM   2) 이 PC에 Microsoft Excel 설치 (빌드 자체에는 필요 없지만,
REM      만든 exe를 실행/테스트하려면 필요합니다)
REM
REM 사용법:
REM   1) 이 폴더에서 build.bat 파일을 더블클릭 (또는 cmd에서 실행)
REM   2) 빌드가 끝나면 dist\Excel_to_PDF_변환기.exe 파일이 생성됩니다
REM   3) 그 exe 파일 하나만 부서원들에게 복사해서 배포하면 됩니다
REM      (부서원 PC에는 Python 설치가 필요 없고, Microsoft Excel만 있으면 됩니다)
REM ============================================================

setlocal

echo [1/3] 필요한 패키지를 설치합니다...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo 패키지 설치에 실패했습니다. Python이 설치되어 있는지 확인해 주세요.
    pause
    exit /b 1
)

echo [2/3] pywin32 설치 후처리 스크립트를 실행합니다...
python -m pywin32_postinstall -install >nul 2>nul

echo [3/3] 실행파일을 빌드합니다...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "Excel_to_PDF_변환기" ^
    excel_to_pdf_converter.py

if errorlevel 1 (
    echo 빌드에 실패했습니다. 위의 오류 메시지를 확인해 주세요.
    pause
    exit /b 1
)

echo.
echo 빌드가 완료되었습니다.
echo   결과물: dist\Excel_to_PDF_변환기.exe
echo   이 파일만 부서원들에게 배포하면 됩니다.
echo.
pause
