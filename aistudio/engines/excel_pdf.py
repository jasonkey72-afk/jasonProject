"""Excel(xlsx/xlsm/xls) → PDF 변환 엔진.

Microsoft Excel 을 COM 자동화로 제어해 "인쇄하듯" PDF 를 만든다.
원본 파일은 읽기 전용으로 열고 저장하지 않으므로 절대 변경되지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from ..runner import JobCancelled
from .common import com_progid_available, human_size, normalize_existing, target_path

SUPPORTED_EXTS = (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv")
PROGID = "Excel.Application"

XL_TYPE_PDF = 0
XL_QUALITY_STANDARD = 0
XL_QUALITY_MINIMUM = 1


def excel_available() -> bool:
    return com_progid_available(PROGID)


def _export_one(excel_app, src: Path, dst: Path, fit_to_width: bool, quality_standard: bool):
    workbook = None
    try:
        workbook = excel_app.Workbooks.Open(
            str(src),
            UpdateLinks=0,
            ReadOnly=True,
            IgnoreReadOnlyRecommended=True,
            Notify=False,
        )
        if fit_to_width:
            for sheet in workbook.Worksheets:
                try:
                    sheet.PageSetup.Zoom = False
                    sheet.PageSetup.FitToPagesWide = 1
                    sheet.PageSetup.FitToPagesTall = False
                except Exception:
                    # 차트 시트 등 PageSetup 이 없는 시트는 건너뛴다
                    pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        workbook.ExportAsFixedFormat(
            Type=XL_TYPE_PDF,
            Filename=str(dst),
            Quality=XL_QUALITY_STANDARD if quality_standard else XL_QUALITY_MINIMUM,
            IncludeDocProperties=True,
            IgnorePrintAreas=False,
            OpenAfterPublish=False,
        )
    finally:
        if workbook is not None:
            # SaveChanges=False : 원본은 절대 저장하지 않는다
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                pass


def convert(params: dict, em) -> dict:
    """params: files, out_mode, out_dir, fit_to_width, quality_standard, overwrite"""
    files = normalize_existing(params.get("files", []))
    if not files:
        return {"ok": 0, "fail": 0, "note": "변환할 파일이 없습니다."}

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise RuntimeError(
            "pywin32 패키지가 필요합니다. (pip install pywin32)\n"
            "Windows + Microsoft Excel 이 설치된 PC 에서만 사용할 수 있습니다."
        )

    pythoncom.CoInitialize()
    excel_app = None
    ok = fail = 0
    outputs: list[str] = []
    try:
        em.status("Microsoft Excel 을 준비하는 중...")
        try:
            excel_app = win32com.client.DispatchEx(PROGID)
        except Exception:
            raise RuntimeError(
                "Microsoft Excel 을 찾을 수 없습니다. 이 PC 에 Excel 이 설치되어 있는지 확인해 주세요."
            )
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
        excel_app.ScreenUpdating = False

        total = len(files)
        em.log(f"총 {total}개 Excel 파일을 PDF 로 변환합니다.", "head")

        for index, src in enumerate(files, start=1):
            em.raise_if_cancelled()
            em.status(f"[{index}/{total}] {src.name}")
            dst = target_path(src, params.get("out_mode", "same"), params.get("out_dir", ""),
                              ".pdf", params.get("overwrite", True))
            try:
                _export_one(excel_app, src, dst,
                            params.get("fit_to_width", True),
                            params.get("quality_standard", True))
                ok += 1
                outputs.append(str(dst))
                size = human_size(dst.stat().st_size) if dst.exists() else "-"
                em.log(f"[성공] {src.name} → {dst.name}  ({size})", "ok")
            except Exception as exc:  # noqa: BLE001
                fail += 1
                em.log(f"[실패] {src.name} : {exc}", "error")
            em.progress(index, total)

        return {"ok": ok, "fail": fail, "outputs": outputs,
                "out_dir": str(Path(outputs[-1]).parent) if outputs else ""}
    except JobCancelled:
        raise
    finally:
        try:
            if excel_app is not None:
                excel_app.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()
