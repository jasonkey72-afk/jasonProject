"""PowerPoint → PDF 변환 화면."""

from __future__ import annotations

import tkinter as tk

from ..engines import ppt_pdf
from ..theme import C, ui_font
from ..widgets import LabeledSwitch, Segmented
from .converter import ConverterPage, hint_label


class PptToPdfPage(ConverterPage):
    key = "pptx_pdf"
    title = "PPTX → PDF"
    subtitle = "설치된 Microsoft PowerPoint 로 변환해 애니메이션을 제외한 슬라이드 디자인을 그대로 담습니다."
    icon = "◧"

    extensions = ppt_pdf.SUPPORTED_EXTS
    filetype_label = "PowerPoint 파일"
    queue_title = "변환할 PowerPoint 파일"
    queue_desc = "pptx, pptm, ppt, ppsx 를 지원합니다. 원본 파일은 읽기 전용으로만 열립니다."
    options_title = "변환 옵션"
    options_desc = "슬라이드로 낼지, 유인물이나 노트 형태로 낼지 선택합니다."
    options_icon = "⚙"
    run_text = "PDF 로 변환"
    done_message = "{ok}개 PowerPoint 파일을 PDF 로 변환했습니다."
    engine = staticmethod(ppt_pdf.convert)

    def build_options(self, parent, bg):
        self.output_type = tk.StringVar(value="slides")
        self.include_hidden = tk.BooleanVar(value=False)
        self.print_quality = tk.BooleanVar(value=True)

        tk.Label(parent, text="페이지 구성", bg=bg, fg=C["text_dim"],
                 font=ui_font(9)).pack(anchor="w", pady=(0, 8))
        Segmented(parent, ppt_pdf.OUTPUT_LABELS, self.output_type, bg=bg, min_seg=92).pack(anchor="w")
        hint_label(parent, "유인물 2/3/6 은 한 페이지에 슬라이드를 여러 장 넣어 인쇄용으로 만듭니다.",
                   bg).pack(anchor="w", pady=(8, 0))

        LabeledSwitch(parent, "숨겨진 슬라이드도 포함", self.include_hidden,
                      desc="발표 시 건너뛰도록 숨긴 슬라이드까지 PDF 에 넣습니다.",
                      bg=bg).pack(anchor="w", pady=(18, 0))
        LabeledSwitch(parent, "인쇄 품질로 저장 (권장)", self.print_quality,
                      desc="끄면 화면용 저해상도로 저장되어 용량이 작아집니다.",
                      bg=bg).pack(anchor="w", pady=(14, 0))

        self.env_hint = hint_label(parent, "", bg)
        self.env_hint.pack(anchor="w", pady=(18, 0))
        self.refresh_env()

    def refresh_env(self):
        env = getattr(self.app, "env", {})
        if env.get("powerpoint"):
            self.env_hint.configure(text="✔ Microsoft PowerPoint 확인됨", fg=C["success"])
        elif env.get("windows"):
            self.env_hint.configure(
                text="⚠ 이 PC 에서 Microsoft PowerPoint 를 찾지 못했습니다. 설치 후 사용해 주세요.",
                fg=C["warning"])
        else:
            self.env_hint.configure(
                text="⚠ 이 기능은 Microsoft PowerPoint 가 설치된 Windows PC 에서만 동작합니다.",
                fg=C["warning"])

    def collect_options(self) -> dict:
        return {
            "output_type": self.output_type.get(),
            "include_hidden": self.include_hidden.get(),
            "print_quality": self.print_quality.get(),
        }
