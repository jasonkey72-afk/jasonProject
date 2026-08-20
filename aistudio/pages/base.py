"""모든 기능 화면의 공통 뼈대."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from ..runner import JobRunner
from ..theme import C, ui_font
from ..widgets import Chip, ScrollArea, rounded_gradient


class BasePage(tk.Frame):
    """헤더 + 스크롤 본문 + 작업 실행기를 갖춘 기본 페이지."""

    key = "page"
    title = "페이지"
    subtitle = ""
    icon = "◆"

    def __init__(self, master, app):
        super().__init__(master, bg=C["bg"])
        self.app = app
        self.runner = JobRunner(self)

        header = tk.Frame(self, bg=C["bg"])
        header.pack(fill="x", padx=32, pady=(26, 0))

        title_row = tk.Frame(header, bg=C["bg"])
        title_row.pack(fill="x")
        tk.Label(title_row, text=self.title, bg=C["bg"], fg=C["text"],
                 font=ui_font(19, "bold")).pack(side="left")
        self.status_chip = Chip(title_row, text="준비됨", tone="ok", bg=C["bg"])
        self.status_chip.pack(side="right", pady=6)

        accent = tk.Canvas(header, height=3, bg=C["bg"], highlightthickness=0, bd=0)
        accent.pack(fill="x", pady=(10, 0))
        accent.bind("<Configure>", lambda e: self._draw_accent(accent, e.width))

        if self.subtitle:
            tk.Label(header, text=self.subtitle, bg=C["bg"], fg=C["text_dim"],
                     font=ui_font(9), justify="left").pack(anchor="w", pady=(12, 0))

        self.scroll = ScrollArea(self, bg=C["bg"])
        self.scroll.pack(fill="both", expand=True, padx=(32, 20), pady=(18, 24))
        self.content = self.scroll.inner

        self.build()

    @staticmethod
    def _draw_accent(canvas, width):
        canvas.delete("all")
        bar = min(width, 96)
        rounded_gradient(canvas, 0, 0, bar, 3, 1, C["accent"], C["accent_2"])

    # -- 하위 클래스에서 구현 ---------------------------------------
    def build(self):
        raise NotImplementedError

    def refresh_env(self):
        """환경 점검(Excel/PowerPoint/ffmpeg) 결과가 갱신되면 호출된다."""

    def on_show(self):
        """페이지가 화면에 표시될 때 호출된다."""

    # -- 작업 실행 공통 처리 ----------------------------------------
    def run_job(self, target, params, panel, done_message=None, on_success=None):
        if self.runner.is_running:
            messagebox.showwarning("알림", "이미 작업이 진행 중입니다.")
            return
        panel.log.clear()
        panel.set_running(True)
        panel.set_status("시작하는 중...")
        self.status_chip.set("작업 중", "info")

        def on_event(event):
            kind = event.get("type")
            if kind == "log":
                panel.log.write(event["message"], event.get("level", "info"))
            elif kind == "status":
                panel.set_status(event["message"])
            elif kind == "progress":
                panel.progress.stop_pulse()
                panel.progress.set_fraction(event["fraction"])
            elif kind == "pulse":
                if event.get("active"):
                    panel.progress.start_pulse()
                else:
                    panel.progress.stop_pulse()

        def on_finish(summary):
            panel.set_running(False)
            if summary.get("cancelled"):
                panel.set_status("사용자가 중지했습니다")
                panel.log.write("작업을 중지했습니다.", "warn")
                self.status_chip.set("중지됨", "warn")
                return
            if summary.get("error"):
                panel.set_status("오류로 중단되었습니다")
                panel.log.write(f"[오류] {summary['error']}", "error")
                self.status_chip.set("오류", "bad")
                messagebox.showerror("오류", summary["error"])
                return

            ok = summary.get("ok", 0)
            fail = summary.get("fail", 0)
            panel.progress.set_fraction(1.0)
            panel.set_status(f"완료 · 성공 {ok}건 / 실패 {fail}건")
            self.status_chip.set("완료" if not fail else "일부 실패", "ok" if not fail else "warn")
            if on_success:
                on_success(summary)
            if done_message:
                if fail:
                    messagebox.showwarning(
                        "완료 (일부 실패)",
                        f"성공 {ok}건, 실패 {fail}건입니다.\n자세한 내용은 로그를 확인해 주세요.",
                    )
                elif ok:
                    messagebox.showinfo("완료", done_message.format(ok=ok, fail=fail))

        self.runner.start(target, params, on_event, on_finish)

    def cancel_job(self, panel=None):
        if self.runner.is_running:
            self.runner.cancel()
            if panel:
                panel.set_status("중지 요청됨 · 정리 중...")
