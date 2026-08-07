"""
브라우저 실행 / 접속 (드라이버 없음)
=====================================
설치된 Edge(또는 Chrome)를 디버깅 포트와 함께 직접 실행하고,
그 포트로 CDP 연결 주소를 알아낸다.

  · msedgedriver.exe / chromedriver.exe 를 쓰지 않는다 -> 버전 문제가 없다
  · 사용자가 이미 쓰고 있는 Edge 창은 건드리지 않는다(전용 프로필로 별도 실행)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from .client import CDPClient, CDPError

# 설치 경로를 못 찾을 때 확인할 표준 위치
EXE_CANDIDATES = {
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
}

APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s"
EXE_NAME = {"edge": "msedge.exe", "chrome": "chrome.exe"}

# 리눅스/맥에서 개발·시험할 때 쓰는 경로 (사내 배포는 윈도우)
POSIX_CANDIDATES = {
    "edge": ["microsoft-edge", "microsoft-edge-stable"],
    "chrome": ["google-chrome", "chromium", "chromium-browser"],
}


def find_browser(browser: str) -> str:
    """브라우저 실행 파일 경로를 찾는다. 못 찾으면 빈 문자열."""
    override = os.environ.get("JOBSCN_BROWSER_PATH", "")
    if override and Path(override).exists():
        return override

    if os.name == "nt":
        try:
            import winreg
            name = EXE_NAME.get(browser, "msedge.exe")
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, APP_PATHS_KEY % name) as k:
                        path = str(winreg.QueryValueEx(k, "")[0]).strip('"')
                        if Path(path).exists():
                            return path
                except OSError:
                    continue
        except Exception:
            pass
        for path in EXE_CANDIDATES.get(browser, []):
            if Path(path).exists():
                return path
        return ""

    import shutil
    for name in POSIX_CANDIDATES.get(browser, []):
        found = shutil.which(name)
        if found:
            return found
    return ""


def free_port() -> int:
    """비어 있는 포트 하나를 고른다."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_json(url: str, timeout: float = 2.0):
    """localhost 요청이 사내 프록시로 새어 나가지 않도록 프록시를 끄고 호출한다."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_endpoint(port: int, timeout: float = 40.0) -> dict:
    """브라우저가 디버깅 포트를 열 때까지 기다린 뒤 접속 정보를 돌려준다."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return _http_json("http://127.0.0.1:%d/json/version" % port)
        except Exception as e:
            last = e
            time.sleep(0.3)
    raise CDPError("브라우저가 디버깅 포트(%d)를 열지 않았습니다: %s" % (port, last))


def launch(browser: str = "edge", user_data_dir: str = "", headless: bool = False,
           port: int = 0, extra_args=None, log=None):
    """
    브라우저를 실행하고 (CDPClient, Popen, port) 를 돌려준다.
    port 를 지정하면 이미 그 포트로 열려 있는 브라우저에 그냥 연결한다.
    """
    browser = (browser or "edge").lower()

    # 이미 열려 있는 브라우저에 붙는 경우
    if port:
        info = wait_endpoint(port, timeout=5)
        if log:
            log("이미 열려 있는 브라우저에 연결했습니다. (%s)" % info.get("Browser", ""))
        return CDPClient(info["webSocketDebuggerUrl"]), None, port

    exe = find_browser(browser)
    if not exe:
        raise CDPError(
            "%s 를 찾을 수 없습니다.\n"
            "설치되어 있는지 확인해 주세요. 설치 경로가 특이한 경우에는\n"
            "환경변수 JOBSCN_BROWSER_PATH 에 실행 파일 경로를 지정할 수 있습니다."
            % ("Microsoft Edge" if browser == "edge" else "Google Chrome"))

    port = free_port()
    args = [
        exe,
        "--remote-debugging-port=%d" % port,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-notifications",
        "--disable-features=Translate",
        # 사용자가 쓰고 있는 창과 섞이지 않게 별도 인스턴스로 띄운다
        "--remote-allow-origins=*",
    ]
    if user_data_dir:
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        args.append("--user-data-dir=%s" % user_data_dir)
    if headless:
        args.append("--headless=new")
    else:
        args.append("--start-maximized")
    if os.name != "nt":
        args += ["--no-sandbox", "--disable-dev-shm-usage"]
    if extra_args:
        args += list(extra_args)
    args.append("about:blank")

    if log:
        log("브라우저를 실행합니다 (드라이버 없이 직접 연결): %s" % Path(exe).name)
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=creationflags)

    info = wait_endpoint(port)
    if log:
        log("연결됨: %s" % info.get("Browser", ""))
    return CDPClient(info["webSocketDebuggerUrl"]), proc, port
