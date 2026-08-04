"""
브라우저(Edge / Chrome) 실행 및 연결 담당 모듈.

사내 환경을 고려한 설계
  - 전용 프로필 폴더를 사용한다 -> 한 번 로그인해 두면 다음 실행 때도 유지된다.
  - 드라이버 파일(msedgedriver.exe)이 exe 옆에 있으면 그것을 먼저 쓴다.
    (사내망에서 자동 다운로드가 막혀 있어도 동작하게 하기 위함)
  - 이미 띄워 둔 브라우저에 붙는 방식(디버깅 포트)도 지원한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

BROWSERS = ("edge", "chrome")

DRIVER_FILES = {
    "edge": "msedgedriver.exe",
    "chrome": "chromedriver.exe",
}


def app_dir() -> Path:
    """exe 로 배포됐을 때는 exe 가 있는 폴더, 개발 중에는 프로젝트 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """시나리오/설정/프로필을 저장할 사용자 폴더."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "jobScenario"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _local_driver(browser: str) -> str | None:
    """exe 옆에 드라이버 파일이 있으면 그 경로를 돌려준다."""
    name = DRIVER_FILES.get(browser)
    if not name:
        return None
    for folder in (app_dir(), app_dir() / "driver", data_dir()):
        p = folder / name
        if p.exists():
            return str(p)
    return None


def create_driver(browser: str = "edge", profile: bool = True,
                  download_dir: str = "", attach_port: int = 0,
                  headless: bool = False):
    """
    브라우저를 띄우고 WebDriver 를 돌려준다.

      browser      : "edge" 또는 "chrome"
      profile      : True 면 전용 프로필 사용(로그인 상태 유지)
      download_dir : 파일 내려받기 폴더
      attach_port  : 0 이 아니면 이미 열려 있는 브라우저에 연결
      headless     : 화면 없이 실행(사내 사이트는 보통 False 권장)
    """
    browser = (browser or "edge").lower()
    if browser not in BROWSERS:
        browser = "edge"

    is_edge = browser == "edge"
    options = EdgeOptions() if is_edge else ChromeOptions()

    if attach_port:
        # 이미 실행 중인 브라우저에 붙는다(로그인/보안 프로그램이 걸린 사이트에 유용)
        options.add_experimental_option("debuggerAddress", "127.0.0.1:%d" % int(attach_port))
    else:
        if profile:
            prof = data_dir() / ("edge_profile" if is_edge else "chrome_profile")
            prof.mkdir(parents=True, exist_ok=True)
            options.add_argument("--user-data-dir=%s" % prof)
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        if download_dir:
            Path(download_dir).mkdir(parents=True, exist_ok=True)
            prefs["download.default_directory"] = str(download_dir)
            prefs["download.prompt_for_download"] = False
        options.add_experimental_option("prefs", prefs)

    driver_path = _local_driver(browser)
    if is_edge:
        service = EdgeService(executable_path=driver_path) if driver_path else EdgeService()
        driver = webdriver.Edge(service=service, options=options)
    else:
        service = ChromeService(executable_path=driver_path) if driver_path else ChromeService()
        driver = webdriver.Chrome(service=service, options=options)

    driver.set_page_load_timeout(120)
    return driver


def quit_driver(driver) -> None:
    """예외를 삼키며 안전하게 브라우저를 닫는다."""
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass
