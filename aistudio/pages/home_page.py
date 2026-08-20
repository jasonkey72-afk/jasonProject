"""홈(대시보드) 화면."""

from __future__ import annotations

import sys
import tkinter as tk

from .. import APP_TAGLINE, __version__
from ..theme import C, mix, ui_font
from ..widgets import Button, Card, Chip, rounded_gradient, rounded_solid
from .base import BasePage

TOOL_CARDS = [
    ("mp4_gif", "▶", "MP4 → GIF",
     "동영상을 팔레트 최적화 방식으로 변환해\n선명하고 가벼운 GIF 를 만듭니다."),
    ("xlsx_pdf", "▦", "XLSX → PDF",
     "Excel 서식·표·한글을 그대로 유지한 채\n여러 파일을 한 번에 PDF 로 바꿉니다."),
    ("pptx_pdf", "◧", "PPTX → PDF",
     "슬라이드·유인물·노트 형태를 골라\n발표 자료를 PDF 로 내보냅니다."),
    ("namelist", "☰", "파일 & 폴더 이름 목록",
     "폴더 안의 이름을 전부 수집해\n엑셀(CSV)·텍스트·트리로 저장합니다."),
]


class ToolTile(tk.Frame):
    """홈 화면의 클릭 가능한 기능 카드."""

    def __init__(self, master, icon, title, desc, command):
        super().__init__(master, bg=C["surface"], highlightthickness=1,
                         highlightbackground=C["border"], cursor="hand2")
        self.command = command
        self._normal = C["surface"]
        self._hover = mix(C["surface"], C["accent"], 0.10)

        badge = tk.Canvas(self, width=44, height=44, bg=self._normal, highlightthickness=0, bd=0)
        badge.pack(anchor="w", padx=20, pady=(20, 0))
        rounded_gradient(badge, 0, 0, 44, 44, 13, C["accent"], C["accent_2"])
        badge.create_text(22, 22, text=icon, fill="#0A0D18", font=ui_font(15, "bold"))
        self.badge = badge

        self.title_label = tk.Label(self, text=title, bg=self._normal, fg=C["text"],
                                    font=ui_font(12, "bold"), anchor="w")
        self.title_label.pack(anchor="w", padx=20, pady=(14, 0))
        self.desc_label = tk.Label(self, text=desc, bg=self._normal, fg=C["text_dim"],
                                   font=ui_font(9), justify="left", anchor="w")
        self.desc_label.pack(anchor="w", padx=20, pady=(8, 0))

        self.go_label = tk.Label(self, text="열기  →", bg=self._normal, fg=C["accent_2"],
                                 font=ui_font(9, "bold"))
        self.go_label.pack(anchor="w", padx=20, pady=(14, 20))

        for widget in (self, badge, self.title_label, self.desc_label, self.go_label):
            widget.bind("<Button-1>", lambda e: self.command())
            widget.bind("<Enter>", lambda e: self._set_hover(True))
            widget.bind("<Leave>", lambda e: self._set_hover(False))

    def _set_hover(self, hover):
        color = self._hover if hover else self._normal
        self.configure(bg=color, highlightbackground=C["accent"] if hover else C["border"])
        self.badge.configure(bg=color)
        for label in (self.title_label, self.desc_label, self.go_label):
            label.configure(bg=color)


class HomePage(BasePage):
    key = "home"
    title = "홈"
    subtitle = ""
    icon = "⌂"

    def build(self):
        # 히어로 배너
        hero = tk.Canvas(self.content, height=132, bg=C["bg"], highlightthickness=0, bd=0)
        hero.pack(fill="x", pady=(0, 20))
        hero.bind("<Configure>", lambda e: self._draw_hero(hero, e.width, e.height))

        grid = tk.Frame(self.content, bg=C["bg"])
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="tool")
        grid.columnconfigure(1, weight=1, uniform="tool")
        for index, (key, icon, name, desc) in enumerate(TOOL_CARDS):
            tile = ToolTile(grid, icon, name, desc, command=lambda k=key: self.app.show_page(k))
            tile.grid(row=index // 2, column=index % 2, sticky="nsew",
                      padx=(0, 8) if index % 2 == 0 else (8, 0), pady=(0, 16))

        # 시스템 점검
        env_card = Card(self.content, title="실행 환경 점검",
                        desc="각 기능이 필요로 하는 프로그램이 이 PC 에 준비되어 있는지 확인합니다.", icon="⚑")
        env_card.pack(fill="x")
        bg = env_card.bg
        chips = tk.Frame(env_card.body, bg=bg)
        chips.pack(fill="x")
        self.chip_os = Chip(chips, "운영체제 확인 중", "neutral", bg=bg)
        self.chip_os.pack(side="left", padx=(0, 8))
        self.chip_excel = Chip(chips, "Excel 확인 중", "neutral", bg=bg)
        self.chip_excel.pack(side="left", padx=(0, 8))
        self.chip_ppt = Chip(chips, "PowerPoint 확인 중", "neutral", bg=bg)
        self.chip_ppt.pack(side="left", padx=(0, 8))
        self.chip_ffmpeg = Chip(chips, "ffmpeg 확인 중", "neutral", bg=bg)
        self.chip_ffmpeg.pack(side="left")

        self.env_detail = tk.Label(env_card.body, text="", bg=bg, fg=C["text_faint"],
                                   font=ui_font(8), justify="left")
        self.env_detail.pack(anchor="w", pady=(14, 0))

        Button(env_card.body, "다시 검사", command=self.app.detect_environment, kind="ghost",
               bg=bg, height=32, font_size=9).pack(anchor="w", pady=(16, 0))
        self.refresh_env()

    def _draw_hero(self, canvas, width, height):
        canvas.delete("all")
        if width <= 2:
            return
        rounded_gradient(canvas, 0, 0, width, height, 18,
                         mix(C["surface"], C["accent"], 0.22),
                         mix(C["surface"], C["accent_2"], 0.16))
        rounded_solid(canvas, 1, 1, width - 1, height - 1, 17, mix(C["surface"], C["accent"], 0.07))
        canvas.create_text(28, 34, anchor="w", text="업무 자동화, 한 화면에서",
                           fill=C["text"], font=ui_font(18, "bold"))
        canvas.create_text(28, 68, anchor="w",
                           text="동영상·엑셀·파워포인트 변환과 파일 목록 정리를 하나의 도구로 처리하세요.",
                           fill=C["text_dim"], font=ui_font(10))
        canvas.create_text(28, 98, anchor="w",
                           text=f"{APP_TAGLINE} · v{__version__}",
                           fill=C["accent_2"], font=ui_font(8, "bold"))
        # 우측 장식 (동심원)
        for i in range(5):
            r = 26 + i * 15
            canvas.create_oval(width - 70 - r, height / 2 - r, width - 70 + r, height / 2 + r,
                               outline=mix(C["surface"], C["accent_2"], 0.30 - i * 0.05), width=1)

    def refresh_env(self):
        env = getattr(self.app, "env", {})
        if not env:
            return
        is_windows = env.get("windows")
        self.chip_os.set(f"{env.get('platform', sys.platform)}", "ok" if is_windows else "warn")

        if env.get("excel"):
            self.chip_excel.set("Excel 사용 가능", "ok")
        else:
            self.chip_excel.set("Excel 없음", "warn")
        if env.get("powerpoint"):
            self.chip_ppt.set("PowerPoint 사용 가능", "ok")
        else:
            self.chip_ppt.set("PowerPoint 없음", "warn")
        if env.get("ffmpeg"):
            self.chip_ffmpeg.set("ffmpeg 사용 가능", "ok")
        else:
            self.chip_ffmpeg.set("ffmpeg 없음", "warn")

        details = []
        if not is_windows:
            details.append("· Excel / PowerPoint 변환은 Microsoft Office 가 설치된 Windows PC 에서만 동작합니다.")
        else:
            if not env.get("excel"):
                details.append("· Excel → PDF 를 쓰려면 Microsoft Excel 설치가 필요합니다.")
            if not env.get("powerpoint"):
                details.append("· PPT → PDF 를 쓰려면 Microsoft PowerPoint 설치가 필요합니다.")
        if env.get("ffmpeg"):
            details.append(f"· ffmpeg 경로: {env['ffmpeg']}")
        else:
            details.append("· MP4 → GIF 를 쓰려면 `pip install imageio-ffmpeg` 또는 ffmpeg.exe 배치가 필요합니다.")
        self.env_detail.configure(text="\n".join(details))
