"""
고수준 웹 동작 모음
====================
'클릭이 가끔 안 먹는다', '입력이 지워지지 않는다', '새 창이 떠서 멈춘다' 같은
실무에서 반복되는 실패를 모두 이 안에서 흡수한다.
SmartLocator 와 함께 다른 프로젝트에 그대로 옮겨 쓸 수 있다.
"""

from __future__ import annotations

import time
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    UnexpectedAlertPresentException,
    NoAlertPresentException,
    WebDriverException,
)

from .locator import SmartLocator, ElementNotFound, parse_target

KEY_MAP = {
    "enter": Keys.ENTER, "tab": Keys.TAB, "esc": Keys.ESCAPE,
    "escape": Keys.ESCAPE, "space": Keys.SPACE, "backspace": Keys.BACK_SPACE,
    "delete": Keys.DELETE, "up": Keys.ARROW_UP, "down": Keys.ARROW_DOWN,
    "left": Keys.ARROW_LEFT, "right": Keys.ARROW_RIGHT,
    "pageup": Keys.PAGE_UP, "pagedown": Keys.PAGE_DOWN,
    "home": Keys.HOME, "end": Keys.END, "f5": Keys.F5,
}

SET_VALUE_JS = """
var el = arguments[0], v = arguments[1];
var proto = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
var setter = Object.getOwnPropertyDescriptor(proto, 'value');
if (setter && setter.set) { setter.set.call(el, v); } else { el.value = v; }
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
"""


class WebActions:
    """드라이버 하나에 대한 동작 묶음."""

    engine_name = "selenium"

    def __init__(self, driver, timeout: float = 15.0, log=None):
        self.driver = driver
        self.locator = SmartLocator(driver, default_timeout=timeout)
        self.log = log or (lambda msg: None)

    # -- 기본 --------------------------------------------------------------

    def find(self, target, timeout=None, visible_only=True):
        try:
            return self.locator.find(target, timeout=timeout, visible_only=visible_only,
                                     log=self.log)
        except ElementNotFound:
            # 현재 탭에 없으면 다른 탭도 찾아본다.
            # 버튼을 눌러 새 탭이 열렸는데 자동화는 원래 탭에 남아 있는 경우가 많다.
            el = self._find_in_other_tabs(target, visible_only)
            if el is not None:
                return el
            raise

    def _find_in_other_tabs(self, target, visible_only):
        """열려 있는 다른 탭을 최근 것부터 훑어보고, 찾으면 그 탭에 머무른다."""
        try:
            current = self.driver.current_window_handle
            handles = self.driver.window_handles
        except WebDriverException:
            return None
        if len(handles) <= 1:
            return None

        for handle in reversed(handles):
            if handle == current:
                continue
            try:
                self.driver.switch_to.window(handle)
                self.driver.switch_to.default_content()
                self.wait_ready(5)
                el = self.locator.find(target, timeout=2.0, visible_only=visible_only)
            except (ElementNotFound, WebDriverException):
                continue
            self.log("  · 현재 탭에 없어 다른 탭에서 찾았습니다 → '%s' 탭으로 이동합니다."
                     % (self.title() or "")[:40])
            return el

        try:                                  # 어디에도 없으면 원래 탭으로 되돌린다
            self.driver.switch_to.window(current)
        except WebDriverException:
            pass
        return None

    # -- 엔진 공통 인터페이스 (cdp 판과 같은 이름으로 제공한다) ------------

    @property
    def alive(self) -> bool:
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    def quit(self):
        try:
            self.driver.quit()
        except Exception:
            pass

    def title(self) -> str:
        try:
            return self.driver.title or ""
        except WebDriverException:
            return ""

    def current_url(self) -> str:
        try:
            return self.driver.current_url or ""
        except WebDriverException:
            return ""

    def page_source(self) -> str:
        try:
            return self.driver.page_source or ""
        except WebDriverException:
            return ""

    def save_screenshot(self, path: str) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.driver.save_screenshot(str(path))
        return str(path)

    def pick_element(self, timeout: float = 180.0, on_status=None):
        from .picker import pick_element
        return pick_element(self.driver, timeout=timeout, on_status=on_status)

    def highlight(self, element):
        from .picker import flash
        flash(self.driver, element)

    def element_label(self, element) -> str:
        try:
            return "<%s> %s" % (element.tag_name, (element.text or "")[:30])
        except WebDriverException:
            return "요소"

    def open_url(self, url: str, timeout: float = 60.0):
        if not url:
            raise ValueError("주소(URL)가 비어 있습니다.")
        if "://" not in url:
            url = "https://" + url
        self.driver.get(url)
        self.wait_ready(timeout)

    def wait_ready(self, timeout: float = 30.0):
        """document.readyState 가 complete 가 될 때까지 기다린다."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.driver.execute_script("return document.readyState") == "complete":
                    return True
            except UnexpectedAlertPresentException:
                return True
            except WebDriverException:
                pass
            time.sleep(0.2)
        return False

    # -- 클릭 --------------------------------------------------------------

    def click(self, target, timeout=None, new_tab_wait: bool = True):
        """일반 클릭 -> 스크롤 후 클릭 -> JS 클릭 순으로 시도한다."""
        # 먼저 대상을 찾는다(찾는 과정에서 다른 탭으로 옮겨갈 수 있다)
        el = self.find(target, timeout)
        before = len(self.driver.window_handles)
        last = None
        for attempt in range(3):
            try:
                if attempt > 0:
                    self._scroll_into_view(el)
                el.click()
                last = None
                break
            except (ElementClickInterceptedException, ElementNotInteractableException) as e:
                last = e
                time.sleep(0.4)
            except StaleElementReferenceException:
                el = self.find(target, timeout)
                last = None
            except WebDriverException as e:
                last = e
                break
        if last is not None:
            # 팝업/레이어에 가려진 경우까지 처리하는 마지막 수단
            self.driver.execute_script("arguments[0].click();", el)

        if new_tab_wait:
            self._follow_new_tab(before)
        return True

    def double_click(self, target, timeout=None):
        from selenium.webdriver import ActionChains
        el = self.find(target, timeout)
        ActionChains(self.driver).double_click(el).perform()
        return True

    def hover(self, target, timeout=None):
        """메뉴가 마우스를 올려야 펼쳐지는 사이트에 사용한다."""
        from selenium.webdriver import ActionChains
        el = self.find(target, timeout)
        self._scroll_into_view(el)
        ActionChains(self.driver).move_to_element(el).perform()
        time.sleep(0.3)
        return True

    # -- 입력 --------------------------------------------------------------

    def input_text(self, target, text: str, timeout=None, clear: bool = True,
                   enter: bool = False):
        el = self.find(target, timeout)
        self._scroll_into_view(el)
        try:
            el.click()
        except WebDriverException:
            pass
        if clear:
            try:
                el.clear()
            except WebDriverException:
                pass
            try:
                el.send_keys(Keys.CONTROL, "a")
                el.send_keys(Keys.DELETE)
            except WebDriverException:
                pass
        try:
            el.send_keys(text)
        except WebDriverException:
            # 달력/금액 입력창처럼 직접 입력이 막힌 경우 값을 직접 넣어준다
            self.driver.execute_script(SET_VALUE_JS, el, text)
        if enter:
            el.send_keys(Keys.ENTER)
        return True

    def select_option(self, target, value: str, timeout=None):
        """콤보박스 선택. 화면 글자 -> value -> 순번 순으로 시도한다."""
        el = self.find(target, timeout)
        if el.tag_name.lower() != "select":
            # 흔히 쓰는 '가짜 콤보박스'는 클릭 후 항목을 글자로 찾는다
            self.click(target, timeout, new_tab_wait=False)
            time.sleep(0.3)
            return self.click("text=%s" % value, timeout, new_tab_wait=False)
        sel = Select(el)
        try:
            sel.select_by_visible_text(value)
        except WebDriverException:
            try:
                sel.select_by_value(value)
            except WebDriverException:
                sel.select_by_index(int(value))
        return True

    def set_checkbox(self, target, checked: bool = True, timeout=None):
        el = self.find(target, timeout)
        if bool(el.is_selected()) != bool(checked):
            try:
                el.click()
            except WebDriverException:
                self.driver.execute_script("arguments[0].click();", el)
        return True

    def press_key(self, key: str, target=None, timeout=None):
        k = KEY_MAP.get((key or "").strip().lower(), key)
        if target:
            self.find(target, timeout).send_keys(k)
        else:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(k)
        return True

    def upload_file(self, target, path: str, timeout=None):
        el = self.find(target, timeout, visible_only=False)
        el.send_keys(str(Path(path)))
        return True

    # -- 대기 / 확인 -------------------------------------------------------

    def wait_element(self, target, timeout=None):
        self.find(target, timeout)
        return True

    def wait_text(self, text: str, timeout: float = 30.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if text in self.driver.find_element(By.TAG_NAME, "body").text:
                    return True
            except WebDriverException:
                pass
            time.sleep(0.4)
        raise ElementNotFound("화면에서 '%s' 글자를 찾지 못했습니다." % text)

    def get_text(self, target, timeout=None) -> str:
        el = self.find(target, timeout)
        return (el.text or el.get_attribute("value") or "").strip()

    # -- 창 / 프레임 -------------------------------------------------------

    def switch_tab(self, spec=-1, timeout: float = 10.0):
        """
        탭 번호(-1 = 마지막) 또는 제목/주소의 일부로 탭을 고른다.
        아직 열리지 않았으면 지정한 시간까지 기다린다.
        """
        text = str(-1 if spec is None or spec == "" else spec).strip()
        try:
            index = int(text)
        except ValueError:
            index = None

        end = time.time() + max(timeout, 0.1)
        first = True
        while True:
            handles = self.driver.window_handles
            if index is not None:
                # '마지막 탭' 인데 아직 탭이 하나뿐이면 새 탭이 열리는 중일 수 있다
                waiting_for_new = (index == -1 and len(handles) < 2
                                   and (first or time.time() < end))
                if not waiting_for_new and handles and -len(handles) <= index < len(handles):
                    self.driver.switch_to.window(handles[index])
                    self.driver.switch_to.default_content()
                    self.wait_ready(20)
                    return True
            else:
                for handle in reversed(handles):
                    try:
                        self.driver.switch_to.window(handle)
                        if text in (self.driver.title or "") or \
                                text in (self.driver.current_url or ""):
                            self.driver.switch_to.default_content()
                            self.wait_ready(20)
                            return True
                    except WebDriverException:
                        continue
            first = False
            if time.time() >= end:
                handles = self.driver.window_handles
                if index is not None and handles:
                    self.driver.switch_to.window(handles[index])
                    self.driver.switch_to.default_content()
                    self.wait_ready(20)
                    return True
                break
            time.sleep(0.3)

        raise ElementNotFound("'%s' 에 해당하는 탭을 찾지 못했습니다." % text)

    def wait_new_tab(self, timeout: float = 15.0, match: str = ""):
        """
        새 탭이 열릴 때까지 기다렸다가 그 탭으로 이동한다.
        이미 새 탭으로 옮겨진 뒤라면 아무 일도 하지 않는다.
        """
        try:
            current = self.driver.current_window_handle
        except WebDriverException:
            current = None
        end = time.time() + max(timeout, 0.1)

        while True:
            handles = self.driver.window_handles
            # 현재 탭보다 **나중에** 열린 탭만 후보로 본다.
            # 단순히 '나 아닌 탭' 으로 보면 이미 새 탭에 있을 때 원래 탭으로 되돌아간다.
            if current in handles:
                newer = handles[handles.index(current) + 1:]
            else:
                newer = list(handles)

            if newer:
                for handle in reversed(newer):
                    try:
                        self.driver.switch_to.window(handle)
                        if match and match not in (self.driver.title or "") \
                                and match not in (self.driver.current_url or ""):
                            continue
                        self.driver.switch_to.default_content()
                        self.wait_ready(30)
                        self.log("  · 새 탭으로 이동했습니다: %s" % (self.title() or "")[:40])
                        return True
                    except WebDriverException:
                        continue
                if current in handles:          # 조건에 맞는 탭이 없으면 제자리로
                    try:
                        self.driver.switch_to.window(current)
                    except WebDriverException:
                        pass

            # 이미 마지막 탭에 있고 탭이 2개 이상이면 클릭 직후 자동으로 옮겨진 것이다
            elif len(handles) > 1 and handles[-1] == current:
                self.log("  · 이미 새 탭에 있습니다: %s" % (self.title() or "")[:40])
                return True

            if time.time() >= end:
                break
            time.sleep(0.3)

        raise ElementNotFound(
            "새 탭이 열리지 않았습니다(%.0f초 기다림). 앞 단계의 클릭이 새 탭을 여는지, "
            "대기 시간을 늘려야 하는지 확인해 주세요." % timeout)

    def close_tab(self):
        if len(self.driver.window_handles) > 1:
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[-1])
        return True

    def handle_alert(self, accept: bool = True, text: str = ""):
        try:
            alert = self.driver.switch_to.alert
        except NoAlertPresentException:
            return False
        if text:
            alert.send_keys(text)
        alert.accept() if accept else alert.dismiss()
        return True

    def run_script(self, script: str):
        return self.driver.execute_script(script)

    def screenshot(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.driver.save_screenshot(str(path))
        return str(path)

    def scroll(self, amount: str = "bottom"):
        js = {
            "bottom": "window.scrollTo(0, document.body.scrollHeight);",
            "top": "window.scrollTo(0, 0);",
        }.get(str(amount).lower())
        if js is None:
            js = "window.scrollBy(0, %d);" % int(amount)
        self.driver.execute_script(js)
        return True

    # -- 내부 --------------------------------------------------------------

    def _scroll_into_view(self, el):
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
            time.sleep(0.15)
        except WebDriverException:
            pass

    def _follow_new_tab(self, before_count: int, wait: float = 1.5):
        """클릭 때문에 새 창이 떴으면 그 창으로 자동 이동한다."""
        end = time.time() + wait
        while time.time() < end:
            handles = self.driver.window_handles
            if len(handles) > before_count:
                self.driver.switch_to.window(handles[-1])
                self.wait_ready(20)
                self.log("  · 새 창으로 이동했습니다.")
                return True
            time.sleep(0.2)
        return False


__all__ = ["WebActions", "ElementNotFound", "parse_target"]
