"""
Office 파일 분할기 (Office File Splitter)
=========================================
용량이 커서 업로드·첨부할 수 없는 Excel / Word / PowerPoint 파일을,
사용자가 정한 크기(예: 10MB) 이하의 여러 파일로 나눠 주는 프로그램입니다.

- 원본 파일은 읽기만 하며 절대 수정하지 않습니다.
- Microsoft Office 설치가 필요 없습니다. (파일 형식을 직접 다룹니다)
- 부서원에게는 빌드된 exe 파일 하나만 전달하면 됩니다.

실행:  python office_file_splitter.py
"""

from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import office_splitter_ui as ui
from office_splitter_ui import C, Card, Chip, DropZone, GhostButton, GradientButton
from office_splitter_ui import AIOrb, ProgressBar, ToggleSwitch, mix
from splitter_core import (
    KB,
    MB,
    SUPPORTED_EXTS,
    Cancelled,
    Reporter,
    SplitError,
    SplitOptions,
    collect_office_files,
    human_size,
    split_file,
)

APP_NAME = "Office 파일 분할기"
APP_VERSION = "1.0"
PRESETS = ["5MB", "10MB", "20MB", "50MB", "100MB"]

# 드래그 앤 드롭은 tkinterdnd2 가 있을 때만 활성화된다 (없어도 정상 동작)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:  # pragma: no cover - 설치 여부에 따라 달라짐
    DND_FILES = None
    TkinterDnD = None
    _HAS_DND = False


def make_root():
    """드래그 앤 드롭이 가능하면 그 창을, 아니면 일반 창을 만든다."""
    if _HAS_DND:
        try:
            return TkinterDnD.Tk(), True
        except Exception:
            pass
    return tk.Tk(), False


def open_in_explorer(path: Path) -> None:
    """탐색기(또는 각 OS의 파일 관리자)로 결과 폴더를 연다."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class SplitterApp:
    def __init__(self):
        self.root, self.dnd = make_root()
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        self.root.geometry("1140x830")
        self.root.minsize(1000, 720)
        self.root.configure(bg=C.BG)
        self._enable_hidpi()

        self.files: list[dict] = []
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.last_output_dir: Path | None = None

        self.size_value = tk.StringVar(value="10")
        self.size_unit = "MB"
        self.output_mode = "same"          # same | custom
        self.output_dir = tk.StringVar(value="")
        self.excel_mode = "auto"           # auto | keep | fast

        # 진행률 계산용 (파일 1개가 전체에서 차지하는 구간)
        self._current_name = ""
        self._file_base = 0.0
        self._file_span = 1.0

        self._init_fonts()
        self._init_styles()
        self._build()
        self._register_dnd()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_queue)
        self._refresh_files()

    # ------------------------------------------------------------------
    # 기본 설정
    # ------------------------------------------------------------------
    def _enable_hidpi(self):
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

    def _init_fonts(self):
        family = ui.pick_family(self.root, ui.FONT_CANDIDATES)
        mono = ui.pick_family(self.root, ui.MONO_CANDIDATES)
        self.fonts = {
            "h1": (family, 17, "bold"),
            "h2": (family, 13, "bold"),
            "h3": (family, 11, "bold"),
            "card_title": (family, 11, "bold"),
            "base": (family, 10),
            "small": (family, 9),
            "tiny": (family, 8),
            "num": (family, 20, "bold"),
            "mono": (mono, 9),
            "button": (family, 11, "bold"),
        }

    def _init_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Dark.Treeview",
            background=C.PANEL, fieldbackground=C.PANEL, foreground=C.TEXT,
            borderwidth=0, relief="flat", rowheight=30, font=self.fonts["base"],
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", C.A_SOFT)],
            foreground=[("selected", C.TEXT)],
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=C.PANEL_HI, foreground=C.MUTED, relief="flat",
            borderwidth=0, font=self.fonts["small"], padding=(8, 6),
        )
        style.map("Dark.Treeview.Heading", background=[("active", C.PANEL_HI)])
        style.layout("Dark.Treeview", [("Dark.Treeview.treearea", {"sticky": "nswe"})])

        style.configure(
            "Dark.Vertical.TScrollbar",
            background=C.PANEL_HI, troughcolor=C.PANEL, bordercolor=C.PANEL,
            arrowcolor=C.MUTED, darkcolor=C.PANEL_HI, lightcolor=C.PANEL_HI,
            relief="flat", width=10,
        )
        style.map("Dark.Vertical.TScrollbar",
                  background=[("active", mix(C.PANEL_HI, C.A2, 0.4))])

    def _bind_keys(self):
        self.root.bind("<Control-o>", lambda e: self.add_files())
        self.root.bind("<Delete>", lambda e: self.remove_selected())
        self.root.bind("<Return>", lambda e: self.start())

    # ------------------------------------------------------------------
    # 화면 구성
    # ------------------------------------------------------------------
    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        self._build_header(root)

        main = tk.Frame(root, bg=C.BG)
        main.grid(row=1, column=0, sticky="nsew", padx=22, pady=(4, 0))
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, minsize=356)
        main.rowconfigure(0, weight=1)

        self._build_left(main)
        self._build_right(main)
        self._build_footer(root)

    def _build_header(self, parent):
        header = tk.Frame(parent, bg=C.BG)
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 10))
        header.columnconfigure(1, weight=1)

        self.orb = AIOrb(header, size=48, bg=C.BG)
        self.orb.grid(row=0, column=0, rowspan=2, padx=(0, 14))

        tk.Label(header, text=APP_NAME, bg=C.BG, fg=C.TEXT,
                 font=self.fonts["h1"]).grid(row=0, column=1, sticky="w")
        tk.Label(header,
                 text="용량이 큰 Excel · Word · PowerPoint 파일을 원하는 크기로 안전하게 나눕니다",
                 bg=C.BG, fg=C.MUTED, font=self.fonts["small"]).grid(row=1, column=1, sticky="w")

        badge = tk.Canvas(header, width=132, height=26, bg=C.BG,
                          highlightthickness=0, bd=0)
        badge.grid(row=0, column=2, rowspan=2, sticky="e")
        ui.draw_round_rect(badge, 1, 1, 131, 25, 13,
                           fill=mix(C.BG, C.A1, 0.18), outline=C.LINE)
        badge.create_text(66, 13, text="원본 파일 무손상", fill=C.A2, font=self.fonts["small"])

        line = tk.Canvas(parent, height=2, bg=C.BG, highlightthickness=0, bd=0)
        line.grid(row=0, column=0, sticky="sew", padx=22)
        line.bind("<Configure>", lambda e: self._draw_header_line(line))

    def _draw_header_line(self, canvas):
        canvas.delete("all")
        w = canvas.winfo_width()
        for x in range(w):
            t = x / max(1, w - 1)
            # 가운데가 밝고 양끝으로 갈수록 배경에 스며드는 선
            glow = math.sin(math.pi * t) ** 0.6
            canvas.create_line(x, 0, x, 2, fill=mix(C.BG, mix(C.A1, C.A2, t), glow * 0.85))

    # ---------- 왼쪽: 파일 영역 ----------
    def _build_left(self, parent):
        left = tk.Frame(parent, bg=C.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        self.dropzone = DropZone(left, self.add_files, self.fonts, height=104)
        if not self.dnd:
            self.dropzone.title_text = "클릭해서 파일을 선택하세요"
            self.dropzone.hint_text = "xlsx · xlsm · docx · pptx  파일을 고를 수 있습니다"
        self.dropzone.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        card = Card(left, "파일 목록", fonts=self.fonts)
        card.grid(row=1, column=0, sticky="nsew")

        tools = tk.Frame(card.head, bg=C.PANEL)
        tools.pack(side="right")
        GhostButton(tools, "폴더 추가", self.add_folder, width=86, height=28,
                    font=self.fonts["small"]).pack(side="left", padx=(0, 6))
        GhostButton(tools, "선택 제거", self.remove_selected, width=86, height=28,
                    font=self.fonts["small"]).pack(side="left", padx=(0, 6))
        GhostButton(tools, "모두 지우기", self.clear_files, width=86, height=28,
                    font=self.fonts["small"]).pack(side="left")

        body = card.body
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            body, style="Dark.Treeview", columns=("name", "size", "parts"),
            show="headings", selectmode="extended", height=8,
        )
        self.tree.heading("name", text="  파일", anchor="w")
        self.tree.heading("size", text="현재 용량", anchor="e")
        self.tree.heading("parts", text="예상 결과", anchor="e")
        self.tree.column("name", anchor="w", stretch=True, minwidth=220)
        self.tree.column("size", anchor="e", width=100, stretch=False)
        self.tree.column("parts", anchor="e", width=100, stretch=False)
        self.tree.tag_configure("odd", background=C.PANEL)
        self.tree.tag_configure("even", background=mix(C.PANEL, "#FFFFFF", 0.025))
        self.tree.tag_configure("done", foreground=C.OK)
        self.tree.tag_configure("fail", foreground=C.ERR)
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview,
                           style="Dark.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns", padx=(4, 0))

        self.empty_label = tk.Label(
            body, text="아직 추가된 파일이 없습니다", bg=C.PANEL, fg=C.FAINT,
            font=self.fonts["base"],
        )

        self._build_log(left)

    def _build_log(self, parent):
        log_card = Card(parent, "진행 상황", fonts=self.fonts, pad=(14, 10))
        log_card.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        lb = log_card.body
        lb.columnconfigure(0, weight=1)

        self.log = tk.Text(lb, height=7, bg=C.PANEL, fg=C.MUTED, relief="flat",
                           font=self.fonts["mono"], wrap="word", state="disabled",
                           highlightthickness=0, insertbackground=C.A2, padx=4, pady=2)
        self.log.grid(row=0, column=0, sticky="ew")
        log_sb = ttk.Scrollbar(lb, orient="vertical", command=self.log.yview,
                               style="Dark.Vertical.TScrollbar")
        self.log.configure(yscrollcommand=log_sb.set)
        log_sb.grid(row=0, column=1, sticky="ns", padx=(4, 0))

        self.log.tag_configure("ok", foreground=C.OK)
        self.log.tag_configure("err", foreground=C.ERR)
        self.log.tag_configure("warn", foreground=C.WARN)
        self.log.tag_configure("head", foreground=C.TEXT)
        self.log.tag_configure("dim", foreground=C.FAINT)

        self._log("파일을 추가하고 '파일 나누기'를 누르세요.", "dim")
        if not self.dnd:
            self._log("(드래그 앤 드롭을 쓰려면 tkinterdnd2 설치가 필요합니다)", "dim")

    # ---------- 오른쪽: 설정 영역 ----------
    def _build_right(self, parent):
        scroller = ui.ScrollFrame(parent, bg=C.BG, width=356,
                                  scrollbar_style="Dark.Vertical.TScrollbar")
        scroller.grid(row=0, column=1, sticky="nsew")
        right = scroller.inner
        right.columnconfigure(0, weight=1)

        # --- 분할 크기
        size_card = Card(right, "분할 크기", fonts=self.fonts)
        size_card.grid(row=0, column=0, sticky="ew")
        b = size_card.body

        entry_row = tk.Frame(b, bg=C.PANEL)
        entry_row.pack(fill="x")

        tk.Label(entry_row, text="한 파일당 최대", bg=C.PANEL, fg=C.MUTED,
                 font=self.fonts["small"]).pack(side="left", padx=(2, 8))

        self.size_entry = tk.Entry(
            entry_row, textvariable=self.size_value, font=self.fonts["num"],
            bg=C.PANEL_HI, fg=C.TEXT, insertbackground=C.A2, relief="flat",
            justify="right", highlightthickness=1, highlightbackground=C.LINE,
            highlightcolor=C.A2, width=5,
        )
        self.size_entry.pack(side="left", ipady=6, fill="x", expand=True)
        self.size_value.trace_add("write", lambda *_: self._on_size_change())

        unit_box = tk.Frame(entry_row, bg=C.PANEL)
        unit_box.pack(side="left", padx=(10, 0))
        self.unit_chips = {}
        for unit in ("MB", "KB"):
            chip = Chip(unit_box, unit, self._set_unit, width=46, height=30,
                        font=self.fonts["small"])
            chip.pack(side="left", padx=(0, 4))
            self.unit_chips[unit] = chip
        self.unit_chips["MB"].set_selected(True)

        preset_row = tk.Frame(b, bg=C.PANEL)
        preset_row.pack(fill="x", pady=(12, 0))
        self.preset_chips = {}
        for preset in PRESETS:
            chip = Chip(preset_row, preset, self._set_preset, width=58, height=28,
                        font=self.fonts["small"])
            chip.pack(side="left", padx=(0, 6))
            self.preset_chips[preset] = chip

        self.size_hint = tk.Label(
            b, text="", bg=C.PANEL, fg=C.FAINT, font=self.fonts["small"],
            anchor="w", justify="left", wraplength=300,
        )
        self.size_hint.pack(fill="x", pady=(10, 0))

        # --- 저장 위치
        out_card = Card(right, "저장 위치", fonts=self.fonts)
        out_card.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        ob = out_card.body

        mode_row = tk.Frame(ob, bg=C.PANEL)
        mode_row.pack(fill="x")
        self.out_chips = {}
        for key, label in (("same", "원본과 같은 폴더"), ("custom", "다른 폴더 지정")):
            chip = Chip(mode_row, label, lambda t, k=key: self._set_output_mode(k),
                        width=140, height=30, font=self.fonts["small"])
            chip.pack(side="left", padx=(0, 8))
            self.out_chips[key] = chip
        self.out_chips["same"].set_selected(True)

        path_row = tk.Frame(ob, bg=C.PANEL)
        path_row.pack(fill="x", pady=(10, 0))
        self.out_entry = tk.Entry(
            path_row, textvariable=self.output_dir, font=self.fonts["small"],
            bg=C.PANEL_HI, fg=C.MUTED, insertbackground=C.A2, relief="flat",
            highlightthickness=1, highlightbackground=C.LINE, highlightcolor=C.A2,
            state="disabled", disabledbackground=C.PANEL, disabledforeground=C.FAINT,
        )
        self.out_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.browse_btn = GhostButton(path_row, "찾아보기", self.browse_output,
                                      width=76, height=27, font=self.fonts["small"])
        self.browse_btn.pack(side="left", padx=(8, 0))
        self.browse_btn.set_enabled(False)

        self.subfolder_toggle = ToggleSwitch(
            ob, "파일마다 '_분할' 폴더를 만들어 정리", value=True,
            font=self.fonts["small"],
        )
        self.subfolder_toggle.pack(fill="x", pady=(12, 0))

        # --- 세부 옵션
        opt_card = Card(right, "세부 옵션", "Excel", fonts=self.fonts)
        opt_card.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        pb = opt_card.body

        self.header_toggle = ToggleSwitch(pb, "머리글(첫 줄)을 모든 파일에 반복",
                                          value=True, font=self.fonts["small"])
        self.header_toggle.pack(fill="x")
        self.formula_toggle = ToggleSwitch(pb, "수식을 계산된 값으로 저장",
                                           value=True, font=self.fonts["small"])
        self.formula_toggle.pack(fill="x", pady=(6, 0))

        mode_label = tk.Label(pb, text="처리 방식", bg=C.PANEL, fg=C.FAINT,
                              font=self.fonts["small"], anchor="w")
        mode_label.pack(fill="x", pady=(12, 6))
        mode_chips = tk.Frame(pb, bg=C.PANEL)
        mode_chips.pack(fill="x")
        self.mode_chips = {}
        for key, label in (("auto", "자동"), ("keep", "서식 유지"), ("fast", "빠르게")):
            chip = Chip(mode_chips, label, lambda t, k=key: self._set_excel_mode(k),
                        width=94, height=28, font=self.fonts["small"])
            chip.pack(side="left", padx=(0, 6))
            self.mode_chips[key] = chip
        self.mode_chips["auto"].set_selected(True)

        tk.Label(pb, text="자동 — 큰 파일은 서식 없이 데이터만 옮겨 빠르게 처리",
                 bg=C.PANEL, fg=C.FAINT, font=self.fonts["small"],
                 anchor="w", justify="left").pack(fill="x", pady=(8, 0))

    # ---------- 아래: 실행 / 진행 / 로그 ----------
    def _build_footer(self, parent):
        footer = tk.Frame(parent, bg=C.BG)
        footer.grid(row=2, column=0, sticky="ew", padx=22, pady=(16, 18))
        footer.columnconfigure(0, weight=1)

        status_row = tk.Frame(footer, bg=C.BG)
        status_row.grid(row=0, column=0, sticky="ew")
        status_row.columnconfigure(0, weight=1)

        self.status_label = tk.Label(status_row, text="준비됨", bg=C.BG, fg=C.MUTED,
                                     font=self.fonts["base"], anchor="w")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.summary_label = tk.Label(status_row, text="", bg=C.BG, fg=C.FAINT,
                                      font=self.fonts["small"], anchor="e")
        self.summary_label.grid(row=0, column=1, sticky="e")

        self.progress = ProgressBar(footer, height=10, bg=C.BG)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        buttons = tk.Frame(footer, bg=C.BG)
        buttons.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(0, weight=1)

        self.open_btn = GhostButton(buttons, "결과 폴더 열기", self.open_output,
                                    width=122, height=44, bg=C.BG,
                                    font=self.fonts["base"])
        self.open_btn.pack(side="right")
        self.open_btn.set_enabled(False)

        self.cancel_btn = GhostButton(buttons, "중지", self.cancel, width=88, height=44,
                                      bg=C.BG, font=self.fonts["base"], accent=C.ERR)
        self.cancel_btn.pack(side="right", padx=(0, 10))
        self.cancel_btn.set_enabled(False)

        self.start_btn = GradientButton(buttons, "파일 나누기", self.start, width=200,
                                        height=44, bg=C.BG, font=self.fonts["button"])
        self.start_btn.pack(side="right", padx=(0, 10))

    # ------------------------------------------------------------------
    # 드래그 앤 드롭
    # ------------------------------------------------------------------
    def _register_dnd(self):
        if not self.dnd:
            return
        try:
            for widget in (self.dropzone, self.tree):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", lambda e: self.dropzone.set_dragging(True))
                widget.dnd_bind("<<DropLeave>>", lambda e: self.dropzone.set_dragging(False))
        except Exception:
            self.dnd = False

    def _on_drop(self, event):
        self.dropzone.set_dragging(False)
        paths = []
        for raw in self.root.tk.splitlist(event.data):
            p = Path(raw)
            if p.is_dir():
                paths.extend(collect_office_files(str(p)))
            else:
                paths.append(str(p))
        self._add_paths(paths)

    # ------------------------------------------------------------------
    # 파일 목록
    # ------------------------------------------------------------------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="나눌 파일 선택",
            filetypes=[
                ("Office 파일", "*.xlsx *.xlsm *.docx *.pptx"),
                ("Excel", "*.xlsx *.xlsm"),
                ("Word", "*.docx"),
                ("PowerPoint", "*.pptx"),
                ("모든 파일", "*.*"),
            ],
        )
        self._add_paths(list(paths))

    def add_folder(self):
        folder = filedialog.askdirectory(title="폴더 선택 (하위 폴더까지 찾습니다)")
        if folder:
            found = collect_office_files(folder)
            if not found:
                messagebox.showinfo(APP_NAME, "선택한 폴더에서 나눌 수 있는 파일을 찾지 못했습니다.")
            self._add_paths(found)

    def _add_paths(self, paths):
        known = {f["path"] for f in self.files}
        added = skipped = 0
        for path in paths:
            p = Path(path)
            if str(p) in known or not p.is_file():
                continue
            if p.suffix.lower() not in SUPPORTED_EXTS:
                skipped += 1
                continue
            self.files.append({"path": str(p), "size": p.stat().st_size, "status": ""})
            known.add(str(p))
            added += 1
        if added:
            self._log(f"{added}개 파일을 목록에 추가했습니다.", "dim")
        if skipped:
            self._log(f"{skipped}개는 지원하지 않는 형식이라 제외했습니다. "
                      f"(가능: xlsx, xlsm, docx, pptx)", "warn")
        self._refresh_files()

    def remove_selected(self):
        selected = set(self.tree.selection())
        if not selected:
            return
        keep = []
        for idx, item in enumerate(self.files):
            if f"F{idx}" not in selected:
                keep.append(item)
        self.files = keep
        self._refresh_files()

    def clear_files(self):
        self.files.clear()
        self._refresh_files()

    def _refresh_files(self):
        self.tree.delete(*self.tree.get_children())
        limit = self.limit_bytes()
        total = 0
        est_parts = 0
        for idx, item in enumerate(self.files):
            size = item["size"]
            total += size
            if limit and size > limit:
                parts = math.ceil(size / limit)
                est = f"{parts}개 예상"
            else:
                parts = 1
                est = "나눌 필요 없음"
            est_parts += parts
            tags = ["even" if idx % 2 else "odd"]
            if item["status"] == "done":
                tags.append("done")
            elif item["status"] == "fail":
                tags.append("fail")
            prefix = {"done": "✓ ", "fail": "! "}.get(item["status"], "")
            self.tree.insert(
                "", "end", iid=f"F{idx}",
                values=(f"  {prefix}{Path(item['path']).name}", human_size(size), est),
                tags=tuple(tags),
            )

        if self.files:
            self.empty_label.place_forget()
            self.summary_label.configure(
                text=f"{len(self.files)}개 파일 · 합계 {human_size(total)} · 결과 약 {est_parts}개"
            )
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
            self.summary_label.configure(text="")
        self._update_hint()

    # ------------------------------------------------------------------
    # 설정 입력
    # ------------------------------------------------------------------
    def limit_bytes(self) -> int:
        """입력된 분할 크기를 바이트로. 잘못된 값이면 0."""
        raw = self.size_value.get().strip().replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            return 0
        if value <= 0:
            return 0
        return int(value * (MB if self.size_unit == "MB" else KB))

    def _on_size_change(self):
        for name, chip in self.preset_chips.items():
            chip.set_selected(name == f"{self.size_value.get().strip()}{self.size_unit}")
        self._refresh_files()

    def _set_unit(self, unit):
        self.size_unit = unit
        for name, chip in self.unit_chips.items():
            chip.set_selected(name == unit)
        self._on_size_change()

    def _set_preset(self, preset):
        value, unit = preset[:-2], preset[-2:]
        self.size_unit = unit
        for name, chip in self.unit_chips.items():
            chip.set_selected(name == unit)
        self.size_value.set(value)

    def _set_output_mode(self, mode):
        self.output_mode = mode
        for key, chip in self.out_chips.items():
            chip.set_selected(key == mode)
        custom = mode == "custom"
        self.out_entry.configure(state="normal" if custom else "disabled")
        self.browse_btn.set_enabled(custom)
        if custom and not self.output_dir.get():
            self.browse_output()

    def _set_excel_mode(self, mode):
        self.excel_mode = mode
        for key, chip in self.mode_chips.items():
            chip.set_selected(key == mode)

    def browse_output(self):
        folder = filedialog.askdirectory(title="결과를 저장할 폴더 선택")
        if folder:
            self.output_dir.set(folder)

    def _update_hint(self):
        limit = self.limit_bytes()
        if not limit:
            self.size_hint.configure(text="숫자를 입력해 주세요. (예: 10)", fg=C.ERR)
            self.start_btn.set_enabled(False)
            return
        self.size_hint.configure(
            text=f"결과 파일은 모두 {human_size(limit)} 이하가 됩니다. "
                 f"업로드 제한보다 5~10% 작게 잡으면 안전합니다.",
            fg=C.FAINT,
        )
        busy = self.worker is not None and self.worker.is_alive()
        self.start_btn.set_enabled(bool(self.files) and not busy)

    # ------------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------------
    def start(self):
        if self.worker and self.worker.is_alive():
            return
        limit = self.limit_bytes()
        if not limit:
            messagebox.showwarning(APP_NAME, "분할 크기를 숫자로 입력해 주세요.")
            return
        if not self.files:
            messagebox.showwarning(APP_NAME, "나눌 파일을 먼저 추가해 주세요.")
            return

        out_dir = None
        if self.output_mode == "custom":
            out_dir = self.output_dir.get().strip()
            if not out_dir:
                messagebox.showwarning(APP_NAME, "저장할 폴더를 지정해 주세요.")
                return
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                messagebox.showerror(APP_NAME, f"저장 폴더를 만들 수 없습니다.\n{e}")
                return

        opts = SplitOptions(
            max_bytes=limit,
            output_dir=out_dir,
            make_subfolder=self.subfolder_toggle.get(),
            repeat_header=self.header_toggle.get(),
            formulas_to_values=self.formula_toggle.get(),
            excel_mode=self.excel_mode,
        )

        for item in self.files:
            item["status"] = ""
        self._refresh_files()
        self._log_clear()
        self._log(f"{len(self.files)}개 파일을 {human_size(limit)} 이하로 나눕니다.", "head")

        self.cancel_event.clear()
        self.start_btn.set_enabled(False)
        self.cancel_btn.set_enabled(True)
        self.open_btn.set_enabled(False)
        self.orb.start()
        self.progress.start()
        self.progress.set(0)
        self.status_label.configure(text="작업 중...", fg=C.TEXT)

        paths = [f["path"] for f in self.files]
        self.worker = threading.Thread(target=self._work, args=(paths, opts), daemon=True)
        self.worker.start()

    def _work(self, paths, opts):
        """백그라운드 스레드. UI 는 큐를 통해서만 건드린다."""
        q = self.queue
        reporter = Reporter(
            log=lambda m: q.put(("log", m, "dim")),
            progress=lambda cur, tot, text: q.put(("prog", cur, tot, text)),
            cancel_event=self.cancel_event,
        )
        ok = failed = skipped = 0
        made = 0
        try:
            for idx, path in enumerate(paths):
                if self.cancel_event.is_set():
                    break
                q.put(("file", idx, len(paths), Path(path).name))
                try:
                    result = split_file(path, opts, reporter)
                    ok += 1
                    made += len(result.parts)
                    q.put(("done_file", idx, str(result.output_dir), len(result.parts)))
                except Cancelled:
                    raise
                except SplitError as e:
                    skipped += 1
                    q.put(("skip_file", idx, str(e)))
                except Exception as e:  # 예상 못한 오류도 다음 파일로 넘어간다
                    failed += 1
                    q.put(("fail_file", idx, f"{type(e).__name__}: {e}"))
            q.put(("finished", ok, skipped, failed, made))
        except Cancelled:
            q.put(("cancelled", ok, made))
        except Exception as e:
            q.put(("fatal", f"{type(e).__name__}: {e}"))

    def cancel(self):
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.cancel_btn.set_enabled(False)
            self.status_label.configure(text="중지하는 중...", fg=C.WARN)

    def open_output(self):
        if self.last_output_dir and Path(self.last_output_dir).exists():
            open_in_explorer(Path(self.last_output_dir))

    # ------------------------------------------------------------------
    # 진행 상황 반영
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]

                if kind == "log":
                    self._log(msg[1], msg[2] if len(msg) > 2 else None)
                elif kind == "prog":
                    _, cur, tot, text = msg
                    if tot:
                        base = self._file_base + (cur / tot) * self._file_span
                        self.progress.set(base)
                    if text:
                        self.status_label.configure(text=f"{self._current_name} — {text}",
                                                    fg=C.TEXT)
                elif kind == "file":
                    _, idx, total, name = msg
                    self._current_name = name
                    self._file_base = idx / total
                    self._file_span = 1 / total
                    self.progress.set(self._file_base)
                    self.status_label.configure(text=f"[{idx + 1}/{total}] {name}", fg=C.TEXT)
                elif kind == "done_file":
                    _, idx, out_dir, parts = msg
                    self.files[idx]["status"] = "done"
                    self.last_output_dir = Path(out_dir)
                    self._log(f"완료: {Path(self.files[idx]['path']).name} → {parts}개 파일", "ok")
                    self._refresh_files()
                elif kind == "skip_file":
                    _, idx, reason = msg
                    self._log(f"건너뜀: {Path(self.files[idx]['path']).name} — {reason}", "warn")
                elif kind == "fail_file":
                    _, idx, reason = msg
                    self.files[idx]["status"] = "fail"
                    self._log(f"실패: {Path(self.files[idx]['path']).name} — {reason}", "err")
                    self._refresh_files()
                elif kind == "finished":
                    _, ok, skipped, failed, made = msg
                    self._finish(f"완료 — 파일 {ok}개를 {made}개로 나눴습니다."
                                 + (f" (건너뜀 {skipped})" if skipped else "")
                                 + (f" (실패 {failed})" if failed else ""),
                                 C.OK if not failed else C.WARN)
                    if ok:
                        messagebox.showinfo(
                            APP_NAME,
                            f"{ok}개 파일을 {made}개로 나눴습니다.\n\n"
                            f"저장 위치: {self.last_output_dir}",
                        )
                    elif skipped and not failed:
                        messagebox.showinfo(APP_NAME, "나눌 파일이 없었습니다. 진행 상황을 확인해 주세요.")
                elif kind == "cancelled":
                    _, ok, made = msg
                    self._finish(f"중지됨 — 그때까지 {ok}개 파일을 처리했습니다.", C.WARN)
                elif kind == "fatal":
                    self._log(msg[1], "err")
                    self._finish("오류로 중단되었습니다.", C.ERR)
                    messagebox.showerror(APP_NAME, msg[1])
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _finish(self, status_text, color):
        self.progress.stop()
        self.progress.set(1.0 if color != C.ERR else 0)
        self.orb.stop()
        self.cancel_btn.set_enabled(False)
        self.status_label.configure(text=status_text, fg=color)
        self.open_btn.set_enabled(self.last_output_dir is not None)
        self._update_hint()
        self._log(status_text, "head")

    # ------------------------------------------------------------------
    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or "dim")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "작업이 진행 중입니다. 정말 종료할까요?"):
                return
            self.cancel_event.set()
        self.root.destroy()

    def run(self):
        # 창을 화면 가운데로
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(0, (self.root.winfo_screenheight() - h) // 2 - 20)
        self.root.geometry(f"+{x}+{y}")
        self.root.mainloop()


def main():
    app = SplitterApp()
    app.run()


if __name__ == "__main__":
    main()
