"""동영상(MP4) → GIF 변환 화면."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..engines import video_gif
from ..theme import C, ui_font
from ..widgets import Button, FormRow, LabeledSwitch
from .converter import ConverterPage, hint_label

PRESETS = {
    "share": {"label": "메신저 공유", "fps": 10, "width": 400, "colors": 128, "hq": True},
    "balanced": {"label": "표준", "fps": 12, "width": 480, "colors": 256, "hq": True},
    "quality": {"label": "고화질", "fps": 20, "width": 720, "colors": 256, "hq": True},
}


class VideoToGifPage(ConverterPage):
    key = "mp4_gif"
    title = "MP4 → GIF"
    subtitle = "동영상을 팔레트 최적화 방식으로 변환해 화질 손상 없이 가벼운 GIF 를 만듭니다."
    icon = "▶"

    extensions = video_gif.SUPPORTED_EXTS
    filetype_label = "동영상 파일"
    queue_title = "변환할 동영상"
    queue_desc = "MP4, MOV, AVI, MKV, WEBM 등 대부분의 동영상 형식을 지원합니다."
    options_title = "GIF 옵션"
    options_desc = "프레임 수와 가로 폭이 용량을 좌우합니다. 잘 모르겠으면 프리셋을 눌러 주세요."
    options_icon = "◈"
    run_text = "GIF 로 변환"
    done_message = "{ok}개 동영상을 GIF 로 변환했습니다."
    engine = staticmethod(video_gif.convert)

    def build_options(self, parent, bg):
        # 프리셋
        preset_row = tk.Frame(parent, bg=bg)
        preset_row.pack(fill="x")
        tk.Label(preset_row, text="빠른 설정", bg=bg, fg=C["text_dim"],
                 font=ui_font(9)).pack(side="left", padx=(0, 12))
        for key, preset in PRESETS.items():
            Button(preset_row, preset["label"], kind="subtle", bg=bg, height=30, font_size=9,
                   command=lambda k=key: self.apply_preset(k)).pack(side="left", padx=(0, 8))

        ttk.Separator(parent, style="AI.TSeparator").pack(fill="x", pady=16)

        self.fps = tk.IntVar(value=12)
        self.width = tk.IntVar(value=480)
        self.colors = tk.IntVar(value=256)
        self.dither = tk.StringVar(value=video_gif.DITHER_OPTIONS[0][1])
        self.high_quality = tk.BooleanVar(value=True)
        self.loop_forever = tk.BooleanVar(value=True)
        self.start_time = tk.StringVar(value="")
        self.end_time = tk.StringVar(value="")

        grid = tk.Frame(parent, bg=bg)
        grid.pack(fill="x")

        row = FormRow(grid, "초당 프레임", bg=bg, hint="숫자가 클수록 부드럽지만 용량이 커집니다")
        row.pack(fill="x", pady=5)
        ttk.Spinbox(row.field, from_=1, to=30, textvariable=self.fps, width=8,
                    style="AI.TSpinbox", font=ui_font(9)).pack(side="left")

        row = FormRow(grid, "가로 폭(px)", bg=bg, hint="0 을 입력하면 원본 크기 그대로")
        row.pack(fill="x", pady=5)
        ttk.Spinbox(row.field, from_=0, to=1920, increment=20, textvariable=self.width, width=8,
                    style="AI.TSpinbox", font=ui_font(9)).pack(side="left")

        row = FormRow(grid, "색상 수", bg=bg, hint="최대 256색. 줄이면 용량이 작아집니다")
        row.pack(fill="x", pady=5)
        ttk.Spinbox(row.field, from_=2, to=256, increment=16, textvariable=self.colors, width=8,
                    style="AI.TSpinbox", font=ui_font(9)).pack(side="left")

        row = FormRow(grid, "디더링", bg=bg, hint="색 경계를 처리하는 방식")
        row.pack(fill="x", pady=5)
        ttk.Combobox(row.field, textvariable=self.dither, state="readonly", width=18,
                     style="AI.TCombobox", font=ui_font(9),
                     values=[label for _v, label in video_gif.DITHER_OPTIONS]).pack(side="left")

        row = FormRow(grid, "구간 자르기", bg=bg, hint="예: 0:05 ~ 0:12 (비우면 전체)")
        row.pack(fill="x", pady=5)
        ttk.Entry(row.field, textvariable=self.start_time, width=10,
                  style="AI.TEntry", font=ui_font(9)).pack(side="left")
        tk.Label(row.field, text="~", bg=bg, fg=C["text_faint"], font=ui_font(9)).pack(side="left", padx=8)
        ttk.Entry(row.field, textvariable=self.end_time, width=10,
                  style="AI.TEntry", font=ui_font(9)).pack(side="left")

        switches = tk.Frame(parent, bg=bg)
        switches.pack(fill="x", pady=(16, 0))
        LabeledSwitch(switches, "고품질 팔레트 사용 (권장)", self.high_quality,
                      desc="영상에 맞는 색 팔레트를 따로 계산합니다. 끄면 더 빠르지만 색이 거칠어집니다.",
                      bg=bg).pack(anchor="w")
        LabeledSwitch(switches, "무한 반복 재생", self.loop_forever,
                      desc="끄면 GIF 가 한 번만 재생되고 멈춥니다.", bg=bg).pack(anchor="w", pady=(12, 0))

        self.ffmpeg_hint = hint_label(parent, "", bg)
        self.ffmpeg_hint.pack(anchor="w", pady=(16, 0))
        self.refresh_env()

    def apply_preset(self, key):
        preset = PRESETS[key]
        self.fps.set(preset["fps"])
        self.width.set(preset["width"])
        self.colors.set(preset["colors"])
        self.high_quality.set(preset["hq"])
        self.panel.log.write(f"'{preset['label']}' 설정을 적용했습니다.", "info")

    def refresh_env(self):
        path = getattr(self.app, "env", {}).get("ffmpeg")
        if path:
            self.ffmpeg_hint.configure(text=f"✔ ffmpeg 엔진 확인됨 · {path}", fg=C["success"])
        else:
            self.ffmpeg_hint.configure(
                text="⚠ ffmpeg 를 찾지 못했습니다. `pip install imageio-ffmpeg` 를 실행하거나 "
                     "ffmpeg.exe 를 프로그램과 같은 폴더에 두세요.",
                fg=C["warning"],
            )

    def validate(self) -> bool:
        try:
            video_gif.parse_timecode(self.start_time.get())
            video_gif.parse_timecode(self.end_time.get())
        except ValueError as exc:
            messagebox.showwarning("알림", str(exc))
            return False
        return True

    def collect_options(self) -> dict:
        dither_value = next(
            (value for value, label in video_gif.DITHER_OPTIONS if label == self.dither.get()),
            "sierra2_4a",
        )
        return {
            "fps": self.fps.get(),
            "width": self.width.get(),
            "colors": self.colors.get(),
            "dither": dither_value,
            "high_quality": self.high_quality.get(),
            "loop_forever": self.loop_forever.get(),
            "start": self.start_time.get(),
            "end": self.end_time.get(),
            "ffmpeg_path": getattr(self.app, "env", {}).get("ffmpeg"),
        }
