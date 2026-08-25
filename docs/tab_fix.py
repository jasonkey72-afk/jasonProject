"""
tab_fix.py - "클릭했더니 새 탭이 열렸는데 다음 단계에서 못 찾음" 해결 모듈
==========================================================================
Selenium 을 쓰는 어떤 코드에도 이 파일 하나만 넣고 import 하면 됩니다.
(추가 설치 필요 없음, selenium 만 있으면 됨)

    from tab_fix import find_anywhere, click_anywhere, wait_new_tab, debug_tabs

핵심
    요소를 못 찾는 문제가 아니라 "어느 탭을 보고 있는가" 의 문제입니다.
    find_anywhere() 는 **모든 탭 x 모든 프레임**을 훑고, 찾은 자리에 머무릅니다.
    그래서 탭이 몇 번째에 열리든, 몇 초 뒤에 열리든 상관없어집니다.
"""

import time

from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException, WebDriverException,
)


# ---------------------------------------------------------------------------
# 0. 진단 - 먼저 이것부터 찍어 보세요
# ---------------------------------------------------------------------------

def debug_tabs(driver):
    """지금 열려 있는 탭을 모두 출력한다. 원인이 바로 갈린다."""
    current = None
    try:
        current = driver.current_window_handle
    except WebDriverException:
        pass

    handles = driver.window_handles
    print("=" * 60)
    print("열린 탭: %d개" % len(handles))
    for i, h in enumerate(handles):
        try:
            driver.switch_to.window(h)
            mark = " <-- 지금 보고 있는 탭" if h == current else ""
            print("  [%d] %s | %s%s" % (i, driver.title, driver.current_url, mark))
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            if frames:
                print("       (이 탭 안에 iframe %d개)" % len(frames))
        except WebDriverException as e:
            print("  [%d] 읽기 실패: %s" % (i, e))
    print("=" * 60)

    if current:
        try:
            driver.switch_to.window(current)
        except WebDriverException:
            pass
    return handles


# ---------------------------------------------------------------------------
# 1. 프레임(iframe) 전체 탐색
# ---------------------------------------------------------------------------

def find_in_frames(driver, by, value, depth=0, max_depth=3):
    """현재 문서 -> 모든 iframe 을 깊이 우선으로 훑는다. 찾으면 그 프레임에 머무른다."""
    try:
        els = [e for e in driver.find_elements(by, value) if _usable(e)]
        if els:
            return els[0]
    except WebDriverException:
        return None

    if depth >= max_depth:
        return None

    try:
        count = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
    except WebDriverException:
        return None

    for i in range(count):
        try:
            # 프레임 목록은 이동할 때마다 무효화되므로 매번 다시 읽는다
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            if i >= len(frames):
                break
            driver.switch_to.frame(frames[i])
        except WebDriverException:
            continue

        found = find_in_frames(driver, by, value, depth + 1, max_depth)
        if found is not None:
            return found

        try:
            driver.switch_to.parent_frame()
        except WebDriverException:
            return None
    return None


def _usable(el):
    """보이고 크기가 있는 요소인지."""
    try:
        if not el.is_displayed():
            return False
        size = el.size
        return size.get("width", 0) > 1 and size.get("height", 0) > 1
    except (StaleElementReferenceException, WebDriverException):
        return False


# ---------------------------------------------------------------------------
# 2. 모든 탭 x 모든 프레임 탐색  <-- 이것이 해결책의 핵심
# ---------------------------------------------------------------------------

def find_anywhere(driver, by, value, timeout=30, verbose=True):
    """
    열려 있는 **모든 탭의 모든 프레임**에서 요소를 찾는다.
    찾으면 그 탭/프레임에 머무른 채로 요소를 돌려주므로,
    이후 click() 등을 바로 이어서 하면 된다.
    """
    end = time.time() + timeout
    start_handle = None
    try:
        start_handle = driver.current_window_handle
    except WebDriverException:
        pass

    while True:
        handles = list(driver.window_handles)
        # 최근에 열린 탭부터 본다(새 탭이 보통 정답이다)
        for handle in reversed(handles):
            try:
                driver.switch_to.window(handle)
                driver.switch_to.default_content()
            except WebDriverException:
                continue

            _wait_ready(driver, 3)
            el = find_in_frames(driver, by, value)
            if el is not None:
                if verbose:
                    print("[tab_fix] 찾음 -> 탭 '%s'" % driver.title)
                return el

        if time.time() >= end:
            break
        time.sleep(0.5)

    # 못 찾았으면 원래 탭으로 되돌려 둔다
    if start_handle:
        try:
            driver.switch_to.window(start_handle)
            driver.switch_to.default_content()
        except WebDriverException:
            pass

    raise NoSuchElementException(
        "어느 탭에서도 찾지 못했습니다: %s=%s (열린 탭 %d개, %.0f초 대기)"
        % (by, value, len(driver.window_handles), timeout))


def click_anywhere(driver, by, value, timeout=30, verbose=True):
    """find_anywhere 로 찾아서 클릭한다. 가려져 있으면 스크롤 후 재시도."""
    el = find_anywhere(driver, by, value, timeout, verbose)
    for attempt in range(3):
        try:
            el.click()
            return el
        except WebDriverException:
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", el)
            except WebDriverException:
                pass
            time.sleep(0.4)
    # 마지막 수단. 단, 이 클릭이 새 탭을 여는 버튼이면 팝업 차단에 막힐 수 있다.
    driver.execute_script("arguments[0].click();", el)
    return el


# ---------------------------------------------------------------------------
# 3. 새 탭을 명시적으로 기다렸다가 전환
# ---------------------------------------------------------------------------

def wait_new_tab(driver, before_handles, timeout=30, verbose=True):
    """
    before_handles 에 없던 새 탭이 열릴 때까지 기다렸다가 그 탭으로 전환한다.
    before_handles 는 **클릭하기 전에** driver.window_handles 로 저장해 둔 목록.
    """
    before = set(before_handles or [])
    end = time.time() + timeout
    while time.time() < end:
        new = [h for h in driver.window_handles if h not in before]
        if new:
            driver.switch_to.window(new[-1])
            driver.switch_to.default_content()
            _wait_ready(driver, 30)
            if verbose:
                print("[tab_fix] 새 탭으로 이동 -> '%s'" % driver.title)
            return driver.current_window_handle
        time.sleep(0.3)

    raise NoSuchElementException(
        "새 탭이 %.0f초 안에 열리지 않았습니다. 탭 %d개 (팝업 차단 여부를 확인하세요)"
        % (timeout, len(driver.window_handles)))


def switch_tab_by(driver, text, timeout=15, verbose=True):
    """제목이나 주소에 text 가 들어간 탭으로 전환한다."""
    end = time.time() + timeout
    while time.time() < end:
        for handle in reversed(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                if text in (driver.title or "") or text in (driver.current_url or ""):
                    driver.switch_to.default_content()
                    _wait_ready(driver, 30)
                    if verbose:
                        print("[tab_fix] '%s' 탭으로 이동" % driver.title)
                    return handle
            except WebDriverException:
                continue
        time.sleep(0.3)
    raise NoSuchElementException("'%s' 에 해당하는 탭이 없습니다." % text)


def _wait_ready(driver, timeout=10):
    """document.readyState 가 complete 가 될 때까지 기다린다."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if driver.execute_script("return document.readyState") == "complete":
                return True
        except WebDriverException:
            return False
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------------------
# 4. 사용 예시
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(__doc__)
    print("""
사용 예시
---------
from selenium import webdriver
from selenium.webdriver.common.by import By
from tab_fix import find_anywhere, click_anywhere, wait_new_tab, debug_tabs

driver = webdriver.Edge()

# 1단계
driver.get("https://portal.company.com")

# 2단계 - 새 탭을 여는 버튼
before = driver.window_handles          # 클릭 "전"에 저장 (방법 B 를 쓸 때만 필요)
driver.find_element(By.LINK_TEXT, "상세보기").click()

# 3단계 - 아래 둘 중 하나
#   방법 A (권장) : 탭을 신경 쓰지 않는다. 모든 탭에서 알아서 찾는다.
click_anywhere(driver, By.XPATH, "//button[normalize-space()='최종승인']")

#   방법 B : 새 탭을 명시적으로 기다렸다가 전환한 뒤 평소대로 진행
# wait_new_tab(driver, before, timeout=30)
# driver.find_element(By.XPATH, "//button[normalize-space()='최종승인']").click()

# 안 될 때는 이것부터
# debug_tabs(driver)
""")
