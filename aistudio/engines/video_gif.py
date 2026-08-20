"""MP4(동영상) → GIF 변환 엔진.

ffmpeg 를 사용해 2-pass 팔레트 방식(palettegen + paletteuse)으로 변환하므로
일반적인 GIF 변환기보다 색 번짐이 적고 용량 대비 화질이 좋다.

ffmpeg 실행 파일은 다음 순서로 찾는다.
  1) 사용자가 지정한 경로
  2) exe/스크립트와 같은 폴더(또는 ffmpeg 하위 폴더)의 ffmpeg 실행 파일
  3) imageio-ffmpeg 패키지에 동봉된 ffmpeg
  4) 시스템 PATH 의 ffmpeg
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from ..runner import JobCancelled
from .common import app_dir, human_size, is_windows, normalize_existing, target_path

SUPPORTED_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".flv")

DITHER_OPTIONS = [
    ("sierra2_4a", "부드럽게 (기본)"),
    ("bayer", "선명하게 (용량 작음)"),
    ("none", "없음"),
]

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_CREATE_NO_WINDOW = 0x08000000 if is_windows() else 0


def _popen_kwargs():
    kwargs = {}
    if is_windows():
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


def find_ffmpeg(custom_path: str | None = None) -> str | None:
    """사용 가능한 ffmpeg 실행 파일 경로를 반환한다. 없으면 None."""
    if custom_path:
        candidate = Path(custom_path)
        if candidate.is_file():
            return str(candidate)

    exe_name = "ffmpeg.exe" if is_windows() else "ffmpeg"
    base = app_dir()
    for candidate in (base / exe_name, base / "ffmpeg" / exe_name, base / "bin" / exe_name):
        if candidate.is_file():
            return str(candidate)

    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).is_file():
            return path
    except Exception:
        pass

    found = shutil.which("ffmpeg")
    return found


def probe_duration(ffmpeg: str, src: Path) -> float | None:
    """입력 파일의 전체 길이(초). 진행률 계산에 사용한다."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(src)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30, **_popen_kwargs()
        )
    except Exception:
        return None
    match = _DURATION_RE.search(proc.stderr.decode("utf-8", "ignore"))
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_timecode(value: str) -> float | None:
    """'12', '1:05', '00:01:05.5' 형태를 초 단위로 바꾼다."""
    value = (value or "").strip()
    if not value:
        return None
    parts = value.split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"시간 형식이 올바르지 않습니다: {value}")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def build_filter(fps: int, width: int, colors: int, dither: str, high_quality: bool) -> str:
    """ffmpeg -filter_complex 문자열을 만든다."""
    chain = [f"fps={max(1, fps)}"]
    if width and width > 0:
        chain.append(f"scale={int(width)}:-1:flags=lanczos")
    base = ",".join(chain)
    if not high_quality:
        return base
    colors = max(2, min(256, int(colors)))
    dither_arg = f"dither={dither}" if dither != "none" else "dither=none"
    return (
        f"{base},split[pg][use];"
        f"[pg]palettegen=max_colors={colors}:stats_mode=diff[pal];"
        f"[use][pal]paletteuse={dither_arg}:diff_mode=rectangle"
    )


def _build_command(ffmpeg: str, src: Path, dst: Path, params: dict, start: float | None,
                   end: float | None) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end is not None:
        # -ss 는 입력 옵션, 길이는 출력 옵션(-t)으로 지정해야 해석이 명확하다
        cmd += ["-t", f"{max(end - (start or 0.0), 0.05):.3f}"]
    filter_str = build_filter(
        int(params.get("fps", 12)),
        int(params.get("width", 480)),
        int(params.get("colors", 256)),
        params.get("dither", "sierra2_4a"),
        bool(params.get("high_quality", True)),
    )
    if params.get("high_quality", True):
        cmd += ["-filter_complex", filter_str]
    else:
        cmd += ["-vf", filter_str]
    cmd += ["-loop", "0" if params.get("loop_forever", True) else "-1"]
    cmd += ["-progress", "pipe:1", "-nostats", str(dst)]
    return cmd


def _read_progress(stream, state: dict):
    """ffmpeg 의 -progress 출력을 읽어 현재 처리 위치(초)를 기록한다."""
    try:
        for line in stream:
            if line.startswith("out_time_us="):
                try:
                    state["seconds"] = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    pass
    except Exception:
        pass


def _run_with_progress(cmd: list[str], em, duration: float | None, base_fraction: float,
                       span: float, label: str) -> tuple[int, str]:
    """ffmpeg 를 실행하며 진행률을 보고한다. (종료코드, 오류메시지)

    진행 출력은 별도 스레드에서 읽는다. 팔레트 계산 구간처럼 ffmpeg 가 한동안
    아무 것도 출력하지 않을 때도 중지 버튼이 즉시 먹히도록 하기 위해서다.
    """
    cancelled = False
    pulsing = False
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="ignore") as err_file:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=err_file, universal_newlines=True,
            bufsize=1, **_popen_kwargs()
        )
        state = {"seconds": 0.0}
        reader = threading.Thread(target=_read_progress, args=(proc.stdout, state), daemon=True)
        reader.start()

        while proc.poll() is None:
            if em.cancelled:
                cancelled = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                break
            seconds = state["seconds"]
            if duration and seconds > 0:
                if pulsing:
                    em.pulse(False)
                    pulsing = False
                ratio = max(0.0, min(1.0, seconds / duration))
                em.progress(base_fraction + ratio * span, 1.0)
                em.status(f"{label}  {int(ratio * 100)}%")
            elif not pulsing:
                # 아직 출력이 없는 구간(색상 팔레트 분석 등)
                em.pulse(True)
                em.status(f"{label}  분석 중...")
                pulsing = True
            time.sleep(0.2)

        if pulsing:
            em.pulse(False)
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        reader.join(timeout=1)
        code = proc.wait()
        err_file.seek(0)
        message = err_file.read().strip()

    if cancelled:
        raise JobCancelled()
    return code, message


def convert(params: dict, em) -> dict:
    """params: files, out_mode, out_dir, fps, width, colors, dither, loop_forever,
    high_quality, start, end, overwrite, ffmpeg_path"""
    files = normalize_existing(params.get("files", []))
    if not files:
        return {"ok": 0, "fail": 0, "note": "변환할 파일이 없습니다."}

    start = parse_timecode(params.get("start", ""))
    end = parse_timecode(params.get("end", ""))
    if start is not None and end is not None and end <= start:
        raise ValueError("끝 시간은 시작 시간보다 뒤여야 합니다.")

    ffmpeg = find_ffmpeg(params.get("ffmpeg_path"))
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg 를 찾을 수 없습니다.\n"
            "· pip install imageio-ffmpeg 로 설치하거나\n"
            "· ffmpeg.exe 를 프로그램과 같은 폴더에 두거나\n"
            "· 설정에서 ffmpeg 경로를 직접 지정해 주세요."
        )

    em.log(f"ffmpeg: {ffmpeg}", "info")
    total = len(files)
    em.log(f"총 {total}개 동영상을 GIF 로 변환합니다.", "head")

    ok = fail = 0
    outputs: list[str] = []
    for index, src in enumerate(files, start=1):
        em.raise_if_cancelled()
        label = f"[{index}/{total}] {src.name}"
        em.status(label)
        dst = target_path(src, params.get("out_mode", "same"), params.get("out_dir", ""),
                          ".gif", params.get("overwrite", True))
        try:
            duration = probe_duration(ffmpeg, src)
            if duration:
                clip_start = start or 0.0
                clip_end = min(end, duration) if end else duration
                duration = max(clip_end - clip_start, 0.1)
            base = (index - 1) / total
            span = 1 / total
            code, message = _run_with_progress(
                _build_command(ffmpeg, src, dst, params, start, end),
                em, duration, base, span, label,
            )
            if code != 0:
                raise RuntimeError(message.splitlines()[-1] if message else f"ffmpeg 오류 (코드 {code})")
            if not dst.exists() or dst.stat().st_size == 0:
                raise RuntimeError("GIF 파일이 만들어지지 않았습니다.")
            ok += 1
            outputs.append(str(dst))
            em.log(f"[성공] {src.name} → {dst.name}  ({human_size(dst.stat().st_size)})", "ok")
        except JobCancelled:
            # 중지된 시점의 GIF 는 미완성이므로 남기지 않는다
            try:
                if dst.exists():
                    os.remove(dst)
            except OSError:
                pass
            raise
        except Exception as exc:  # noqa: BLE001
            fail += 1
            em.log(f"[실패] {src.name} : {exc}", "error")
        em.progress(index, total)

    return {"ok": ok, "fail": fail, "outputs": outputs,
            "out_dir": str(Path(outputs[-1]).parent) if outputs else ""}
