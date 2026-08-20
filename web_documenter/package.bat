@echo off
REM ============================================================
REM 웹 본문 문서화 도구 - 배포용 ZIP 만들기
REM
REM 코드를 수정한 뒤 이 파일을 더블클릭하면
REM package\web_documenter_v[버전].zip 파일이 새로 만들어집니다.
REM 그 ZIP 하나만 부서원들에게 전달하면 됩니다.
REM (검증용 test 폴더는 배포본에 포함하지 않습니다)
REM ============================================================

setlocal
set VERSION=1.1.1
set NAME=web_documenter
set STAGE=%TEMP%\%NAME%_pkg
set OUT=%~dp0package\%NAME%_v%VERSION%.zip

echo [1/3] 배포 파일을 모읍니다...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%\%NAME%\icons"

for %%F in (manifest.json background.js content.js popup.html popup.css popup.js print.html print.js README.md 설치방법.txt) do (
    copy /y "%~dp0%%F" "%STAGE%\%NAME%\" >nul || goto :fail
)
copy /y "%~dp0icons\*.png" "%STAGE%\%NAME%\icons\" >nul || goto :fail

echo [2/3] 이전 ZIP 파일을 정리합니다...
if not exist "%~dp0package" mkdir "%~dp0package"
if exist "%OUT%" del /q "%OUT%"

echo [3/3] ZIP 파일을 만듭니다...
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\%NAME%' -DestinationPath '%OUT%' -Force" || goto :fail
rmdir /s /q "%STAGE%"

echo.
echo 완료되었습니다.
echo   결과물: %OUT%
echo   이 파일 하나만 배포하면 됩니다.
echo.
pause
exit /b 0

:fail
echo.
echo 만들기에 실패했습니다. 위의 오류 메시지를 확인해 주세요.
pause
exit /b 1
