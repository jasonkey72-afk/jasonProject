"""PowerPoint(pptx/ppt/pptm) → PDF 변환 엔진.

Microsoft PowerPoint 를 COM 자동화로 제어한다.
원본은 읽기 전용으로 열고 저장 없이 닫으므로 변경되지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from ..runner import JobCancelled
from .common import com_progid_available, human_size, normalize_existing, target_path

SUPPORTED_EXTS = (".pptx", ".ppt", ".pptm", ".ppsx", ".pps")
PROGID = "PowerPoint.Application"

PP_FIXED_FORMAT_TYPE_PDF = 2
PP_FIXED_FORMAT_INTENT_PRINT = 2
PP_FIXED_FORMAT_INTENT_SCREEN = 1
PP_SAVE_AS_PDF = 32

# ExportAsFixedFormat 의 OutputType 값
OUTPUT_TYPES = {
    "slides": 1,       # 슬라이드 (기본)
    "notes": 5,        # 슬라이드 노트
    "handout2": 2,     # 유인물 2장/페이지
    "handout3": 3,     # 유인물 3장/페이지
    "handout6": 4,     # 유인물 6장/페이지
}

OUTPUT_LABELS = [
    ("slides", "슬라이드"),
    ("handout2", "유인물 2"),
    ("handout3", "유인물 3"),
    ("handout6", "유인물 6"),
    ("notes", "노트"),
]

MSO_FALSE = 0
MSO_TRUE = -1


def powerpoint_available() -> bool:
    return com_progid_available(PROGID)


def _export_one(ppt_app, src: Path, dst: Path, output_type: str, include_hidden: bool,
                print_quality: bool):
    presentation = None
    try:
        presentation = ppt_app.Presentations.Open(
            str(src), ReadOnly=MSO_TRUE, Untitled=MSO_FALSE, WithWindow=MSO_FALSE
        )
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            presentation.ExportAsFixedFormat(
                str(dst),
                PP_FIXED_FORMAT_TYPE_PDF,
                PP_FIXED_FORMAT_INTENT_PRINT if print_quality else PP_FIXED_FORMAT_INTENT_SCREEN,
                MSO_FALSE,                                   # FrameSlides
                1,                                           # HandoutOrder: 가로 우선
                OUTPUT_TYPES.get(output_type, 1),            # OutputType
                MSO_TRUE if include_hidden else MSO_FALSE,   # PrintHiddenSlides
            )
        except Exception:
            # 일부 버전에서는 ExportAsFixedFormat 인자 조합을 거부하므로 SaveAs 로 대체
            presentation.SaveAs(str(dst), PP_SAVE_AS_PDF)
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                pass


def convert(params: dict, em) -> dict:
    """params: files, out_mode, out_dir, output_type, include_hidden, print_quality, overwrite"""
    files = normalize_existing(params.get("files", []))
    if not files:
        return {"ok": 0, "fail": 0, "note": "변환할 파일이 없습니다."}

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise RuntimeError(
            "pywin32 패키지가 필요합니다. (pip install pywin32)\n"
            "Windows + Microsoft PowerPoint 가 설치된 PC 에서만 사용할 수 있습니다."
        )

    pythoncom.CoInitialize()
    ppt_app = None
    ok = fail = 0
    outputs: list[str] = []
    try:
        em.status("Microsoft PowerPoint 를 준비하는 중...")
        try:
            ppt_app = win32com.client.DispatchEx(PROGID)
        except Exception:
            raise RuntimeError(
                "Microsoft PowerPoint 를 찾을 수 없습니다. 이 PC 에 PowerPoint 가 설치되어 있는지 확인해 주세요."
            )
        try:
            # PowerPoint 는 창을 완전히 숨기면 오류가 나는 버전이 있어 실패해도 무시한다
            ppt_app.DisplayAlerts = 1
        except Exception:
            pass

        total = len(files)
        em.log(f"총 {total}개 PowerPoint 파일을 PDF 로 변환합니다.", "head")

        for index, src in enumerate(files, start=1):
            em.raise_if_cancelled()
            em.status(f"[{index}/{total}] {src.name}")
            dst = target_path(src, params.get("out_mode", "same"), params.get("out_dir", ""),
                              ".pdf", params.get("overwrite", True))
            try:
                _export_one(
                    ppt_app, src, dst,
                    params.get("output_type", "slides"),
                    params.get("include_hidden", False),
                    params.get("print_quality", True),
                )
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
            if ppt_app is not None:
                ppt_app.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()
