@echo off
REM ============================================================
REM 이미지 OCR 변환기 - Windows 실행파일(exe) 빌드 스크립트
REM
REM 사전 준비:
REM   1) Windows PC에 Python 3.9 이상 설치
REM   2) Tesseract-OCR 엔진 설치 (빌드 자체에는 필요 없지만,
REM      만든 exe를 실행/테스트하려면 필요합니다)
REM      https://github.com/UB-Mannheim/tesseract/wiki
REM
REM 사용법:
REM   1) 이 폴더에서 build_ocr.bat 파일을 더블클릭 (또는 cmd에서 실행)
REM   2) 빌드가 끝나면 dist\이미지_OCR_변환기.exe 파일이 생성됩니다
REM   3) 그 exe 파일 하나만 부서원들에게 복사해서 배포하면 됩니다
REM      (부서원 PC에는 Python 설치가 필요 없고, Tesseract-OCR만 있으면 됩니다)
REM ============================================================

setlocal

echo [1/3] 필요한 패키지를 설치합니다...
python -m pip install --upgrade pip
python -m pip install pytesseract Pillow pyinstaller
if errorlevel 1 (
    echo 패키지 설치에 실패했습니다. Python이 설치되어 있는지 확인해 주세요.
    pause
    exit /b 1
)

echo [2/3] 실행파일을 빌드합니다...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "이미지_OCR_변환기" ^
    image_ocr_converter.py

if errorlevel 1 (
    echo 빌드에 실패했습니다. 위의 오류 메시지를 확인해 주세요.
    pause
    exit /b 1
)

echo.
echo 빌드가 완료되었습니다.
echo   결과물: dist\이미지_OCR_변환기.exe
echo   이 파일만 부서원들에게 배포하면 됩니다.
echo   (실행하는 PC에는 Tesseract-OCR 엔진이 설치되어 있어야 합니다)
echo.
pause
