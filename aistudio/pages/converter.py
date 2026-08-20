"""파일 변환 계열 화면(동영상→GIF, Excel→PDF, PPT→PDF)의 공통 구조."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

from ..engines.common import open_in_explorer
from ..theme import C, ui_font
from ..widgets import Button, Card, FileQueue, LabeledSwitch, PathPicker, RunPanel, Segmented
from .base import BasePage


class ConverterPage(BasePage):
    """목록 → 옵션 → 저장 위치 → 실행 순서로 구성된 변환 화면."""

    extensions: tuple = ()
    filetype_label = "파일"
    queue_title = "변환할 파일"
    queue_desc = ""
    options_title = "변환 옵션"
    options_desc = ""
    options_icon = "⚙"
    run_text = "변환 시작"
    done_message = "{ok}개 파일을 변환했습니다."
    engine = None  # (params, emitter) -> summary

    def build(self):
        # 1) 파일 목록
        queue_card = Card(self.content, title=self.queue_title, desc=self.queue_desc, icon="▤")
        queue_card.pack(fill="x", pady=(0, 16))
        self.queue = FileQueue(queue_card.body, self.extensions, self.filetype_label,
                               bg=queue_card.bg, on_change=self._on_queue_change)
        self.queue.pack(fill="both", expand=True)

        # 2) 세부 옵션
        self.options_card = Card(self.content, title=self.options_title,
                                 desc=self.options_desc, icon=self.options_icon)
        self.options_card.pack(fill="x", pady=(0, 16))
        self.build_options(self.options_card.body, self.options_card.bg)

        # 3) 저장 위치
        out_card = Card(self.content, title="저장 위치", desc="변환된 파일을 어디에 둘지 선택합니다.", icon="⇩")
        out_card.pack(fill="x", pady=(0, 16))
        bg = out_card.bg

        self.out_mode = tk.StringVar(value="same")
        Segmented(out_card.body,
                  [("same", "원본과 같은 폴더"), ("custom", "다른 폴더 지정")],
                  self.out_mode, command=lambda v: self._sync_out_mode(), bg=bg).pack(anchor="w")

        self.out_dir = tk.StringVar(value="")
        self.picker = PathPicker(out_card.body, self.out_dir, bg=bg, title="저장할 폴더 선택")
        self.picker.pack(fill="x", pady=(12, 0))

        self.overwrite = tk.BooleanVar(value=True)
        LabeledSwitch(out_card.body, "같은 이름 파일 덮어쓰기", self.overwrite,
                      desc="끄면 '이름 (2).확장자' 형태로 새 파일을 만듭니다.", bg=bg).pack(
            anchor="w", pady=(16, 0))
        self._sync_out_mode()

        # 4) 실행
        run_card = Card(self.content, title="실행", desc="진행 상황과 파일별 결과가 아래에 표시됩니다.", icon="✦")
        run_card.pack(fill="both", expand=True)
        self.panel = RunPanel(run_card.body, self.run_text, on_run=self.start,
                              on_cancel=lambda: self.cancel_job(self.panel), bg=run_card.bg)
        self.panel.pack(fill="both", expand=True)

        footer = tk.Frame(run_card.body, bg=run_card.bg)
        footer.pack(fill="x", pady=(12, 0))
        self.open_button = Button(footer, "결과 폴더 열기", command=self.open_output_folder,
                                  kind="ghost", bg=run_card.bg, height=32, font_size=9)
        self.open_button.pack(side="left")
        self.open_button.set_enabled(False)
        self._last_out_dir = ""

    # -- 하위 클래스 확장 지점 --------------------------------------
    def build_options(self, parent, bg):
        raise NotImplementedError

    def collect_options(self) -> dict:
        return {}

    def validate(self) -> bool:
        return True

    # -- 내부 처리 ---------------------------------------------------
    def _on_queue_change(self, count):
        self.status_chip.set(f"{count}개 대기" if count else "준비됨", "info" if count else "ok")

    def _sync_out_mode(self):
        self.picker.set_enabled(self.out_mode.get() == "custom")

    def open_output_folder(self):
        if self._last_out_dir:
            open_in_explorer(self._last_out_dir)

    def start(self):
        files = self.queue.paths()
        if not files:
            messagebox.showwarning("알림", f"{self.filetype_label}을(를) 먼저 추가해 주세요.")
            return
        out_mode = self.out_mode.get()
        out_dir = self.out_dir.get().strip()
        if out_mode == "custom":
            if not out_dir:
                messagebox.showwarning("알림", "저장할 폴더를 지정해 주세요.")
                return
            if not os.path.isdir(out_dir):
                try:
                    os.makedirs(out_dir, exist_ok=True)
                except OSError as exc:
                    messagebox.showerror("오류", f"저장 폴더를 만들 수 없습니다:\n{exc}")
                    return
        if not self.validate():
            return

        params = {
            "files": files,
            "out_mode": out_mode,
            "out_dir": out_dir,
            "overwrite": self.overwrite.get(),
        }
        params.update(self.collect_options())
        self.open_button.set_enabled(False)
        self.run_job(self.engine, params, self.panel,
                     done_message=self.done_message, on_success=self._on_success)

    def _on_success(self, summary):
        self._last_out_dir = summary.get("out_dir", "")
        self.open_button.set_enabled(bool(self._last_out_dir))


def hint_label(parent, text, bg):
    return tk.Label(parent, text=text, bg=bg, fg=C["text_faint"], font=ui_font(8), justify="left")
