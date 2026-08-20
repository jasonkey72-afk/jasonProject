"""AI Studio 커스텀 위젯 모음.

tkinter 기본 위젯만으로는 표현하기 어려운 둥근 모서리 / 그라디언트 / 스위치 등을
Canvas 로 직접 그려서 모던한 UI 를 만든다. 외부 라이브러리는 사용하지 않는다.
"""

from __future__ import annotations

import math
import os
import tkinter as tk
from tkinter import ttk

from .theme import C, TONES, lighten, mix, mono_font, ui_font


# ------------------------------------------------------------- 그리기 헬퍼
def rounded_gradient(cv: tk.Canvas, x0, y0, x1, y1, r, c1, c2, tags=()):
    """둥근 사각형을 좌→우 그라디언트로 채운다."""
    w = int(x1 - x0)
    h = int(y1 - y0)
    if w <= 0 or h <= 0:
        return
    r = max(0, min(r, w // 2, h // 2))
    for i in range(w):
        t = i / max(w - 1, 1)
        color = mix(c1, c2, t) if c1 != c2 else c1
        d = max(r - i, r - (w - 1 - i), 0)
        dy = r - math.sqrt(max(r * r - d * d, 0)) if d > 0 else 0
        cv.create_line(x0 + i, y0 + dy, x0 + i, y1 - dy, fill=color, tags=tags)


def rounded_solid(cv: tk.Canvas, x0, y0, x1, y1, r, color, tags=()):
    rounded_gradient(cv, x0, y0, x1, y1, r, color, color, tags=tags)


def rounded_border(cv: tk.Canvas, x0, y0, x1, y1, r, fill, outline, tags=(), width=1):
    """테두리가 있는 둥근 사각형 (바깥 테두리색 → 안쪽 채움색)."""
    rounded_solid(cv, x0, y0, x1, y1, r, outline, tags=tags)
    rounded_solid(cv, x0 + width, y0 + width, x1 - width, y1 - width, max(r - width, 0), fill, tags=tags)


def circle(cv: tk.Canvas, cx, cy, r, **kw):
    return cv.create_oval(cx - r, cy - r, cx + r, cy + r, **kw)


# ------------------------------------------------------------------ 버튼
class Button(tk.Canvas):
    """둥근 모서리 버튼. kind: primary / ghost / subtle / danger."""

    def __init__(self, master, text="", command=None, kind="primary", icon=None,
                 width=None, height=38, font_size=10, bg=None, radius=10, **kw):
        self._bg = bg or master.cget("bg")
        self._text = text
        self._icon = icon
        self._kind = kind
        self._command = command
        self._radius = radius
        self._font = ui_font(font_size, "bold")
        self._enabled = True
        self._hover = False
        self._pressed = False

        label = self._label()
        req_w = width or (self._font.measure(label) + 42)
        super().__init__(master, width=req_w, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=1, **kw)
        self._cw, self._ch = req_w, height

        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    # -- 상태 --------------------------------------------------------
    def _label(self):
        return f"{self._icon}   {self._text}" if self._icon else self._text

    def set_text(self, text):
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if self._enabled else "")
        self._draw()

    def set_command(self, command):
        self._command = command

    # -- 이벤트 ------------------------------------------------------
    def _on_configure(self, event):
        self._cw, self._ch = event.width, event.height
        self._draw()

    def _on_enter(self, _event):
        self._hover = True
        if self._enabled:
            self.configure(cursor="hand2")
        self._draw()

    def _on_leave(self, _event):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event):
        if not self._enabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _event):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._enabled and self._hover and self._command:
            self._command()

    # -- 렌더링 ------------------------------------------------------
    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        if w <= 1 or h <= 1:
            return
        r = self._radius

        if not self._enabled:
            rounded_border(self, 0, 0, w, h, r, C["surface_alt"], C["border"])
            fg = C["text_faint"]
        elif self._kind == "primary":
            c1, c2 = C["accent"], C["accent_2"]
            if self._pressed:
                c1, c2 = mix(c1, "#000000", 0.18), mix(c2, "#000000", 0.18)
            elif self._hover:
                c1, c2 = lighten(c1, 0.12), lighten(c2, 0.12)
            rounded_gradient(self, 0, 0, w, h, r, c1, c2)
            fg = "#0A0D18"
        elif self._kind == "danger":
            fill = mix(C["danger"], C["bg"], 0.72 if not self._hover else 0.6)
            rounded_border(self, 0, 0, w, h, r, fill, mix(C["danger"], C["bg"], 0.45))
            fg = C["danger"]
        elif self._kind == "subtle":
            fill = C["surface_hi"] if not self._hover else C["border"]
            rounded_solid(self, 0, 0, w, h, r, fill)
            fg = C["text"]
        else:  # ghost
            fill = C["surface_alt"] if not self._hover else C["surface_hi"]
            outline = C["border_hi"] if self._hover else C["border"]
            rounded_border(self, 0, 0, w, h, r, fill, outline)
            fg = C["text"] if self._hover else C["text_dim"]

        dy = 1 if self._pressed else 0
        self.create_text(w / 2, h / 2 + dy, text=self._label(), fill=fg, font=self._font)


# ------------------------------------------------------------------ 스위치
class Switch(tk.Canvas):
    """켜기/끄기 토글 스위치 (BooleanVar 연동)."""

    W, H = 46, 26

    def __init__(self, master, variable: tk.BooleanVar, command=None, bg=None):
        self._bg = bg or master.cget("bg")
        self.var = variable
        self._command = command
        self._pos = 1.0 if variable.get() else 0.0
        self._anim = None
        super().__init__(master, width=self.W, height=self.H, bg=self._bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *a: self._animate())
        self._draw()

    def _toggle(self, _event=None):
        self.var.set(not self.var.get())
        if self._command:
            self._command()

    def _animate(self):
        target = 1.0 if self.var.get() else 0.0
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        self._step(target)

    def _step(self, target):
        delta = target - self._pos
        if abs(delta) < 0.06:
            self._pos = target
            self._draw()
            return
        self._pos += delta * 0.35
        self._draw()
        self._anim = self.after(16, lambda: self._step(target))

    def _draw(self):
        self.delete("all")
        p = self._pos
        track_off, track_on = C["surface_hi"], C["accent"]
        rounded_gradient(self, 0, 0, self.W, self.H, self.H // 2,
                         mix(track_off, track_on, p), mix(track_off, C["accent_2"], p))
        if p < 0.5:
            rounded_border(self, 0, 0, self.W, self.H, self.H // 2, C["surface_hi"], C["border"])
        knob_r = 9
        cx = 4 + knob_r + p * (self.W - 2 * (4 + knob_r))
        circle(self, cx, self.H / 2, knob_r, fill="#F4F7FF" if p > 0.5 else C["text_dim"], outline="")


class LabeledSwitch(tk.Frame):
    """스위치 + 설명 텍스트 한 줄."""

    def __init__(self, master, text, variable, desc=None, command=None, bg=None):
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg)
        self.switch = Switch(self, variable, command=command, bg=bg)
        self.switch.grid(row=0, column=0, rowspan=2 if desc else 1, sticky="w", padx=(0, 12))
        tk.Label(self, text=text, bg=bg, fg=C["text"], font=ui_font(10)).grid(row=0, column=1, sticky="w")
        if desc:
            tk.Label(self, text=desc, bg=bg, fg=C["text_faint"], font=ui_font(8)).grid(
                row=1, column=1, sticky="w", pady=(1, 0))
        self.columnconfigure(1, weight=1)


# -------------------------------------------------------- 세그먼트 컨트롤
class Segmented(tk.Canvas):
    """라디오 버튼 대신 쓰는 분할 선택 컨트롤."""

    def __init__(self, master, options, variable: tk.StringVar, command=None,
                 bg=None, height=36, min_seg=110):
        self._bg = bg or master.cget("bg")
        self.options = list(options)  # [(value, label), ...]
        self.var = variable
        self._command = command
        self._font = ui_font(9, "bold")
        seg_w = max(min_seg, max(self._font.measure(lbl) for _v, lbl in self.options) + 34)
        width = seg_w * len(self.options) + 8
        super().__init__(master, width=width, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._cw, self._ch = width, height
        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_click)
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _on_configure(self, event):
        self._cw, self._ch = event.width, event.height
        self._draw()

    def _seg_width(self):
        return (self._cw - 8) / max(len(self.options), 1)

    def _on_click(self, event):
        idx = int((event.x - 4) // max(self._seg_width(), 1))
        idx = max(0, min(idx, len(self.options) - 1))
        value = self.options[idx][0]
        if value != self.var.get():
            self.var.set(value)
            if self._command:
                self._command(value)

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        if w <= 1:
            return
        rounded_border(self, 0, 0, w, h, h // 2, C["surface_alt"], C["border"])
        sw = self._seg_width()
        current = self.var.get()
        for i, (value, label) in enumerate(self.options):
            x0 = 4 + i * sw
            x1 = x0 + sw
            active = value == current
            if active:
                rounded_gradient(self, x0, 4, x1, h - 4, (h - 8) // 2, C["accent"], C["accent_2"])
            self.create_text((x0 + x1) / 2, h / 2, text=label,
                             fill="#0A0D18" if active else C["text_dim"], font=self._font)


# ------------------------------------------------------------- 진행 표시
class ProgressBar(tk.Canvas):
    """그라디언트 진행 바 (불확정 모드 애니메이션 지원)."""

    def __init__(self, master, bg=None, height=10, radius=5):
        self._bg = bg or master.cget("bg")
        super().__init__(master, height=height, bg=self._bg, highlightthickness=0, bd=0)
        self._ch = height
        self._cw = 1
        self._radius = radius
        self._fraction = 0.0
        self._pulse = False
        self._phase = 0.0
        self._anim = None
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        self._cw, self._ch = event.width, event.height
        self._draw()

    def set_fraction(self, fraction: float):
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self._draw()

    def reset(self):
        self.stop_pulse()
        self.set_fraction(0.0)

    def start_pulse(self):
        if self._pulse:
            return
        self._pulse = True
        self._tick()

    def stop_pulse(self):
        self._pulse = False
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        self._draw()

    def _tick(self):
        if not self._pulse:
            return
        self._phase = (self._phase + 0.022) % 1.0
        self._draw()
        self._anim = self.after(28, self._tick)

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        if w <= 2:
            return
        rounded_solid(self, 0, 0, w, h, self._radius, C["surface_hi"])
        if self._pulse:
            band = w * 0.28
            x0 = -band + (w + band) * self._phase
            x1 = min(w, x0 + band)
            x0 = max(0, x0)
            if x1 - x0 > 2:
                rounded_gradient(self, x0, 0, x1, h, self._radius, C["accent"], C["accent_2"])
        elif self._fraction > 0:
            fw = max(self._radius * 2, w * self._fraction)
            rounded_gradient(self, 0, 0, fw, h, self._radius, C["accent"], C["accent_2"])


# ------------------------------------------------------------------- 칩
class Chip(tk.Canvas):
    """상태 배지 (점 + 텍스트)."""

    def __init__(self, master, text="", tone="neutral", bg=None, height=26):
        self._bg = bg or master.cget("bg")
        self._text = text
        self._tone = tone
        self._font = ui_font(8, "bold")
        super().__init__(master, height=height, width=self._font.measure(text) + 40,
                         bg=self._bg, highlightthickness=0, bd=0)
        self._ch = height
        self.bind("<Configure>", self._on_configure)
        self._cw = self._font.measure(text) + 40
        self._draw()

    def _on_configure(self, event):
        self._cw, self._ch = event.width, event.height
        self._draw()

    def set(self, text=None, tone=None):
        if text is not None:
            self._text = text
        if tone is not None:
            self._tone = tone
        want = self._font.measure(self._text) + 40
        if want != int(self.cget("width")):
            self.configure(width=want)
            self._cw = want
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        if w <= 2:
            return
        color = TONES.get(self._tone, C["text_dim"])
        rounded_border(self, 0, 0, w, h, h // 2, mix(color, C["bg"], 0.86), mix(color, C["bg"], 0.68))
        circle(self, 14, h / 2, 3.5, fill=color, outline="")
        self.create_text(24, h / 2, text=self._text, anchor="w", fill=color, font=self._font)


# ------------------------------------------------------------------ 카드
class Card(tk.Frame):
    """제목 + 설명 + 본문(body) 구조의 카드 컨테이너."""

    def __init__(self, master, title=None, desc=None, icon=None, bg=None, pad=18):
        bg = bg or C["surface"]
        super().__init__(master, bg=bg, highlightthickness=1,
                         highlightbackground=C["border"], highlightcolor=C["border"])
        self.bg = bg
        if title:
            head = tk.Frame(self, bg=bg)
            head.pack(fill="x", padx=pad, pady=(pad, 0))
            if icon:
                badge = tk.Canvas(head, width=34, height=34, bg=bg, highlightthickness=0, bd=0)
                badge.pack(side="left", padx=(0, 12))
                rounded_solid(badge, 0, 0, 34, 34, 10, C["accent_soft"])
                badge.create_text(17, 17, text=icon, fill=C["accent_2"], font=ui_font(13, "bold"))
            titles = tk.Frame(head, bg=bg)
            titles.pack(side="left", fill="x", expand=True)
            tk.Label(titles, text=title, bg=bg, fg=C["text"], font=ui_font(11, "bold")).pack(anchor="w")
            if desc:
                tk.Label(titles, text=desc, bg=bg, fg=C["text_faint"],
                         font=ui_font(8), justify="left").pack(anchor="w", pady=(2, 0))
            self.head = head
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=(14 if title else pad, pad))


class FormRow(tk.Frame):
    """라벨 + 입력 위젯 한 줄을 만들기 위한 헬퍼."""

    def __init__(self, master, label, bg=None, width=132, hint=None, expand=False):
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg)
        wrap = tk.Frame(self, bg=bg, width=width)
        wrap.pack(side="left", fill="y")
        wrap.pack_propagate(False)
        tk.Label(wrap, text=label, bg=bg, fg=C["text_dim"], font=ui_font(9)).pack(anchor="w", pady=(6, 0))
        self.field = tk.Frame(self, bg=bg)
        self.field.pack(side="left", fill="x", expand=expand)
        if hint:
            tk.Label(self, text=hint, bg=bg, fg=C["text_faint"],
                     font=ui_font(8)).pack(side="left", padx=(14, 0))


# ------------------------------------------------------------ 스크롤 영역
class ScrollArea(tk.Frame):
    """세로 스크롤이 되는 콘텐츠 영역. 내용은 self.inner 에 배치한다."""

    def __init__(self, master, bg=None, gutter=14):
        bg = bg or C["bg"]
        super().__init__(master, bg=bg)
        self._gutter = gutter  # 내용과 스크롤바 사이 여백
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", style="AI.Vertical.TScrollbar",
                                    command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll_set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda e: self._bind_wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._bind_wheel(False))

    def _on_scroll_set(self, first, last):
        # 내용이 다 보이면 스크롤바를 숨긴다
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scroll.pack_forget()
        else:
            self.scroll.pack(side="right", fill="y")
        self.scroll.set(first, last)

    def _on_inner_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=max(event.width - self._gutter, 1))

    def _bind_wheel(self, active):
        if active:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
            self.canvas.bind_all("<Button-4>", self._on_wheel)
            self.canvas.bind_all("<Button-5>", self._on_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


# ----------------------------------------------------------- 로그 콘솔
class LogConsole(tk.Frame):
    """작업 로그 출력 영역."""

    LEVEL_COLORS = {
        "info": C["text_dim"],
        "ok": C["success"],
        "error": C["danger"],
        "warn": C["warning"],
        "head": C["accent_2"],
    }

    def __init__(self, master, height=9, bg=None):
        bg = bg or C["surface_alt"]
        super().__init__(master, bg=bg, highlightthickness=1, highlightbackground=C["border"])
        self.text = tk.Text(
            self, height=height, bg=bg, fg=C["text_dim"], bd=0, highlightthickness=0,
            font=mono_font(9), wrap="word", padx=12, pady=10, state="disabled",
            insertbackground=C["accent_2"], selectbackground=C["accent_soft"],
            selectforeground=C["text"],
        )
        scroll = ttk.Scrollbar(self, orient="vertical", style="AI.Vertical.TScrollbar",
                               command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for level, color in self.LEVEL_COLORS.items():
            self.text.tag_configure(level, foreground=color)

    def write(self, message, level="info"):
        self.text.configure(state="normal")
        self.text.insert("end", message + "\n", level)
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


# ------------------------------------------------------- 파일 목록 패널
class FileQueue(tk.Frame):
    """변환 대상 파일 목록 + 추가/삭제 도구모음 (여러 화면에서 재사용)."""

    def __init__(self, master, extensions, filetype_label, bg=None, height=8,
                 on_change=None, empty_text="아직 추가된 파일이 없습니다"):
        bg = bg or C["surface"]
        super().__init__(master, bg=bg)
        self.extensions = tuple(e.lower() for e in extensions)
        self.filetype_label = filetype_label
        self.on_change = on_change
        self.empty_text = empty_text
        self._paths: list[str] = []

        bar = tk.Frame(self, bg=bg)
        bar.pack(fill="x")
        Button(bar, "파일 추가", icon="＋", command=self.add_files, kind="ghost",
               bg=bg, height=34, font_size=9).pack(side="left")
        Button(bar, "폴더 추가", icon="＋", command=self.add_folder, kind="ghost",
               bg=bg, height=34, font_size=9).pack(side="left", padx=6)
        Button(bar, "선택 제거", command=self.remove_selected, kind="ghost",
               bg=bg, height=34, font_size=9).pack(side="left", padx=(0, 6))
        Button(bar, "전체 지우기", command=self.clear, kind="ghost",
               bg=bg, height=34, font_size=9).pack(side="left")
        self.count_label = tk.Label(bar, text="0개", bg=bg, fg=C["accent_2"], font=ui_font(9, "bold"))
        self.count_label.pack(side="right")

        table = tk.Frame(self, bg=C["surface_alt"], highlightthickness=1, highlightbackground=C["border"])
        table.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(table, style="AI.Treeview", columns=("name", "folder"),
                                 show="headings", height=height, selectmode="extended")
        self.tree.heading("name", text="파일 이름", anchor="w")
        self.tree.heading("folder", text="폴더 위치", anchor="w")
        self.tree.column("name", width=280, anchor="w", stretch=False)
        self.tree.column("folder", width=380, anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", style="AI.Vertical.TScrollbar",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background=C["surface"])
        self.tree.bind("<Delete>", lambda e: self.remove_selected())

        self.empty_label = tk.Label(table, text=empty_text, bg=C["surface_alt"],
                                    fg=C["text_faint"], font=ui_font(9))
        self._sync_empty()

    # -- 데이터 -----------------------------------------------------
    def paths(self):
        return list(self._paths)

    def count(self):
        return len(self._paths)

    def add_paths(self, paths):
        added = 0
        for path in paths:
            norm = os.path.normpath(path)
            if norm in self._paths:
                continue
            self._paths.append(norm)
            added += 1
        if added:
            self._refresh()
        return added

    def add_files(self):
        from tkinter import filedialog
        pattern = " ".join(f"*{e}" for e in self.extensions)
        paths = filedialog.askopenfilenames(
            title=f"{self.filetype_label} 선택",
            filetypes=[(self.filetype_label, pattern), ("모든 파일", "*.*")],
        )
        if paths:
            self.add_paths(paths)

    def add_folder(self):
        from tkinter import filedialog, messagebox
        folder = filedialog.askdirectory(title="폴더 선택 (하위 폴더까지 검색)")
        if not folder:
            return
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(self.extensions) and not name.startswith("~$"):
                    found.append(os.path.join(root, name))
        added = self.add_paths(sorted(found))
        if added == 0:
            messagebox.showinfo("알림", "선택한 폴더에서 대상 파일을 찾지 못했습니다.")

    def remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        indexes = sorted((self.tree.index(iid) for iid in selected), reverse=True)
        for idx in indexes:
            del self._paths[idx]
        self._refresh()

    def clear(self):
        self._paths.clear()
        self._refresh()

    # -- 표시 -------------------------------------------------------
    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, path in enumerate(self._paths):
            folder, name = os.path.split(path)
            self.tree.insert("", "end", values=(name, folder), tags=("odd",) if i % 2 else ())
        self.count_label.configure(text=f"{len(self._paths)}개")
        self._sync_empty()
        if self.on_change:
            self.on_change(len(self._paths))

    def _sync_empty(self):
        if self._paths:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")


# -------------------------------------------------------- 경로 선택 위젯
class PathPicker(tk.Frame):
    """폴더 경로 입력 + 찾아보기 버튼."""

    def __init__(self, master, variable: tk.StringVar, bg=None, title="폴더 선택", mode="dir"):
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg)
        self.var = variable
        self.mode = mode
        self.title = title
        self.entry = ttk.Entry(self, textvariable=variable, style="AI.TEntry", font=ui_font(9))
        self.entry.pack(side="left", fill="x", expand=True)
        self.button = Button(self, "찾아보기", command=self.browse, kind="ghost",
                             bg=bg, height=32, font_size=9, width=96)
        self.button.pack(side="left", padx=(8, 0))

    def browse(self):
        from tkinter import filedialog
        if self.mode == "dir":
            path = filedialog.askdirectory(title=self.title)
        else:
            path = filedialog.asksaveasfilename(title=self.title)
        if path:
            self.var.set(os.path.normpath(path))

    def set_enabled(self, enabled: bool):
        self.entry.configure(state="normal" if enabled else "disabled")
        self.button.set_enabled(enabled)


# --------------------------------------------------------- 실행 패널
class RunPanel(tk.Frame):
    """실행 버튼 + 진행바 + 상태 텍스트 + 로그 콘솔 묶음."""

    def __init__(self, master, run_text, on_run, on_cancel=None, bg=None, log_height=9):
        bg = bg or C["surface"]
        super().__init__(master, bg=bg)
        top = tk.Frame(self, bg=bg)
        top.pack(fill="x")

        self.run_button = Button(top, run_text, command=on_run, kind="primary",
                                 icon="▶", bg=bg, height=42, font_size=10)
        self.run_button.pack(side="left")
        self.cancel_button = Button(top, "중지", command=on_cancel, kind="danger",
                                    bg=bg, height=42, font_size=9, width=80)
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.cancel_button.set_enabled(False)

        meter = tk.Frame(top, bg=bg)
        meter.pack(side="left", fill="x", expand=True, padx=(18, 0))
        self.status = tk.Label(meter, text="대기 중", bg=bg, fg=C["text_dim"],
                               font=ui_font(9), anchor="w")
        self.status.pack(fill="x", pady=(2, 6))
        self.progress = ProgressBar(meter, bg=bg, height=10)
        self.progress.pack(fill="x")

        self.log = LogConsole(self, height=log_height)
        self.log.pack(fill="both", expand=True, pady=(16, 0))

    def set_running(self, running: bool, run_text=None):
        self.run_button.set_enabled(not running)
        self.cancel_button.set_enabled(running)
        if run_text:
            self.run_button.set_text(run_text)
        if running:
            self.progress.set_fraction(0.0)
        else:
            self.progress.stop_pulse()

    def set_status(self, text):
        self.status.configure(text=text)


# ------------------------------------------------------------ 로고 오브
class LogoOrb(tk.Canvas):
    """사이드바 상단에서 은은하게 맥동하는 AI 로고."""

    def __init__(self, master, size=40, bg=None):
        self._bg = bg or master.cget("bg")
        super().__init__(master, width=size, height=size, bg=self._bg, highlightthickness=0, bd=0)
        self._size = size
        self._phase = 0.0
        self._running = True
        self._tick()

    def stop(self):
        self._running = False

    def _tick(self):
        if not self._running:
            return
        self._phase = (self._phase + 0.018) % 1.0
        self._draw()
        self.after(60, self._tick)

    def _draw(self):
        self.delete("all")
        s = self._size
        cx = cy = s / 2
        glow = 0.5 + 0.5 * math.sin(self._phase * 2 * math.pi)
        # 바깥 후광
        for i in range(4, 0, -1):
            r = s / 2 * (0.55 + i * 0.11) * (0.96 + 0.06 * glow)
            color = mix(self._bg, mix(C["accent"], C["accent_2"], glow), 0.10 + 0.05 * (4 - i))
            circle(self, cx, cy, r, fill=color, outline="")
        # 본체
        rounded_gradient(self, cx - s * 0.28, cy - s * 0.28, cx + s * 0.28, cy + s * 0.28,
                         int(s * 0.28), mix(C["accent"], "#FFFFFF", 0.1 * glow), C["accent_2"])
        self.create_text(cx, cy, text="AI", fill="#08101C", font=ui_font(int(s * 0.24), "bold"))
