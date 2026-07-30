@echo off
REM ============================================================
REM Spotfire(.dxp) to Excel 변환/검색 도구 - Windows 실행파일(exe) 빌드 스크립트
REM
REM 사전 준비:
REM   1) Windows PC에 Python 3.9 이상 설치
REM   (Spotfire나 Microsoft Excel이 설치되어 있지 않아도 빌드/실행 가능합니다)
REM
REM 사용법:
REM   1) 이 폴더에서 build_spotfire_converter.bat 파일을 더블클릭 (또는 cmd에서 실행)
REM   2) 빌드가 끝나면 dist\Spotfire_dxp_Excel_변환기.exe 파일이 생성됩니다
REM   3) 그 exe 파일 하나만 부서원들에게 복사해서 배포하면 됩니다
REM      (부서원 PC에는 Python, Spotfire, Excel 설치가 필요 없습니다)
REM ============================================================

setlocal

echo [1/2] 필요한 패키지를 설치합니다...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo 패키지 설치에 실패했습니다. Python이 설치되어 있는지 확인해 주세요.
    pause
    exit /b 1
)

echo [2/2] 실행파일을 빌드합니다...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "Spotfire_dxp_Excel_변환기" ^
    spotfire_dxp_converter.py

if errorlevel 1 (
    echo 빌드에 실패했습니다. 위의 오류 메시지를 확인해 주세요.
    pause
    exit /b 1
)

echo.
echo 빌드가 완료되었습니다.
echo   결과물: dist\Spotfire_dxp_Excel_변환기.exe
echo   이 파일만 부서원들에게 배포하면 됩니다.
echo.
pause
