"""엔진 공통 유틸리티."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def app_dir() -> Path:
    """실행 파일(exe) 또는 스크립트가 위치한 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def human_size(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def unique_path(path: Path) -> Path:
    """같은 이름의 파일이 있으면 `이름 (2).확장자` 형태로 비켜간다."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    index = 2
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def target_path(src: Path, out_mode: str, out_dir: str, new_ext: str, overwrite: bool) -> Path:
    """원본 경로와 저장 옵션으로 결과 파일 경로를 만든다."""
    folder = src.parent if out_mode == "same" else Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / (src.stem + new_ext)
    return dst if overwrite else unique_path(dst)


def com_progid_available(progid: str) -> bool:
    """레지스트리만 확인해서 Office 앱 설치 여부를 빠르게 판단한다."""
    if not is_windows():
        return False
    try:
        import winreg
    except ImportError:
        return False
    for key in (progid, f"{progid}\\CurVer"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key):
                return True
        except OSError:
            continue
    return False


def normalize_existing(paths) -> list[Path]:
    """실제로 존재하는 파일만 남긴다."""
    result = []
    for item in paths:
        p = Path(item)
        if p.is_file():
            result.append(p)
    return result


def open_in_explorer(path: str | os.PathLike):
    """결과 폴더를 탐색기(또는 각 OS 파일 관리자)로 연다."""
    target = Path(path)
    if not target.exists():
        return False
    try:
        if is_windows():
            os.startfile(str(target))  # noqa: S606 - Windows 전용 API
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(target)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(target)])
        return True
    except Exception:
        return False
