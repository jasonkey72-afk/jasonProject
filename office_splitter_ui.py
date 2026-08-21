"""
Office 파일 분할기 — 화면 구성 요소 (다크 테마 / 모던 UI)
=========================================================
tkinter 기본 위젯만으로는 세련된 느낌을 내기 어려워, 캔버스에 직접 그리는
버튼·토글·칩·진행바·AI 오브를 이 파일에 모아 두었다.
(프로그램 로직은 office_file_splitter.py, 분할 기능은 splitter_core.py)
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont, ttk


# ---------------------------------------------------------------------------
# 색상 팔레트
# ---------------------------------------------------------------------------

class C:
    BG = "#0B0E14"          # 창 배경 (딥 네이비 블랙)
    PANEL = "#131824"       # 카드 배경
    PANEL_HI = "#1A2130"    # 카드 위 강조 영역
    LINE = "#232C3D"        # 경계선
    TEXT = "#E8ECF4"        # 기본 글자
    MUTED = "#8B97AD"       # 보조 글자
    FAINT = "#5C6880"       # 더 흐린 글자

    A1 = "#6D5DFB"          # 그라데이션 시작 (바이올렛)
    A2 = "#22D3EE"          # 그라데이션 끝 (시안)
    A_SOFT = "#2A2C55"      # 선택 배경
    OK = "#34D399"
    WARN = "#FBBF24"
    ERR = "#F87171"


FONT_CANDIDATES = [
    "Pretendard", "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo",
    "Noto Sans KR", "Segoe UI", "DejaVu Sans",
]
MONO_CANDIDATES = [
    "Cascadia Mono", "Consolas", "D2Coding", "Menlo", "DejaVu Sans Mono", "Courier New",
]


def pick_family(root, candidates):
    families = set(tkfont.families(root))
    for name in candidates:
        if name in families:
            return name
    return tkfont.nametofont("TkDefaultFont").cget("family")


# ---------------------------------------------------------------------------
# 그리기 도우미
# ---------------------------------------------------------------------------

def hex_to_rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def mix(c1: str, c2: str, t: float) -> str:
    """두 색을 t(0~1) 비율로 섞는다."""
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def rounded_points(x0, y0, x1, y1, r):
    """둥근 사각형용 좌표 (create_polygon 의 smooth 옵션과 함께 사용)."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]


def draw_round_rect(canvas, x0, y0, x1, y1, r, **kwargs):
    return canvas.create_polygon(rounded_points(x0, y0, x1, y1, r), smooth=True, **kwargs)


def draw_round_gradient(canvas, x0, y0, x1, y1, r, c1, c2, tags=""):
    """
    둥근 모서리 가로 그라데이션.
    세로선을 한 줄씩 그리되, 모서리 부분은 원 모양만큼 위아래를 깎아 둥글게 만든다.
    """
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    r = int(max(0, min(r, w / 2, h / 2)))
    for i in range(w):
        dx = min(i, w - 1 - i)
        if dx < r:
            inset = r - int(math.sqrt(max(0, r * r - (r - dx - 0.5) ** 2)))
        else:
            inset = 0
        color = mix(c1, c2, i / max(1, w - 1))
        canvas.create_line(
            x0 + i, y0 + inset, x0 + i, y1 - inset, fill=color, tags=tags,
        )


# ---------------------------------------------------------------------------
# AI 오브 — 회전하는 링과 맥동하는 코어
# ---------------------------------------------------------------------------

class AIOrb(tk.Canvas):
    """작업 중일 때 살아 움직이는 느낌을 주는 장식 요소."""

    def __init__(self, master, size=46, bg=C.BG):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self.size = size
        self.phase = 0.0
        self.busy = False
        self._tick()

    def start(self):
        self.busy = True

    def stop(self):
        self.busy = False

    def _tick(self):
        self.delete("all")
        s = self.size
        cx = cy = s / 2
        speed = 7.0 if self.busy else 1.4
        self.phase = (self.phase + speed) % 360
        pulse = (math.sin(math.radians(self.phase * (3 if self.busy else 1.2))) + 1) / 2

        # 바깥 링 3개 (각각 다른 속도/각도로 회전)
        for i, (ratio, extent, width, t) in enumerate(
            ((0.94, 110, 2, 0.0), (0.72, 150, 2, 0.45), (0.52, 90, 2, 0.85))
        ):
            rr = s / 2 * ratio - 1
            angle = self.phase * (1 + i * 0.6) * (1 if i % 2 == 0 else -1)
            self.create_arc(
                cx - rr, cy - rr, cx + rr, cy + rr,
                start=angle, extent=extent, style=tk.ARC,
                outline=mix(C.A1, C.A2, t), width=width,
            )

        # 가운데 코어
        core = s / 2 * (0.16 + 0.10 * pulse)
        glow = s / 2 * (0.26 + 0.14 * pulse)
        self.create_oval(cx - glow, cy - glow, cx + glow, cy + glow,
                         fill=mix(C.BG, C.A1, 0.35 + 0.25 * pulse), outline="")
        self.create_oval(cx - core, cy - core, cx + core, cy + core,
                         fill=mix(C.A2, "#FFFFFF", 0.25 * pulse), outline="")

        self.after(40 if self.busy else 70, self._tick)


# ---------------------------------------------------------------------------
# 버튼
# ---------------------------------------------------------------------------

class GradientButton(tk.Canvas):
    """그라데이션 채움 + 둥근 모서리 기본 버튼."""

    def __init__(self, master, text, command, width=210, height=46,
                 bg=C.PANEL, c1=C.A1, c2=C.A2, radius=12, font=None, fg="#FFFFFF"):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.command = command
        self.text = text
        self.c1, self.c2, self.radius, self.fg = c1, c2, radius, fg
        self.font = font or ("TkDefaultFont", 11, "bold")
        self.state_ = "normal"
        self._hover = False
        self._press = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_text(self, text):
        self.text = text
        self._draw()

    def set_enabled(self, enabled: bool):
        self.state_ = "normal" if enabled else "disabled"
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = self._press = False
        self._draw()

    def _on_press(self, _e):
        if self.state_ == "normal":
            self._press = True
            self._draw()

    def _on_release(self, _e):
        was = self._press
        self._press = False
        self._draw()
        if was and self.state_ == "normal" and self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])
        pad = 1 if not self._press else 2

        if self.state_ == "disabled":
            c1 = c2 = C.PANEL_HI
            fg = C.FAINT
        else:
            t = 0.16 if self._hover else 0.0
            c1 = mix(self.c1, "#FFFFFF", t)
            c2 = mix(self.c2, "#FFFFFF", t)
            fg = self.fg

        draw_round_gradient(self, pad, pad, w - pad, h - pad, self.radius, c1, c2)
        self.create_text(w / 2, h / 2 + (1 if self._press else 0),
                         text=self.text, fill=fg, font=self.font)


class GhostButton(tk.Canvas):
    """테두리만 있는 보조 버튼."""

    def __init__(self, master, text, command, width=110, height=34,
                 bg=C.PANEL, radius=9, font=None, fg=C.MUTED, accent=C.A2):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.command = command
        self.text = text
        self.radius, self.fg, self.accent = radius, fg, accent
        self.font = font or ("TkDefaultFont", 10)
        self.enabled = True
        self._hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: (setattr(self, "_hover", True), self._draw()))
        self.bind("<Leave>", lambda e: (setattr(self, "_hover", False), self._draw()))
        self.bind("<Button-1>", lambda e: self.command() if self.enabled and self.command else None)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_text(self, text):
        self.text = text
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])
        if not self.enabled:
            outline, fg, fill = C.LINE, C.FAINT, ""
        elif self._hover:
            outline, fg, fill = self.accent, C.TEXT, mix(C.PANEL, self.accent, 0.12)
        else:
            outline, fg, fill = C.LINE, self.fg, ""
        draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius,
                        fill=fill or "", outline=outline, width=1)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)


class Chip(tk.Canvas):
    """선택형 알약 버튼 (프리셋 용량, 저장 위치 선택 등)."""

    def __init__(self, master, text, command=None, width=64, height=30,
                 bg=C.PANEL, font=None):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text = text
        self.command = command
        self.font = font or ("TkDefaultFont", 10)
        self.selected = False
        self._hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: (setattr(self, "_hover", True), self._draw()))
        self.bind("<Leave>", lambda e: (setattr(self, "_hover", False), self._draw()))
        self.bind("<Button-1>", self._click)

    def _click(self, _e):
        if self.command:
            self.command(self.text)

    def set_selected(self, value: bool):
        self.selected = value
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])
        r = h / 2
        if self.selected:
            draw_round_gradient(self, 0, 0, w, h, r, C.A1, C.A2)
            fg = "#FFFFFF"
        else:
            fill = mix(C.PANEL, "#FFFFFF", 0.06 if self._hover else 0.03)
            outline = C.A2 if self._hover else C.LINE
            draw_round_rect(self, 1, 1, w - 1, h - 1, r, fill=fill, outline=outline, width=1)
            fg = C.TEXT if self._hover else C.MUTED
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)


class ToggleSwitch(tk.Canvas):
    """켜짐/꺼짐 스위치 (부드럽게 움직인다)."""

    def __init__(self, master, text, value=True, command=None, bg=C.PANEL,
                 font=None, width=300, height=28):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text = text
        self.value = value
        self.command = command
        self.font = font or ("TkDefaultFont", 10)
        self._pos = 1.0 if value else 0.0
        self._anim = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._click)

    def get(self):
        return self.value

    def set(self, value: bool):
        self.value = bool(value)
        self._animate()

    def _click(self, _e):
        self.value = not self.value
        self._animate()
        if self.command:
            self.command(self.value)

    def _animate(self):
        target = 1.0 if self.value else 0.0
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
        step = 0.18 if target > self._pos else -0.18
        if abs(target - self._pos) < 0.02:
            self._pos = target
            self._draw()
            return
        self._pos = max(0.0, min(1.0, self._pos + step))
        self._draw()
        self._anim = self.after(12, self._animate)

    def _draw(self):
        self.delete("all")
        h = self.winfo_height() or int(self["height"])
        sw, sh = 38, 20
        y0 = (h - sh) / 2
        track = mix(C.PANEL_HI, C.A1, self._pos * 0.85)
        draw_round_rect(self, 0, y0, sw, y0 + sh, sh / 2, fill=track,
                        outline=mix(C.LINE, C.A2, self._pos), width=1)
        knob_r = sh / 2 - 3
        kx = 3 + knob_r + (sw - 2 * (3 + knob_r)) * self._pos
        ky = y0 + sh / 2
        self.create_oval(kx - knob_r, ky - knob_r, kx + knob_r, ky + knob_r,
                         fill="#FFFFFF" if self.value else C.MUTED, outline="")
        self.create_text(sw + 12, h / 2, text=self.text, anchor="w",
                         fill=C.TEXT if self.value else C.MUTED, font=self.font)


# ---------------------------------------------------------------------------
# 진행바
# ---------------------------------------------------------------------------

class ProgressBar(tk.Canvas):
    """둥근 그라데이션 진행바. 작업 중에는 빛이 흐르는 효과가 나타난다."""

    def __init__(self, master, height=10, bg=C.BG):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self.h = height
        self.value = 0.0
        self.busy = False
        self._shine = 0.0
        self.bind("<Configure>", lambda e: self._draw())
        self._tick()

    def set(self, fraction: float):
        self.value = max(0.0, min(1.0, fraction))
        self._draw()

    def start(self):
        self.busy = True

    def stop(self):
        self.busy = False
        self._draw()

    def _tick(self):
        if self.busy:
            self._shine = (self._shine + 0.022) % 1.35
            self._draw()
        self.after(33, self._tick)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.h
        if w <= 2:
            return
        r = h / 2
        draw_round_rect(self, 0, 0, w, h, r, fill=C.PANEL_HI, outline="")
        fill_w = int(w * self.value)
        if fill_w > 2:
            draw_round_gradient(self, 0, 0, fill_w, h, r, C.A1, C.A2)
            if self.busy:
                # 진행된 구간 위로 밝은 빛이 지나간다
                sx = int(fill_w * (self._shine / 1.35))
                for i in range(-14, 15):
                    x = sx + i
                    if 1 <= x < fill_w - 1:
                        t = (1 - abs(i) / 15) * 0.5
                        base = mix(C.A1, C.A2, x / max(1, fill_w))
                        self.create_line(x, 1, x, h - 1, fill=mix(base, "#FFFFFF", t))


# ---------------------------------------------------------------------------
# 카드 / 드롭존
# ---------------------------------------------------------------------------

class Card(tk.Frame):
    """제목이 있는 카드 컨테이너. 내용은 card.body 에 넣는다."""

    def __init__(self, master, title=None, subtitle=None, fonts=None, pad=(14, 12)):
        super().__init__(master, bg=C.PANEL, highlightthickness=1,
                         highlightbackground=C.LINE, highlightcolor=C.LINE, bd=0)
        fonts = fonts or {}
        px, py = pad
        if title:
            head = tk.Frame(self, bg=C.PANEL)
            head.pack(fill="x", padx=px, pady=(py, 0))
            tk.Label(head, text=title, bg=C.PANEL, fg=C.TEXT,
                     font=fonts.get("card_title", ("TkDefaultFont", 11, "bold"))).pack(side="left")
            if subtitle:
                tk.Label(head, text=subtitle, bg=C.PANEL, fg=C.FAINT,
                         font=fonts.get("small", ("TkDefaultFont", 9))).pack(side="left", padx=(8, 0))
            self.head = head
        self.body = tk.Frame(self, bg=C.PANEL)
        self.body.pack(fill="both", expand=True, padx=px, pady=(8, py))


class ScrollFrame(tk.Frame):
    """
    세로로 스크롤되는 영역. 위젯은 .inner 안에 넣는다.
    창이 작은 노트북에서도 설정 항목이 잘려서 안 보이는 일이 없도록 사용한다.
    (내용이 다 보일 때는 스크롤바가 나타나지 않는다)
    """

    def __init__(self, master, bg=C.BG, width=340, scrollbar_style="Vertical.TScrollbar"):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=width)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", style=scrollbar_style,
                                       command=self.canvas.yview)
        self._bar_shown = False
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)

        self.inner.bind("<Configure>", lambda e: self._sync())
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._on_wheel, add="+")

    def _on_scroll(self, first, last):
        """내용이 다 보이면 스크롤바를 숨기고, 넘칠 때만 보여 준다."""
        self.scrollbar.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self._bar_shown:
            self.scrollbar.pack(side="right", fill="y", padx=(4, 0))
            self._bar_shown = True
        elif not needed and self._bar_shown:
            self.scrollbar.pack_forget()
            self._bar_shown = False

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync()

    def _sync(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _scrollable(self) -> bool:
        return self.inner.winfo_reqheight() > self.canvas.winfo_height()

    def _on_wheel(self, event):
        """포인터가 이 영역 안에 있을 때만 스크롤한다."""
        if not self._scrollable():
            return
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while widget is not None:
            if widget is self:
                break
            widget = getattr(widget, "master", None)
        else:
            return
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 2, "units")


class DropZone(tk.Canvas):
    """파일을 끌어다 놓거나 클릭해서 고르는 영역."""

    def __init__(self, master, on_click, fonts, height=118, bg=C.BG):
        super().__init__(master, height=height, bg=bg, highlightthickness=0,
                         bd=0, cursor="hand2")
        self.on_click = on_click
        self.fonts = fonts
        self.hover = False
        self.dragging = False
        self.title_text = "여기에 파일을 끌어다 놓으세요"
        self.hint_text = "또는 클릭해서 선택  ·  xlsx · xlsm · docx · pptx"
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: (setattr(self, "hover", True), self._draw()))
        self.bind("<Leave>", lambda e: (setattr(self, "hover", False), self._draw()))
        self.bind("<Button-1>", lambda e: self.on_click())

    def set_dragging(self, value: bool):
        self.dragging = value
        self._draw()

    def _dashed_round_rect(self, x0, y0, x1, y1, r, color, dash=(6, 5)):
        # create_polygon 은 점선을 지원하지 않으므로 변과 모서리를 나눠 그린다
        self.create_line(x0 + r, y0, x1 - r, y0, fill=color, dash=dash)
        self.create_line(x0 + r, y1, x1 - r, y1, fill=color, dash=dash)
        self.create_line(x0, y0 + r, x0, y1 - r, fill=color, dash=dash)
        self.create_line(x1, y0 + r, x1, y1 - r, fill=color, dash=dash)
        for (cx, cy, start) in ((x0 + r, y0 + r, 90), (x1 - r, y0 + r, 0),
                                (x1 - r, y1 - r, 270), (x0 + r, y1 - r, 180)):
            self.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=90,
                            style=tk.ARC, outline=color, dash=dash)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height() or int(self["height"])
        if w <= 2:
            return
        active = self.hover or self.dragging
        border = C.A2 if active else C.LINE
        if active:
            draw_round_rect(self, 2, 2, w - 2, h - 2, 14,
                            fill=mix(C.BG, C.A1, 0.10), outline="")
        self._dashed_round_rect(2, 2, w - 3, h - 3, 14, border)

        # 왼쪽 아이콘 (문서 + 갈라지는 화살표)
        cx, cy = 56, h / 2
        draw_round_rect(self, cx - 18, cy - 21, cx + 2, cy + 21, 4,
                        fill=mix(C.PANEL, C.A1, 0.35 if active else 0.18), outline=border)
        for dy in (-9, 0, 9):
            self.create_line(cx - 12, cy + dy, cx - 4, cy + dy,
                             fill=C.TEXT if active else C.MUTED, width=2)
        for dy in (-13, 13):
            self.create_line(cx + 8, cy, cx + 16, cy + dy, fill=mix(C.A1, C.A2, 0.5),
                             width=2, smooth=True)
            self.create_oval(cx + 14, cy + dy - 2, cx + 18, cy + dy + 2,
                             fill=C.A2, outline="")
        self.create_line(cx + 3, cy, cx + 9, cy, fill=mix(C.A1, C.A2, 0.5), width=2)

        self.create_text(96, cy - 11, text=self.title_text, anchor="w",
                         fill=C.TEXT if active else C.MUTED, font=self.fonts["h3"])
        self.create_text(96, cy + 12, text=self.hint_text, anchor="w",
                         fill=C.FAINT, font=self.fonts["small"])
