"""
새 탭(팝업) 처리 검증
======================
실행:  python tests\\test_newtab.py

사내 시스템에서 가장 자주 막히는 상황을 그대로 재현한다.

  1단계: 웹사이트를 연다
  2단계: 버튼을 누르면 **새 탭**이 열린다
  3단계: 새 탭에 있는 버튼을 클릭한다   <- 여기서 "요소를 찾지 못했습니다" 가 난다

원인은 클릭 뒤에도 자동화가 **원래 탭에 머물러 있기** 때문이다.
새 탭이 늦게 열리면(서버 응답을 기다렸다가 여는 경우) 자동 추적 시간을 넘겨 버린다.

두 엔진 모두에서 같은 검사를 돌린다.
    set JOBSCN_TEST_ENGINE=cdp      && python tests\\test_newtab.py
    set JOBSCN_TEST_ENGINE=selenium && python tests\\test_newtab.py
"""

import sys

from conftest_driver import make_engine, test_engine, MAIN_PAGE, Report, assert_eq  # noqa: E402

from jobscenario.webauto.locator import ElementNotFound

r = Report("새 탭 처리 (%s 엔진)" % test_engine())
web = make_engine(log=lambda m: None)


def reset():
    """1단계로 돌아간다. 열려 있는 새 탭은 모두 닫는다."""
    for _ in range(5):
        try:
            if not web.close_tab():
                break
        except Exception:
            break
    web.open_url(MAIN_PAGE)


try:
    # --- 바로 열리는 새 탭 (target="_blank" 링크) ---
    def instant_tab():
        reset()
        web.click("text=상세보기(새 탭)")          # 클릭 즉시 새 탭이 열린다
        assert "newtab.html" in web.current_url(), web.current_url()
        web.click("text=최종승인")
        assert_eq(web.get_text("id=done"), "최종승인됨")

    r.check("클릭으로 열린 새 탭을 자동으로 따라간다", instant_tab)

    # --- 늦게 열리는 새 탭 : 실제로 막혔던 상황 ---
    def slow_tab():
        reset()
        web.click("text=느린 상세보기(3초 뒤 새 탭)")   # 3초 뒤에야 탭이 열린다
        # 클릭 직후에는 아직 원래 탭에 있다. 그래도 다음 단계가 성공해야 한다.
        web.click("text=최종승인", timeout=10)
        assert_eq(web.get_text("id=done"), "최종승인됨")

    r.check("늦게 열린 새 탭도 다음 단계에서 자동으로 찾아간다", slow_tab)

    # --- 명시적으로 기다리는 단계 ---
    def explicit_wait():
        reset()
        web.click("text=느린 상세보기(3초 뒤 새 탭)")
        web.wait_new_tab(15)                        # '새 탭 열릴 때까지 기다렸다가 이동'
        assert "newtab.html" in web.current_url(), web.current_url()
        web.click("text=최종승인")
        assert_eq(web.get_text("id=done"), "최종승인됨")

    r.check("[새 탭 열릴 때까지 기다렸다가 이동] 단계", explicit_wait)

    def wait_with_match():
        reset()
        web.click("text=느린 상세보기(3초 뒤 새 탭)")
        web.wait_new_tab(15, "결재 상세")            # 제목 일부로 확인하며 이동
        assert "newtab.html" in web.current_url(), web.current_url()

    r.check("제목을 확인하며 새 탭으로 이동", wait_with_match)

    def already_moved():
        """자동으로 이미 옮겨간 뒤에 이 단계를 넣어도 되돌아가면 안 된다."""
        reset()
        web.click("text=상세보기(새 탭)")            # 여기서 이미 새 탭으로 이동
        web.wait_new_tab(5)                          # 그래도 새 탭에 그대로 있어야 한다
        assert "newtab.html" in web.current_url(), web.current_url()

    r.check("이미 새 탭에 있으면 그대로 둔다", already_moved)

    # --- 탭 전환 ---
    def switch_by_title():
        reset()
        web.click("text=상세보기(새 탭)")
        web.switch_tab("사내 포털")                  # 제목 일부로 원래 탭에 복귀
        assert "portal.html" in web.current_url(), web.current_url()
        web.switch_tab("결재 상세")                  # 다시 새 탭으로
        assert "newtab.html" in web.current_url(), web.current_url()

    r.check("제목 일부로 탭 전환", switch_by_title)

    def switch_by_index():
        reset()
        web.click("text=상세보기(새 탭)")
        web.switch_tab(0)
        assert "portal.html" in web.current_url(), web.current_url()
        web.switch_tab(-1)
        assert "newtab.html" in web.current_url(), web.current_url()

    r.check("번호로 탭 전환", switch_by_index)

    def close_returns():
        reset()
        web.click("text=상세보기(새 탭)")
        web.close_tab()
        assert "portal.html" in web.current_url(), web.current_url()

    r.check("새 탭을 닫으면 원래 탭으로 돌아온다", close_returns)

    # --- 원래 탭의 요소도 계속 찾을 수 있어야 한다 ---
    def back_to_first():
        reset()
        web.click("text=상세보기(새 탭)")            # 새 탭으로 이동한 상태
        web.click("text=조회")                       # 원래 탭에만 있는 버튼
        assert_eq(web.get_text("#res"), "조회 완료")

    r.check("새 탭에 있어도 원래 탭의 요소를 찾아간다", back_to_first)

    # --- 어느 탭에도 없으면 여전히 실패해야 한다 ---
    def still_fails():
        reset()
        try:
            web.click("text=어느탭에도없는버튼ZZZ", timeout=3)
        except ElementNotFound:
            return
        raise AssertionError("오류가 발생해야 하는데 성공했습니다")

    r.check("어느 탭에도 없으면 정상적으로 오류", still_fails)

    def no_new_tab():
        """새 탭이 열리지 않으면 무엇을 확인해야 하는지 알려줘야 한다."""
        reset()
        try:
            web.wait_new_tab(3)
        except ElementNotFound as e:
            assert "새 탭이 열리지 않았습니다" in str(e), str(e)
            return
        raise AssertionError("오류가 발생해야 하는데 성공했습니다")

    r.check("새 탭이 안 열리면 친절한 오류", no_new_tab)
finally:
    try:
        web.quit()
    except Exception:
        pass

sys.exit(r.finish())
