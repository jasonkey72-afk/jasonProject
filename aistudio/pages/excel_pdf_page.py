"""Excel → PDF 변환 화면."""

from __future__ import annotations

import tkinter as tk

from ..engines import excel_pdf
from ..theme import C, ui_font
from ..widgets import LabeledSwitch
from .converter import ConverterPage, hint_label


class ExcelToPdfPage(ConverterPage):
    key = "xlsx_pdf"
    title = "XLSX → PDF"
    subtitle = "설치된 Microsoft Excel 로 '인쇄하듯' 변환하므로 표·서식·한글이 그대로 유지됩니다."
    icon = "▦"

    extensions = excel_pdf.SUPPORTED_EXTS
    filetype_label = "Excel 파일"
    queue_title = "변환할 Excel 파일"
    queue_desc = "xlsx, xlsm, xls, xlsb, csv 를 지원합니다. 원본 파일은 읽기 전용으로만 열립니다."
    options_title = "변환 옵션"
    options_desc = "인쇄 설정을 조정해 표가 잘리지 않게 만듭니다."
    options_icon = "⚙"
    run_text = "PDF 로 변환"
    done_message = "{ok}개 Excel 파일을 PDF 로 변환했습니다."
    engine = staticmethod(excel_pdf.convert)

    def build_options(self, parent, bg):
        self.fit_to_width = tk.BooleanVar(value=True)
        self.quality_standard = tk.BooleanVar(value=True)

        LabeledSwitch(parent, "한 페이지 폭에 맞추기 (권장)", self.fit_to_width,
                      desc="열이 잘리지 않도록 시트를 자동으로 축소해 인쇄합니다.", bg=bg).pack(anchor="w")
        LabeledSwitch(parent, "표준 화질로 저장", self.quality_standard,
                      desc="끄면 최소 화질로 저장되어 용량이 줄어듭니다.", bg=bg).pack(anchor="w", pady=(14, 0))

        tk.Label(parent, text="원본 보호", bg=bg, fg=C["accent_2"],
                 font=ui_font(9, "bold")).pack(anchor="w", pady=(18, 4))
        hint_label(parent,
                   "파일을 읽기 전용으로 열고 저장하지 않은 채 닫으므로 원본 Excel 파일은 절대 변경되지 않습니다.",
                   bg).pack(anchor="w")

        self.env_hint = hint_label(parent, "", bg)
        self.env_hint.pack(anchor="w", pady=(14, 0))
        self.refresh_env()

    def refresh_env(self):
        env = getattr(self.app, "env", {})
        if env.get("excel"):
            self.env_hint.configure(text="✔ Microsoft Excel 확인됨", fg=C["success"])
        elif env.get("windows"):
            self.env_hint.configure(
                text="⚠ 이 PC 에서 Microsoft Excel 을 찾지 못했습니다. Excel 설치 후 사용해 주세요.",
                fg=C["warning"])
        else:
            self.env_hint.configure(
                text="⚠ 이 기능은 Microsoft Excel 이 설치된 Windows PC 에서만 동작합니다.",
                fg=C["warning"])

    def collect_options(self) -> dict:
        return {
            "fit_to_width": self.fit_to_width.get(),
            "quality_standard": self.quality_standard.get(),
        }
