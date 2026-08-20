"""폴더 안 파일 & 폴더 이름 목록 만들기 화면 (신규 기능)."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..engines import namelist
from ..engines.common import human_size, open_in_explorer
from ..theme import C, ui_font
from ..widgets import Button, Card, FormRow, LabeledSwitch, PathPicker, RunPanel, Segmented
from .base import BasePage
from .converter import hint_label

PREVIEW_LIMIT = 500


class NameListPage(BasePage):
    key = "namelist"
    title = "파일 & 폴더 이름 목록"
    subtitle = "폴더 안의 파일과 하위 폴더 이름을 한 번에 수집해 엑셀(CSV)·텍스트·트리 형태로 저장합니다."
    icon = "☰"

    def build(self):
        self.rows: list[dict] = []
        self.scan_root = ""

        # 1) 대상 폴더
        target_card = Card(self.content, title="대상 폴더",
                           desc="이름을 기록할 폴더를 선택합니다.", icon="▤")
        target_card.pack(fill="x", pady=(0, 16))
        bg = target_card.bg
        self.root_var = tk.StringVar(value="")
        PathPicker(target_card.body, self.root_var, bg=bg, title="목록을 만들 폴더 선택").pack(fill="x")

        # 2) 수집 옵션
        opt_card = Card(self.content, title="수집 옵션",
                        desc="무엇을, 어디까지 훑을지 정합니다.", icon="⚙")
        opt_card.pack(fill="x", pady=(0, 16))
        bg = opt_card.bg

        self.include_files = tk.BooleanVar(value=True)
        self.include_folders = tk.BooleanVar(value=True)
        self.include_hidden = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=True)
        self.max_depth = tk.IntVar(value=0)
        self.ext_filter = tk.StringVar(value="")
        self.name_contains = tk.StringVar(value="")
        self.sort_by = tk.StringVar(value="kind")

        switches = tk.Frame(opt_card.body, bg=bg)
        switches.pack(fill="x")
        left = tk.Frame(switches, bg=bg)
        left.pack(side="left", fill="x", expand=True)
        right = tk.Frame(switches, bg=bg)
        right.pack(side="left", fill="x", expand=True, padx=(24, 0))
        LabeledSwitch(left, "파일 포함", self.include_files, bg=bg).pack(anchor="w", pady=(0, 12))
        LabeledSwitch(left, "폴더 포함", self.include_folders, bg=bg).pack(anchor="w")
        LabeledSwitch(right, "하위 폴더까지 검색", self.recursive, bg=bg,
                      command=self._sync_depth).pack(anchor="w", pady=(0, 12))
        LabeledSwitch(right, "숨김 항목 포함", self.include_hidden, bg=bg).pack(anchor="w")

        ttk.Separator(opt_card.body, style="AI.TSeparator").pack(fill="x", pady=16)

        row = FormRow(opt_card.body, "검색 깊이", bg=bg, hint="0 = 제한 없음 (1 은 선택한 폴더 바로 아래만)")
        row.pack(fill="x", pady=5)
        self.depth_spin = ttk.Spinbox(row.field, from_=0, to=20, textvariable=self.max_depth,
                                      width=8, style="AI.TSpinbox", font=ui_font(9))
        self.depth_spin.pack(side="left")

        row = FormRow(opt_card.body, "확장자만 보기", bg=bg, hint="예: xlsx, pdf, mp4 (비우면 전체)", expand=True)
        row.pack(fill="x", pady=5)
        ttk.Entry(row.field, textvariable=self.ext_filter, style="AI.TEntry",
                  font=ui_font(9)).pack(side="left", fill="x", expand=True)

        row = FormRow(opt_card.body, "이름 포함 검색", bg=bg, hint="이름에 이 글자가 들어간 항목만", expand=True)
        row.pack(fill="x", pady=5)
        ttk.Entry(row.field, textvariable=self.name_contains, style="AI.TEntry",
                  font=ui_font(9)).pack(side="left", fill="x", expand=True)

        row = FormRow(opt_card.body, "정렬 기준", bg=bg)
        row.pack(fill="x", pady=5)
        self.sort_label = tk.StringVar(value=dict(namelist.SORT_OPTIONS)["kind"])
        ttk.Combobox(row.field, textvariable=self.sort_label, state="readonly", width=24,
                     style="AI.TCombobox", font=ui_font(9),
                     values=[label for _v, label in namelist.SORT_OPTIONS]).pack(side="left")
        self._sync_depth()

        # 3) 실행 + 결과 미리보기
        run_card = Card(self.content, title="목록 만들기",
                        desc="수집한 결과를 아래 표에서 바로 확인할 수 있습니다.", icon="✦")
        run_card.pack(fill="x", pady=(0, 16))
        self.panel = RunPanel(run_card.body, "목록 만들기", on_run=self.start,
                              on_cancel=lambda: self.cancel_job(self.panel),
                              bg=run_card.bg, log_height=5)
        self.panel.pack(fill="x")

        preview_card = Card(self.content, title="미리보기",
                            desc=f"최대 {PREVIEW_LIMIT}개까지 표시합니다. 저장 시에는 전체가 포함됩니다.", icon="◉")
        preview_card.pack(fill="both", expand=True, pady=(0, 16))
        bg = preview_card.bg

        summary_row = tk.Frame(preview_card.body, bg=bg)
        summary_row.pack(fill="x", pady=(0, 10))
        self.summary_label = tk.Label(summary_row, text="아직 수집한 항목이 없습니다.",
                                      bg=bg, fg=C["text_dim"], font=ui_font(9))
        self.summary_label.pack(side="left")

        table = tk.Frame(preview_card.body, bg=C["surface_alt"], highlightthickness=1,
                         highlightbackground=C["border"])
        table.pack(fill="both", expand=True)
        columns = ("no", "name", "kind", "ext", "size", "mtime", "relpath")
        headings = {"no": ("번호", 60), "name": ("이름", 240), "kind": ("종류", 60),
                    "ext": ("확장자", 80), "size": ("크기", 90), "mtime": ("수정일시", 130),
                    "relpath": ("상대 경로", 260)}
        self.tree = ttk.Treeview(table, style="AI.Treeview", columns=columns,
                                 show="headings", height=10)
        for key in columns:
            label, width = headings[key]
            self.tree.heading(key, text=label, anchor="w")
            self.tree.column(key, width=width, anchor="w",
                             stretch=(key == "relpath"))
        scroll = ttk.Scrollbar(table, orient="vertical", style="AI.Vertical.TScrollbar",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background=C["surface"])
        self.tree.tag_configure("folder", foreground=C["accent_2"])

        # 4) 저장
        save_card = Card(self.content, title="저장 / 내보내기",
                         desc="엑셀에서 바로 열리는 CSV 를 비롯해 네 가지 형식을 지원합니다.", icon="⇩")
        save_card.pack(fill="x")
        bg = save_card.bg

        self.export_format = tk.StringVar(value="csv")
        Segmented(save_card.body, [(v, l.split(" (")[0]) for v, l in namelist.EXPORT_FORMATS],
                  self.export_format, bg=bg, min_seg=110).pack(anchor="w")

        col_frame = tk.Frame(save_card.body, bg=bg)
        col_frame.pack(fill="x", pady=(16, 0))
        tk.Label(col_frame, text="포함할 정보", bg=bg, fg=C["text_dim"],
                 font=ui_font(9)).pack(anchor="w", pady=(0, 8))
        self.col_ext = tk.BooleanVar(value=True)
        self.col_relpath = tk.BooleanVar(value=True)
        self.col_parent = tk.BooleanVar(value=False)
        self.col_size = tk.BooleanVar(value=True)
        self.col_mtime = tk.BooleanVar(value=True)
        chips = tk.Frame(col_frame, bg=bg)
        chips.pack(fill="x")
        for text, var in (("확장자", self.col_ext), ("상대 경로", self.col_relpath),
                          ("상위 폴더", self.col_parent), ("크기", self.col_size),
                          ("수정일시", self.col_mtime)):
            LabeledSwitch(chips, text, var, bg=bg).pack(side="left", padx=(0, 22))
        hint_label(save_card.body, "번호 · 이름 · 종류는 항상 포함됩니다.", bg).pack(anchor="w", pady=(10, 0))

        actions = tk.Frame(save_card.body, bg=bg)
        actions.pack(fill="x", pady=(18, 0))
        self.save_button = Button(actions, "파일로 저장", command=self.export_file,
                                  kind="primary", bg=bg, height=40)
        self.save_button.pack(side="left")
        self.copy_button = Button(actions, "클립보드로 복사", command=self.copy_clipboard,
                                  kind="ghost", bg=bg, height=40)
        self.copy_button.pack(side="left", padx=(8, 0))
        self.open_button = Button(actions, "저장 폴더 열기", command=self.open_saved,
                                  kind="ghost", bg=bg, height=40)
        self.open_button.pack(side="left", padx=(8, 0))
        self._saved_dir = ""
        self._set_result_buttons(False)

    # -- 옵션 동기화 -------------------------------------------------
    def _sync_depth(self):
        self.depth_spin.configure(state="normal" if self.recursive.get() else "disabled")

    def _set_result_buttons(self, enabled):
        self.save_button.set_enabled(enabled)
        self.copy_button.set_enabled(enabled)
        self.open_button.set_enabled(enabled and bool(self._saved_dir))

    # -- 수집 --------------------------------------------------------
    def start(self):
        root = self.root_var.get().strip()
        if not root:
            messagebox.showwarning("알림", "먼저 대상 폴더를 선택해 주세요.")
            return
        if not os.path.isdir(root):
            messagebox.showwarning("알림", "폴더를 찾을 수 없습니다. 경로를 확인해 주세요.")
            return
        if not self.include_files.get() and not self.include_folders.get():
            messagebox.showwarning("알림", "'파일 포함' 또는 '폴더 포함' 중 하나는 켜져 있어야 합니다.")
            return

        sort_by = next((v for v, label in namelist.SORT_OPTIONS if label == self.sort_label.get()), "kind")
        params = {
            "root": root,
            "recursive": self.recursive.get(),
            "max_depth": self.max_depth.get(),
            "include_files": self.include_files.get(),
            "include_folders": self.include_folders.get(),
            "include_hidden": self.include_hidden.get(),
            "ext_filter": self.ext_filter.get(),
            "name_contains": self.name_contains.get(),
            "sort_by": sort_by,
        }
        self._set_result_buttons(False)
        self.run_job(namelist.scan, params, self.panel, on_success=self._on_scanned)

    def _on_scanned(self, summary):
        self.rows = summary.get("rows", [])
        self.scan_root = summary.get("root", "")
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows[:PREVIEW_LIMIT]):
            tags = []
            if i % 2:
                tags.append("odd")
            if row["is_dir"]:
                tags.append("folder")
            self.tree.insert("", "end", tags=tuple(tags), values=(
                row["no"], row["name"], row["kind"], row["ext"],
                row["size"], row["mtime"], row["relpath"],
            ))
        folders = summary.get("folders", 0)
        files = summary.get("files", 0)
        total = human_size(summary.get("total_bytes", 0))
        more = f"  (미리보기 {PREVIEW_LIMIT}개까지 표시)" if len(self.rows) > PREVIEW_LIMIT else ""
        self.summary_label.configure(
            text=f"폴더 {folders:,}개 · 파일 {files:,}개 · 합계 {total}{more}")
        self._set_result_buttons(bool(self.rows))
        if not self.rows:
            messagebox.showinfo("알림", "조건에 맞는 항목이 없습니다. 옵션을 조정해 보세요.")

    # -- 내보내기 ----------------------------------------------------
    def _columns(self):
        return namelist.selected_columns({
            "ext": self.col_ext.get(),
            "relpath": self.col_relpath.get(),
            "parent": self.col_parent.get(),
            "size": self.col_size.get(),
            "mtime": self.col_mtime.get(),
        })

    def export_file(self):
        if not self.rows:
            return
        fmt = self.export_format.get()
        ext = namelist.EXPORT_EXT[fmt]
        default_name = f"{Path(self.scan_root).name or 'list'}_목록{ext}"
        path = filedialog.asksaveasfilename(
            title="목록 저장", defaultextension=ext, initialfile=default_name,
            filetypes=[(dict(namelist.EXPORT_FORMATS)[fmt], f"*{ext}"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            saved = namelist.export(self.rows, self.scan_root, fmt, self._columns(), Path(path))
        except OSError as exc:
            messagebox.showerror("오류", f"저장하지 못했습니다:\n{exc}")
            return
        self._saved_dir = str(saved.parent)
        self.open_button.set_enabled(True)
        self.panel.log.write(f"[저장] {saved}", "ok")
        self.panel.set_status(f"저장 완료 · {saved.name}")
        messagebox.showinfo("저장 완료", f"{len(self.rows):,}개 항목을 저장했습니다.\n{saved}")

    def copy_clipboard(self):
        if not self.rows:
            return
        text = namelist.clipboard_text(self.rows, self._columns())
        self.clipboard_clear()
        self.clipboard_append(text)
        self.panel.log.write(f"[복사] {len(self.rows):,}개 항목을 클립보드에 담았습니다. 엑셀에 붙여넣기 하세요.", "ok")
        self.panel.set_status("클립보드로 복사했습니다")

    def open_saved(self):
        if self._saved_dir:
            open_in_explorer(self._saved_dir)
