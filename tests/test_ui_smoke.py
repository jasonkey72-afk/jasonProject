"""
화면(GUI) 동작 확인
====================
창을 실제로 띄운 뒤, 사람이 누르는 것과 같은 순서로
  파일 추가(xlsx·docx·pptx·pdf) → 크기 설정 → 분할 시작 → 완료
를 진행시켜 결과 파일이 만들어지는지 확인한다.

화면이 없는 환경(리눅스 서버 등)에서는 자동으로 건너뛴다.
실행:  python tests/test_ui_smoke.py
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import tkinter  # noqa: F401
except Exception:
    print("tkinter 를 사용할 수 없어 건너뜁니다.")
    raise SystemExit(0)

from test_splitter_core import check, make_docx, make_pdf, make_pptx, make_xlsx  # noqa: E402


def pump(root, seconds=0.4):
    """정해진 시간 동안 창 이벤트를 처리한다."""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def wait_until(root, condition, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if condition():
            return True
        time.sleep(0.02)
    return False


def main():
    try:
        import office_file_splitter as app_mod
    except Exception as e:
        print(f"화면을 만들 수 없어 건너뜁니다: {e}")
        return

    # 자동 테스트에서는 "완료" 안내창이 떠도 눌러 줄 사람이 없으므로 대체한다
    class Silent:
        popups = []

        @classmethod
        def showinfo(cls, title, message):
            cls.popups.append(("info", message))

        @classmethod
        def showwarning(cls, title, message):
            cls.popups.append(("warn", message))

        @classmethod
        def showerror(cls, title, message):
            cls.popups.append(("error", message))

        @classmethod
        def askyesno(cls, title, message):
            return True

    app_mod.messagebox = Silent

    try:
        app = app_mod.SplitterApp()
    except Exception as e:
        print(f"화면을 만들 수 없어 건너뜁니다: {e}")
        return

    root = app.root
    tmp = Path(tempfile.mkdtemp(prefix="ui_test_"))
    print(f"작업 폴더: {tmp}")
    try:
        xlsx = tmp / "실적.xlsx"
        docx = tmp / "보고서.docx"
        pptx = tmp / "발표.pptx"
        pdf = tmp / "도면.pdf"
        make_xlsx(xlsx, rows=6000, cols=8, sheets=1)
        make_docx(docx, paragraphs=1500)
        make_pptx(pptx, slides=40)
        make_pdf(pdf, pages=20, side=140)

        # --- 파일 추가
        app._add_paths([str(xlsx), str(docx), str(pptx), str(pdf)])
        pump(root)
        check(len(app.files) == 4, "파일 4개가 목록에 들어갔다 (PDF 포함)")
        check(len(app.tree.get_children()) == 4, "목록 화면에도 4줄이 보인다")

        # --- 지원하지 않는 파일은 걸러진다
        other = tmp / "메모.txt"
        other.write_text("hello")
        app._add_paths([str(other)])
        pump(root)
        check(len(app.files) == 4, "txt 파일은 목록에 추가되지 않는다")

        # --- 프리셋/단위 버튼
        app._set_preset("5MB")
        pump(root, 0.1)
        check(app.size_value.get() == "5" and app.size_unit == "MB",
              "프리셋 버튼이 크기를 바꾼다")
        app._set_unit("KB")
        app.size_value.set("100")
        pump(root, 0.1)
        check(app.limit_bytes() == 100 * 1024, "단위 버튼(KB)이 반영된다")

        # --- 잘못된 값이면 시작 버튼이 잠긴다
        app.size_value.set("abc")
        pump(root, 0.1)
        check(app.start_btn.state_ == "disabled", "숫자가 아니면 시작 버튼이 잠긴다")
        app.size_value.set("100")
        pump(root, 0.1)
        check(app.start_btn.state_ == "normal", "올바른 값이면 다시 열린다")

        # --- 결과를 다른 폴더에 저장
        # (폴더가 비어 있으면 '다른 폴더 지정'을 누르는 순간 폴더 선택 창이 뜨므로 먼저 채워 둔다)
        out = tmp / "결과"
        app.output_dir.set(str(out))
        app._set_output_mode("custom")
        pump(root, 0.1)
        check(app.output_mode == "custom", "저장 위치를 다른 폴더로 바꿨다")

        # --- 분할 시작 (실제 작업 스레드가 돈다)
        app.start()
        ok = wait_until(root, lambda: app.worker is not None and not app.worker.is_alive())
        pump(root, 0.6)
        check(ok, "작업이 끝까지 진행됐다")

        made = sorted(p for p in out.rglob("*") if p.is_file())
        check(len(made) >= 8, f"결과 파일이 만들어졌다 ({len(made)}개)")
        over = [f"{p.name} {p.stat().st_size}B" for p in made if p.stat().st_size > 100 * 1024]
        check(not over, f"결과 파일이 모두 100KB 이하다 {over}")
        check(all(f["status"] == "done" for f in app.files), "목록이 완료 표시로 바뀌었다")
        check(app.last_output_dir is not None and app.last_output_dir.exists(),
              "'결과 폴더 열기' 버튼이 가리킬 폴더가 있다")

        log_text = app.log.get("1.0", "end")
        check("완료" in log_text, "진행 상황에 완료 기록이 남았다")
        check(any(kind == "info" for kind, _ in Silent.popups), "완료 안내창이 떴다")

        by_source = {}
        for part in made:
            by_source.setdefault(part.name.split("_part")[0], []).append(part)
        check(len(by_source) == 4, f"네 파일 모두 나뉘었다 ({sorted(by_source)})")
        check(all(len(v) >= 2 for v in by_source.values()), "각 파일이 2개 이상으로 나뉘었다")

        # --- 중지 동작
        shutil.rmtree(out, ignore_errors=True)
        app.start()
        pump(root, 0.15)
        app.cancel()
        wait_until(root, lambda: app.worker is not None and not app.worker.is_alive())
        pump(root, 0.4)
        check(app.cancel_event.is_set(), "중지 요청이 전달됐다")
        check(app.start_btn.state_ == "normal", "중지 후 다시 시작할 수 있다")

        print("\n화면 동작 확인을 모두 통과했습니다.")
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
