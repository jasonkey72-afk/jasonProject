"""
CDPActions - 드라이버 없이 동작하는 자동화 엔진
================================================
selenium 판 WebActions 와 **같은 메서드 이름/인자**를 제공하므로
실행 엔진(runner)은 어느 쪽을 쓰는지 몰라도 된다.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..locator import parse_target, Target, ElementNotFound
from .. import picker as picker_mod
from .client import CDPError, CDPClosed
from .launcher import launch
from .page import CDPBrowser, CDPElement

HIGHLIGHT_JS = """
function () {
  this.scrollIntoView({block: 'center', inline: 'center'});
  var old = this.style.outline, oldBg = this.style.backgroundColor;
  var el = this;
  el.style.outline = '3px solid #f97316';
  el.style.backgroundColor = 'rgba(249,115,22,.20)';
  setTimeout(function () {
    el.style.outline = old; el.style.backgroundColor = oldBg;
  }, 1600);
  return true;
}
"""


class CDPActions:
    """브라우저 하나에 대한 동작 묶음(selenium 판과 동일한 사용법)."""

    engine_name = "cdp"

    def __init__(self, browser: CDPBrowser, timeout: float = 15.0, log=None):
        self.browser = browser
        self.timeout = timeout
        self.log = log or (lambda msg: None)

    # -- 만들기 / 끝내기 ---------------------------------------------------

    @classmethod
    def start(cls, browser: str = "edge", user_data_dir: str = "",
              download_dir: str = "", headless: bool = False, port: int = 0,
              timeout: float = 15.0, log=None) -> "CDPActions":
        client, proc, used_port = launch(browser, user_data_dir=user_data_dir,
                                        headless=headless, port=port, log=log)
        return cls(CDPBrowser(client, proc, used_port, download_dir, log=log),
                   timeout=timeout, log=log)

    @property
    def page(self):
        if self.browser.page is None:
            self.browser.switch_tab(-1)
        return self.browser.page

    @property
    def alive(self) -> bool:
        return self.browser.alive

    def quit(self):
        self.browser.quit()

    # -- 상태 읽기(엔진 공통 인터페이스) -----------------------------------

    def title(self) -> str:
        return self.page.title

    def current_url(self) -> str:
        return self.page.url

    def page_source(self) -> str:
        return self.page.page_source()

    def save_screenshot(self, path: str) -> str:
        return self.page.screenshot(path)

    # -- 탐색 --------------------------------------------------------------

    def find(self, target, timeout=None, visible_only: bool = True) -> CDPElement:
        spec = target if isinstance(target, dict) else None
        if spec is None:
            spec = (target if isinstance(target, Target) else parse_target(target)).to_dict()
        try:
            return self.page.find(spec, self.timeout if timeout is None else timeout,
                                  visible_only, log=self.log)
        except ElementNotFound:
            # 현재 탭에 없으면 다른 탭도 찾아본다.
            # 버튼을 눌러 새 탭이 열렸는데 자동화는 원래 탭에 남아 있는 경우가 많다.
            el = self._find_in_other_tabs(spec, visible_only)
            if el is not None:
                return el
            raise

    def _find_in_other_tabs(self, spec: dict, visible_only: bool):
        """열려 있는 다른 탭을 최근 것부터 훑어보고, 찾으면 그 탭으로 이동한다."""
        current = self.browser.page
        current_id = current.target_id if current is not None else None
        targets = self.browser.page_targets()
        if len(targets) <= 1:
            return None

        for info in reversed(targets):          # 가장 최근에 열린 탭부터
            if info["targetId"] == current_id:
                continue
            try:
                page = self.browser.attach(info["targetId"])
                page.wait_ready(5)
                el = page.find(spec, timeout=2.0, visible_only=visible_only)
            except (ElementNotFound, CDPError):
                continue
            self.browser.page = page
            self.log("  · 현재 탭에 없어 다른 탭에서 찾았습니다 → '%s' 탭으로 이동합니다."
                     % (page.title or info.get("url", ""))[:40])
            return el
        return None

    def highlight(self, el: CDPElement):
        try:
            self.page.call_on(el, HIGHLIGHT_JS)
        except CDPError:
            pass

    def element_label(self, el: CDPElement) -> str:
        info = el.info() or {}
        return "<%s> %s" % (info.get("tag", "?"),
                            (info.get("text") or info.get("value") or "")[:30])

    # -- 웹 동작 -----------------------------------------------------------

    def open_url(self, url: str, timeout: float = 60.0):
        if not url:
            raise ValueError("주소(URL)가 비어 있습니다.")
        if "://" not in url:
            url = "https://" + url
        self.page.navigate(url, timeout)

    def wait_ready(self, timeout: float = 30.0):
        return self.page.wait_ready(timeout)

    def click(self, target, timeout=None, new_tab_wait: bool = True):
        # 먼저 대상을 찾는다. 찾는 과정에서 다른 탭으로 옮겨갈 수 있으므로
        # '클릭 전 탭 수' 는 그 뒤에 세어야 한다.
        el = self.find(target, timeout)
        before = self.browser.page.target_id if self.browser.page else None
        how = self.page.click(el)
        if how.startswith("js("):
            self.log("  · 다른 요소에 가려져 있어 스크립트로 클릭했습니다.")
        if new_tab_wait:
            self.browser.follow_new_tab(before)
        return True

    def double_click(self, target, timeout=None):
        el = self.find(target, timeout)
        self.page.click(el)
        self.page.click(el)
        return True

    def hover(self, target, timeout=None):
        self.page.hover(self.find(target, timeout))
        time.sleep(0.3)
        return True

    def input_text(self, target, text: str, timeout=None, clear: bool = True,
                   enter: bool = False):
        el = self.find(target, timeout)
        self.page.type_text(el, text, clear=clear)
        if enter:
            self.page.press_key("enter")
        return True

    def select_option(self, target, value: str, timeout=None):
        el = self.find(target, timeout)
        result = self.page.select_option(el, value)
        if result == "not-select":
            # 흔히 쓰는 '가짜 콤보박스': 눌러서 펼친 뒤 항목을 글자로 찾는다
            self.page.click(el)
            time.sleep(0.3)
            return self.click("text=%s" % value, timeout, new_tab_wait=False)
        if result == "no-option":
            raise ElementNotFound("목록에서 '%s' 항목을 찾지 못했습니다." % value)
        return True

    def set_checkbox(self, target, checked: bool = True, timeout=None):
        return self.page.set_checkbox(self.find(target, timeout), checked)

    def press_key(self, key: str, target=None, timeout=None):
        if target is not None and not self._is_empty(target):
            el = self.find(target, timeout)
            self.page.call_on(el, "function(){ this.focus(); return true; }")
        return self.page.press_key(key)

    def upload_file(self, target, path: str, timeout=None):
        el = self.find(target, timeout, visible_only=False)
        return self.page.upload(el, [str(Path(path))])

    def wait_element(self, target, timeout=None):
        self.find(target, timeout)
        return True

    def wait_text(self, text: str, timeout: float = 30.0):
        end = time.time() + timeout
        needle = json.dumps(text, ensure_ascii=False)
        expr = ("(function(){var b=document.body; return !!b && "
                "(b.innerText||'').indexOf(%s) >= 0;})()" % needle)
        while time.time() < end:
            try:
                for _, ctx in self.page.frame_contexts():
                    if self.page.evaluate(expr, context_id=ctx):
                        return True
            except CDPClosed:
                raise
            except CDPError:
                pass
            time.sleep(0.4)
        raise ElementNotFound("화면에서 '%s' 글자를 찾지 못했습니다." % text)

    def get_text(self, target, timeout=None) -> str:
        info = self.find(target, timeout).info() or {}
        return (info.get("text") or info.get("value") or "").strip()

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
            targets = self.browser.page_targets()
            if index is not None:
                # '마지막 탭' 을 요청했는데 아직 탭이 하나뿐이면, 새 탭이 열리는 중일 수
                # 있으므로 잠깐 기다려 본다(끝내 안 열리면 지금 탭을 그대로 쓴다).
                waiting_for_new = (index == -1 and len(targets) < 2
                                   and (first or time.time() < end))
                if not waiting_for_new and -len(targets) <= index < len(targets):
                    self.browser.switch_tab(index)
                    self.page.wait_ready(20)
                    return True
            else:
                hit = [t for t in targets
                       if text in (t.get("title") or "") or text in (t.get("url") or "")]
                if hit:
                    self.browser.page = self.browser.attach(hit[-1]["targetId"])
                    self.page.wait_ready(20)
                    return True
            first = False
            if time.time() >= end:
                if index is not None and self.browser.page_targets():
                    self.browser.switch_tab(index)      # 새 탭은 안 열렸다 -> 지금 탭 사용
                    self.page.wait_ready(20)
                    return True
                break
            time.sleep(0.3)

        raise ElementNotFound(
            "'%s' 에 해당하는 탭을 찾지 못했습니다. 현재 열린 탭: %s"
            % (text, [(t.get("title") or t.get("url", ""))[:25]
                      for t in self.browser.page_targets()]))

    def wait_new_tab(self, timeout: float = 15.0, match: str = ""):
        """
        새 탭이 열릴 때까지 기다렸다가 그 탭으로 이동한다.
        클릭이 새 탭을 여는데 그 탭이 늦게 뜨는 경우에 쓴다.
        이미 새 탭으로 옮겨진 뒤라면 아무 일도 하지 않는다.
        """
        current = self.browser.page
        current_id = current.target_id if current is not None else None
        end = time.time() + max(timeout, 0.1)

        while True:
            targets = self.browser.page_targets()
            newer = self._targets_after(current_id, targets)
            if match:
                newer = [t for t in newer
                         if match in (t.get("title") or "") or match in (t.get("url") or "")]
            if newer:
                page = self.browser.attach(newer[-1]["targetId"])
                page.wait_ready(30)
                self.browser.page = page
                self.log("  · 새 탭으로 이동했습니다: %s" % (page.title or "")[:40])
                return True

            # 이미 가장 최근 탭에 있고 탭이 2개 이상이면, 클릭 직후 자동으로 옮겨진 것이다
            if len(targets) > 1 and targets and targets[-1]["targetId"] == current_id:
                self.log("  · 이미 새 탭에 있습니다: %s" % (self.title() or "")[:40])
                return True

            if time.time() >= end:
                break
            time.sleep(0.3)

        raise ElementNotFound(
            "새 탭이 열리지 않았습니다(%.0f초 기다림). 앞 단계의 클릭이 새 탭을 여는지, "
            "대기 시간을 늘려야 하는지 확인해 주세요." % timeout)

    def _targets_after(self, current_id, targets: list) -> list:
        """현재 탭보다 나중에 열린 탭만 골라낸다."""
        order = self.browser.tab_order()
        if current_id in order:
            newer = set(order[order.index(current_id) + 1:])
        else:
            newer = set(order)
        return [t for t in targets if t["targetId"] in newer]

    def close_tab(self):
        return self.browser.close_tab()

    def handle_alert(self, accept: bool = True, text: str = ""):
        return self.page.handle_dialog(accept, text)

    def run_script(self, script: str):
        """
        selenium 은 'return document.title' 처럼 함수 본문으로 쓰고,
        CDP 는 식(expression)을 받는다. 두 방식 모두 되도록 필요할 때만 감싼다.
        (시나리오 파일을 두 엔진이 함께 쓸 수 있어야 한다)
        """
        text = (script or "").strip()
        if not re.search(r"(^|[\n;{])\s*return\b", text):
            text = "return (%s);" % text.rstrip(";")
        # 결과를 항상 값으로 옮길 수 있게 만든다.
        # 창·DOM 요소를 돌려주는 스크립트(window.open 등)가 오류를 내지 않도록 한다.
        wrapped = (
            "(function () {"
            "  var __v = (function () { %s })();"
            "  if (__v === undefined || __v === null) { return null; }"
            "  if (typeof __v === 'object' || typeof __v === 'function') {"
            "    try { return JSON.parse(JSON.stringify(__v)); }"
            "    catch (e) { return String(__v); }"
            "  }"
            "  return __v;"
            "})()" % text
        )
        return self.page.evaluate(wrapped)

    def screenshot(self, path: str):
        return self.page.screenshot(path)

    def scroll(self, amount: str = "bottom"):
        return self.page.scroll(amount)

    # -- 요소 선택기 -------------------------------------------------------

    def pick_element(self, timeout: float = 180.0, on_status=None) -> Target:
        """
        사용자가 브라우저에서 요소를 클릭할 때까지 기다린다.
        selenium 판과 달리 프레임을 옮겨 다니지 않고 각 컨텍스트에 바로 심는다.
        """
        deadline = time.time() + timeout
        injected_at = 0.0
        while time.time() < deadline:
            pairs = self.page.frame_contexts()

            if time.time() - injected_at > 1.5:
                for _, ctx in pairs:
                    try:
                        self.page.evaluate(picker_mod.PICKER_JS, context_id=ctx,
                                           by_value=True)
                    except CDPError:
                        pass
                injected_at = time.time()
                if on_status:
                    on_status("브라우저에서 원하는 요소를 클릭하세요. (ESC = 취소)")

            for path_index, (_, ctx) in enumerate(pairs):
                try:
                    raw = self.page.evaluate(picker_mod.READ_JS_EXPR, context_id=ctx)
                except CDPError:
                    continue
                if not raw:
                    continue
                info = json.loads(raw)
                if info.get("cancel"):
                    self.stop_picker()
                    raise picker_mod.PickCancelled("사용자가 선택을 취소했습니다.")
                if info.get("error"):
                    continue
                frames = self._frame_path(path_index)
                self.stop_picker()
                return picker_mod.build_target(info, frames)

            time.sleep(0.25)

        self.stop_picker()
        raise TimeoutError("요소 선택 시간이 초과되었습니다.")

    def stop_picker(self):
        for _, ctx in self.page.frame_contexts():
            try:
                self.page.evaluate(picker_mod.STOP_JS, context_id=ctx)
            except CDPError:
                pass

    def _frame_path(self, flat_index: int) -> list:
        """
        평평한 프레임 순서(깊이 우선)에서의 위치를 저장용 경로([0, 1])로 바꾼다.
        selenium 판과 같은 형식이므로 시나리오 파일을 두 엔진이 함께 쓸 수 있다.
        """
        if flat_index <= 0:
            return []
        try:
            tree = self.page.send("Page.getFrameTree").get("frameTree", {})
        except CDPError:
            return []
        order = []

        def walk(node, path):
            order.append(list(path))
            for i, child in enumerate(node.get("childFrames") or []):
                walk(child, path + [i])

        walk(tree, [])
        return order[flat_index] if flat_index < len(order) else []

    # -- 내부 -------------------------------------------------------------

    @staticmethod
    def _is_empty(target) -> bool:
        if isinstance(target, dict):
            return not target.get("strategies")
        if isinstance(target, Target):
            return target.is_empty()
        return not str(target or "").strip()


__all__ = ["CDPActions", "ElementNotFound"]
