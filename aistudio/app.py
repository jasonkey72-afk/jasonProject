"""AI Studio 메인 윈도우.

좌측 내비게이션 + 우측 기능 화면 구조. 모든 기능(MP4→GIF, XLSX→PDF,
PPTX→PDF, 파일&폴더 이름 목록)을 이 하나의 창에서 실행한다.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk

from . import APP_NAME, APP_TAGLINE, __version__
from .engines import excel_pdf, ppt_pdf, video_gif
from .engines.common import is_windows
from .pages.excel_pdf_page import ExcelToPdfPage
from .pages.home_page import HomePage
from .pages.namelist_page import NameListPage
from .pages.ppt_pdf_page import PptToPdfPage
from .pages.video_gif_page import VideoToGifPage
from .theme import C, apply_theme, init_fonts, mix, ui_font
from .widgets import LogoOrb, rounded_gradient, rounded_solid

PAGE_CLASSES = [HomePage, VideoToGifPage, ExcelToPdfPage, PptToPdfPage, NameListPage]

NAV_LABELS = {
    "home": "홈",
    "mp4_gif": "MP4 → GIF",
    "xlsx_pdf": "XLSX → PDF",
    "pptx_pdf": "PPTX → PDF",
    "namelist": "이름 목록",
}


class NavItem(tk.Canvas):
    """사이드바 메뉴 항목."""

    HEIGHT = 46

    def __init__(self, master, icon, label, command, bg):
        super().__init__(master, height=self.HEIGHT, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._bg = bg
        self._icon = icon
        self._label = label
        self._command = command
        self._active = False
        self._hover = False
        self._cw = 200
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self._command())

    def _on_configure(self, event):
        self._cw = event.width
        self._draw()

    def _set_hover(self, hover):
        self._hover = hover
        self._draw()

    def set_active(self, active):
        self._active = active
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self.HEIGHT
        if w <= 2:
            return
        if self._active:
            rounded_solid(self, 8, 4, w - 8, h - 4, 12, mix(C["sidebar"], C["accent"], 0.20))
            rounded_gradient(self, 8, 12, 11, h - 12, 1, C["accent"], C["accent_2"])
            icon_color, text_color, weight = C["accent_2"], C["text"], "bold"
        elif self._hover:
            rounded_solid(self, 8, 4, w - 8, h - 4, 12, mix(C["sidebar"], "#FFFFFF", 0.05))
            icon_color, text_color, weight = C["text_dim"], C["text"], "normal"
        else:
            icon_color, text_color, weight = C["text_faint"], C["text_dim"], "normal"
        self.create_text(32, h / 2, text=self._icon, fill=icon_color, font=ui_font(11, "bold"))
        self.create_text(56, h / 2, text=self._label, anchor="w", fill=text_color,
                         font=ui_font(10, weight))


class AIStudioApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_TAGLINE}")
        self.geometry("1240x820")
        self.minsize(1060, 700)

        init_fonts(self)
        apply_theme(self)
        self.configure(bg=C["bg"])
        self._apply_native_chrome()

        self.env: dict = {"windows": is_windows(), "platform": sys.platform}
        self._env_queue: "queue.Queue" = queue.Queue()

        self.pages: dict[str, object] = {}
        self.nav_items: dict[str, NavItem] = {}
        self.current_page: str | None = None

        self._build_layout()
        self.show_page("home")
        self.detect_environment()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- 레이아웃
    def _build_layout(self):
        sidebar = tk.Frame(self, bg=C["sidebar"], width=224)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=C["sidebar"])
        brand.pack(fill="x", padx=18, pady=(24, 8))
        self.orb = LogoOrb(brand, size=40, bg=C["sidebar"])
        self.orb.pack(side="left")
        titles = tk.Frame(brand, bg=C["sidebar"])
        titles.pack(side="left", padx=(12, 0))
        tk.Label(titles, text=APP_NAME, bg=C["sidebar"], fg=C["text"],
                 font=ui_font(13, "bold")).pack(anchor="w")
        tk.Label(titles, text=APP_TAGLINE, bg=C["sidebar"], fg=C["text_faint"],
                 font=ui_font(8)).pack(anchor="w")

        divider = tk.Canvas(sidebar, height=1, bg=C["sidebar"], highlightthickness=0, bd=0)
        divider.pack(fill="x", padx=18, pady=(14, 12))
        divider.bind("<Configure>", lambda e: self._draw_divider(divider, e.width))

        tk.Label(sidebar, text="기능", bg=C["sidebar"], fg=C["text_faint"],
                 font=ui_font(8, "bold")).pack(anchor="w", padx=26, pady=(0, 6))

        self.nav_holder = tk.Frame(sidebar, bg=C["sidebar"])
        self.nav_holder.pack(fill="x")

        footer = tk.Frame(sidebar, bg=C["sidebar"])
        footer.pack(side="bottom", fill="x", padx=18, pady=18)
        self.env_summary = tk.Label(footer, text="환경 점검 중...", bg=C["sidebar"],
                                    fg=C["text_faint"], font=ui_font(8), justify="left")
        self.env_summary.pack(anchor="w")
        tk.Label(footer, text=f"v{__version__}", bg=C["sidebar"], fg=C["text_faint"],
                 font=ui_font(8)).pack(anchor="w", pady=(6, 0))

        # 본문 영역
        self.container = tk.Frame(self, bg=C["bg"])
        self.container.pack(side="left", fill="both", expand=True)

        for page_class in PAGE_CLASSES:
            page = page_class(self.container, self)
            self.pages[page_class.key] = page
            item = NavItem(self.nav_holder, page_class.icon,
                           NAV_LABELS.get(page_class.key, page_class.title),
                           command=lambda k=page_class.key: self.show_page(k),
                           bg=C["sidebar"])
            item.pack(fill="x", pady=1)
            self.nav_items[page_class.key] = item

    @staticmethod
    def _draw_divider(canvas, width):
        canvas.delete("all")
        rounded_gradient(canvas, 0, 0, width, 1, 0,
                         mix(C["sidebar"], C["accent"], 0.35), C["sidebar"])

    def _apply_native_chrome(self):
        """Windows 에서 제목 표시줄도 어둡게 만든다 (지원되지 않으면 조용히 넘어감)."""
        if not is_windows():
            return
        try:
            import ctypes

            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            pass

    # ------------------------------------------------------------ 페이지 전환
    def show_page(self, key):
        page = self.pages.get(key)
        if page is None:
            return
        if self.current_page == key:
            return
        for other in self.pages.values():
            other.pack_forget()
        page.pack(fill="both", expand=True)
        for nav_key, item in self.nav_items.items():
            item.set_active(nav_key == key)
        self.current_page = key
        page.on_show()

    # ------------------------------------------------------------ 환경 점검
    def detect_environment(self):
        self.env_summary.configure(text="환경 점검 중...")

        def worker():
            result = {
                "windows": is_windows(),
                "platform": f"{sys.platform}",
                "excel": excel_pdf.excel_available(),
                "powerpoint": ppt_pdf.powerpoint_available(),
                "ffmpeg": video_gif.find_ffmpeg(),
            }
            self._env_queue.put(result)

        threading.Thread(target=worker, daemon=True).start()
        self.after(120, self._poll_env)

    def _poll_env(self):
        try:
            result = self._env_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_env)
            return
        self.env = result
        ready = []
        if result.get("ffmpeg"):
            ready.append("GIF")
        if result.get("excel"):
            ready.append("Excel")
        if result.get("powerpoint"):
            ready.append("PPT")
        ready.append("이름목록")
        self.env_summary.configure(text="사용 가능: " + ", ".join(ready))
        for page in self.pages.values():
            try:
                page.refresh_env()
            except Exception:
                pass

    # ---------------------------------------------------------------- 종료
    def _on_close(self):
        running = [p for p in self.pages.values() if getattr(p, "runner", None) and p.runner.is_running]
        if running:
            from tkinter import messagebox

            if not messagebox.askokcancel("종료 확인", "진행 중인 작업이 있습니다. 정말 종료할까요?"):
                return
            for page in running:
                page.runner.cancel()
        try:
            self.orb.stop()
        except Exception:
            pass
        self.destroy()


def main():
    # 고해상도 화면에서 글자가 흐려지지 않도록 (Windows 전용)
    if is_windows():
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    app = AIStudioApp()
    app.mainloop()
