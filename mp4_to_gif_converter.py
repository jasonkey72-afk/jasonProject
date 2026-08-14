"""
MP4 to GIF 변환기
==================
용량이 큰 동영상(MP4/AVI/MOV/MKV 등)을 "움직이는 GIF"로 변환합니다.

- ffmpeg의 2-pass 팔레트 방식(palettegen/paletteuse)을 사용하여 같은 용량에서
  가장 깨끗한 화질의 GIF를 만듭니다.
- 원본 동영상 파일은 읽기만 하므로 절대 변경되지 않습니다.
- 여러 파일을 한 번에 선택해 일괄 변환할 수 있습니다.
- "목표 용량"을 지정하면 그 용량 이하가 될 때까지 해상도/프레임수를 자동으로
  낮춰가며 다시 변환합니다.

ffmpeg 실행 파일은 imageio-ffmpeg 패키지에 포함된 것을 사용하며,
없을 경우 PC에 설치된 ffmpeg(PATH)를 찾아 사용합니다.
"""

import os
import re
import sys
import queue
import shutil
import threading
import subprocess
import tempfile
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

SUPPORTED_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v", ".webm", ".mpg", ".mpeg", ".flv", ".ts")

# 품질 프리셋: 표시 이름 -> (팔레트 색상 수, 디더링 방식)
QUALITY_PRESETS = {
    "높음 (색상 256, 가장 깨끗함)": (256, "sierra2_4a"),
    "보통 (색상 128, 균형)": (128, "sierra2_4a"),
    "작게 (색상 64, 용량 우선)": (64, "bayer:bayer_scale=3"),
}
DEFAULT_QUALITY = "보통 (색상 128, 균형)"

# 목표 용량을 초과했을 때 순서대로 시도할 (가로폭 배율, FPS 배율)
SHRINK_STEPS = [
    (1.00, 1.00),
    (0.80, 1.00),
    (0.80, 0.75),
    (0.65, 0.75),
    (0.50, 0.60),
    (0.40, 0.50),
    (0.30, 0.40),
]

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class ConversionCancelled(Exception):
    pass


# ---------------------------------------------------------------- ffmpeg 준비


def find_ffmpeg():
    """사용 가능한 ffmpeg 실행 파일 경로를 반환한다. 없으면 None."""
    # 1) imageio-ffmpeg 에 동봉된 ffmpeg (exe로 배포할 때 함께 포함됨)
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    # 2) PC에 설치되어 PATH에 등록된 ffmpeg
    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    # 3) exe와 같은 폴더에 넣어둔 ffmpeg
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = base / name
        if candidate.exists():
            return str(candidate)
    return None


def _no_window_kwargs():
    """Windows에서 검은 콘솔 창이 깜빡이지 않도록 하는 subprocess 옵션."""
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def probe_duration(ffmpeg, src_path):
    """동영상 전체 길이(초)를 구한다. 알 수 없으면 None."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(src_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            **_no_window_kwargs(),
        )
    except Exception:
        return None
    m = DURATION_RE.search(proc.stderr or "")
    if not m:
        return None
    h, mnt, sec = m.group(1), m.group(2), m.group(3)
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def run_ffmpeg(ffmpeg, args, total_seconds, cancel_event, on_progress):
    """ffmpeg를 실행하며 진행률(0.0~1.0)을 콜백으로 알려준다."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y"] + args + ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        **_no_window_kwargs(),
    )

    try:
        for line in proc.stdout:
            if cancel_event.is_set():
                proc.terminate()
                raise ConversionCancelled()
            line = line.strip()
            if line.startswith("out_time_us=") and total_seconds:
                value = line.split("=", 1)[1]
                if value.isdigit():
                    on_progress(min(1.0, (int(value) / 1_000_000) / total_seconds))
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        stderr_text = ""
        try:
            stderr_text = proc.stderr.read() or ""
            proc.stderr.close()
        except Exception:
            pass
        proc.wait()

    if cancel_event.is_set():
        raise ConversionCancelled()
    if proc.returncode != 0:
        tail = "\n".join([ln for ln in stderr_text.splitlines() if ln.strip()][-4:])
        raise RuntimeError(tail or f"ffmpeg 오류 (코드 {proc.returncode})")
    on_progress(1.0)


# ---------------------------------------------------------------- 변환 로직


def build_filter(fps, width):
    """fps 조정 + 가로폭 리사이즈 필터 문자열을 만든다. (세로는 비율 유지)"""
    parts = ["fps={}".format(fps)]
    if width and width > 0:
        parts.append("scale={}:-1:flags=lanczos".format(width))
    return ",".join(parts)


def convert_once(ffmpeg, src_path, dst_path, fps, width, colors, dither,
                 start, duration, loop_forever, total_seconds, cancel_event, on_progress):
    """1회 변환(팔레트 생성 + GIF 생성). 결과 파일 크기(byte)를 반환한다."""
    vf = build_filter(fps, width)

    # -ss/-t 는 반드시 대상 -i 앞에 두어야 그 입력에만 적용된다.
    # (뒤에 두면 2단계에서 팔레트 이미지 입력에 적용되어 구간 지정이 무시된다)
    src_args = []
    if start:
        src_args += ["-ss", str(start)]
    if duration:
        src_args += ["-t", str(duration)]
    src_args += ["-i", str(src_path)]

    tmp_dir = tempfile.mkdtemp(prefix="mp4gif_")
    palette = os.path.join(tmp_dir, "palette.png")
    try:
        # 1단계: 이 영상에 최적화된 색상 팔레트 만들기 (전체 진행률의 0~35%)
        run_ffmpeg(
            ffmpeg,
            src_args
            + ["-vf", "{},palettegen=max_colors={}:stats_mode=diff".format(vf, colors), palette],
            total_seconds,
            cancel_event,
            lambda ratio: on_progress(ratio * 0.35),
        )

        # 2단계: 팔레트를 사용해 GIF 만들기 (전체 진행률의 35~100%)
        lavfi = "{}[x];[x][1:v]paletteuse=dither={}:diff_mode=rectangle".format(vf, dither)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            ffmpeg,
            src_args
            + ["-i", palette, "-lavfi", lavfi, "-loop", "0" if loop_forever else "-1", str(dst_path)],
            total_seconds,
            cancel_event,
            lambda ratio: on_progress(0.35 + ratio * 0.65),
        )
        return dst_path.stat().st_size
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def unique_path(dst_path):
    """같은 이름의 파일이 이미 있으면 뒤에 _1, _2 를 붙여 덮어쓰기를 막는다."""
    if not dst_path.exists():
        return dst_path
    for i in range(1, 1000):
        candidate = dst_path.with_name("{}_{}{}".format(dst_path.stem, i, dst_path.suffix))
        if not candidate.exists():
            return candidate
    return dst_path


def safe_stem(name):
    """GIF 파일명으로 쓰기 곤란한 문자를 정리한다."""
    bad = '\\/:*?"<>|\t\r\n'
    cleaned = "".join(("_" if ch in bad else ch) for ch in name)
    return cleaned.strip() or "output"


def human_size(num_bytes):
    mb = num_bytes / (1024 * 1024)
    if mb >= 1:
        return "{:.1f}MB".format(mb)
    return "{:.0f}KB".format(num_bytes / 1024)


def run_conversion(file_paths, opt, progress_q, cancel_event):
    """백그라운드 스레드에서 실행되는 일괄 변환 루프."""
    try:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            progress_q.put((
                "fatal",
                "동영상 변환 엔진(ffmpeg)을 찾을 수 없습니다.\n\n"
                "개발용으로 실행 중이라면 아래 명령으로 설치해 주세요:\n"
                "    pip install imageio-ffmpeg",
            ))
            return

        total = len(file_paths)
        success_count = 0
        fail_count = 0

        for idx, src in enumerate(file_paths, start=1):
            if cancel_event.is_set():
                break

            src_path = Path(src)
            dst_dir = src_path.parent if opt["output_mode"] == "same" else Path(opt["output_dir"])
            dst_path = unique_path(dst_dir / (safe_stem(src_path.stem) + ".gif"))

            progress_q.put(("start", idx, total, src_path.name))
            try:
                video_len = probe_duration(ffmpeg, src_path)
                # 진행률 표시용 실제 변환 구간 길이
                span = video_len
                if span is not None:
                    span = max(0.0, span - (opt["start"] or 0.0))
                if opt["duration"]:
                    span = opt["duration"] if span is None else min(span, opt["duration"])

                result_size = None
                for step_no, (w_ratio, f_ratio) in enumerate(SHRINK_STEPS):
                    if cancel_event.is_set():
                        raise ConversionCancelled()

                    width = int(opt["width"] * w_ratio) if opt["width"] > 0 else 0
                    if width and width < 80:
                        width = 80
                    fps = max(4, int(round(opt["fps"] * f_ratio)))

                    if step_no > 0:
                        progress_q.put((
                            "log",
                            "    · 용량이 커서 다시 시도합니다 (가로 {}px, {}fps)".format(
                                width if width else "원본", fps),
                        ))

                    def report(ratio, i=idx, t=total, name=src_path.name):
                        progress_q.put(("progress", i, t, name, ratio))

                    result_size = convert_once(
                        ffmpeg, src_path, dst_path, fps, width,
                        opt["colors"], opt["dither"], opt["start"], opt["duration"],
                        opt["loop_forever"], span, cancel_event, report,
                    )

                    if not opt["max_bytes"] or result_size <= opt["max_bytes"]:
                        break
                else:
                    progress_q.put((
                        "log",
                        "    · 목표 용량까지 줄이지 못했습니다. 가능한 가장 작은 설정으로 저장합니다.",
                    ))

                success_count += 1
                progress_q.put(("ok", idx, total, src_path.name, str(dst_path), human_size(result_size)))
            except ConversionCancelled:
                if dst_path.exists():
                    try:
                        dst_path.unlink()
                    except Exception:
                        pass
                break
            except Exception as e:
                fail_count += 1
                progress_q.put(("error", idx, total, src_path.name, str(e)))

        if cancel_event.is_set():
            progress_q.put(("cancelled", success_count, fail_count))
        else:
            progress_q.put(("done", success_count, fail_count))
    except Exception:
        progress_q.put(("fatal", traceback.format_exc()))


# ---------------------------------------------------------------- GUI


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MP4 → 움직이는 GIF 변환기")
        self.geometry("760x680")
        self.minsize(680, 600)

        self.file_paths = []
        self.progress_q = queue.Queue()
        self.worker_thread = None
        self.cancel_event = threading.Event()

        self._build_ui()
        self.after(150, self._poll_queue)

    # ---------- UI 구성 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", **pad)

        ttk.Button(top_frame, text="파일 추가...", command=self.add_files).pack(side="left")
        ttk.Button(top_frame, text="폴더 추가...", command=self.add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(top_frame, text="선택 항목 제거", command=self.remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(top_frame, text="목록 전체 지우기", command=self.clear_list).pack(side="left", padx=(6, 0))

        list_frame = ttk.LabelFrame(self, text="변환할 동영상 파일 목록")
        list_frame.pack(fill="both", expand=True, **pad)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=6)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scrollbar.pack(side="right", fill="y", pady=6)

        # ----- GIF 설정 -----
        gif_frame = ttk.LabelFrame(self, text="GIF 설정")
        gif_frame.pack(fill="x", **pad)

        ttk.Label(gif_frame, text="가로 크기(px):").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        self.width_var = tk.StringVar(value="480")
        ttk.Entry(gif_frame, textvariable=self.width_var, width=8).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(gif_frame, text="(0 = 원본 크기, 세로는 비율에 맞춰 자동)").grid(
            row=0, column=2, columnspan=3, sticky="w", padx=6)

        ttk.Label(gif_frame, text="초당 프레임(FPS):").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.fps_var = tk.StringVar(value="10")
        ttk.Entry(gif_frame, textvariable=self.fps_var, width=8).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(gif_frame, text="(10~15 권장. 높을수록 부드럽지만 용량이 커집니다)").grid(
            row=1, column=2, columnspan=3, sticky="w", padx=6)

        ttk.Label(gif_frame, text="화질:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.quality_var = tk.StringVar(value=DEFAULT_QUALITY)
        ttk.Combobox(
            gif_frame, textvariable=self.quality_var, state="readonly",
            values=list(QUALITY_PRESETS.keys()), width=28,
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=4)

        self.loop_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(gif_frame, text="무한 반복 재생", variable=self.loop_var).grid(
            row=2, column=3, sticky="w", padx=6)

        ttk.Label(gif_frame, text="시작 시간(초):").grid(row=3, column=0, sticky="e", padx=6, pady=4)
        self.start_var = tk.StringVar(value="")
        ttk.Entry(gif_frame, textvariable=self.start_var, width=8).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(gif_frame, text="길이(초):").grid(row=3, column=2, sticky="e", padx=6, pady=4)
        self.dur_var = tk.StringVar(value="")
        ttk.Entry(gif_frame, textvariable=self.dur_var, width=8).grid(row=3, column=3, sticky="w", pady=4)
        ttk.Label(gif_frame, text="(비워두면 영상 전체)").grid(row=3, column=4, sticky="w", padx=6)

        self.limit_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            gif_frame, text="목표 용량 이하로 자동 조절:", variable=self.limit_var,
            command=self._toggle_limit,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        self.limit_mb_var = tk.StringVar(value="10")
        self.limit_entry = ttk.Entry(gif_frame, textvariable=self.limit_mb_var, width=8)
        self.limit_entry.grid(row=4, column=2, sticky="w", pady=4)
        ttk.Label(gif_frame, text="MB (초과하면 크기/프레임을 낮춰 다시 변환)").grid(
            row=4, column=3, columnspan=2, sticky="w", padx=6)

        gif_frame.columnconfigure(4, weight=1)

        # ----- 저장 위치 -----
        option_frame = ttk.LabelFrame(self, text="저장 위치")
        option_frame.pack(fill="x", **pad)

        self.output_mode = tk.StringVar(value="same")
        ttk.Radiobutton(
            option_frame, text="원본 파일과 같은 폴더에 저장", value="same",
            variable=self.output_mode, command=self._toggle_output_dir,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4, columnspan=3)

        ttk.Radiobutton(
            option_frame, text="다른 폴더에 저장:", value="custom",
            variable=self.output_mode, command=self._toggle_output_dir,
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.output_dir_var = tk.StringVar()
        self.output_dir_entry = ttk.Entry(option_frame, textvariable=self.output_dir_var, state="disabled")
        self.output_dir_entry.grid(row=1, column=1, sticky="we", padx=6, pady=4)
        option_frame.columnconfigure(1, weight=1)

        self.browse_btn = ttk.Button(
            option_frame, text="찾아보기...", command=self.browse_output_dir, state="disabled")
        self.browse_btn.grid(row=1, column=2, sticky="w", padx=6, pady=4)

        # ----- 실행 -----
        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)

        self.convert_btn = ttk.Button(action_frame, text="GIF로 변환 시작", command=self.start_conversion)
        self.convert_btn.pack(side="left")

        self.cancel_btn = ttk.Button(action_frame, text="취소", command=self.cancel_conversion, state="disabled")
        self.cancel_btn.pack(side="left", padx=(6, 0))

        self.progress = ttk.Progressbar(action_frame, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))

        log_frame = ttk.LabelFrame(self, text="진행 로그")
        log_frame.pack(fill="both", expand=True, **pad)

        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        log_scroll.pack(side="right", fill="y", pady=6)

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

    def _toggle_output_dir(self):
        state = "normal" if self.output_mode.get() == "custom" else "disabled"
        self.output_dir_entry.configure(state=state)
        self.browse_btn.configure(state=state)

    def _toggle_limit(self):
        self.limit_entry.configure(state="normal" if self.limit_var.get() else "disabled")

    # ---------- 파일 목록 관리 ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="동영상 파일 선택",
            filetypes=[
                ("동영상 파일", "*.mp4 *.avi *.mov *.mkv *.wmv *.m4v *.webm *.mpg *.mpeg *.flv *.ts"),
                ("모든 파일", "*.*"),
            ],
        )
        for p in paths:
            if p not in self.file_paths:
                self.file_paths.append(p)
                self.listbox.insert(tk.END, p)

    def add_folder(self):
        folder = filedialog.askdirectory(title="폴더 선택")
        if not folder:
            return
        added = 0
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if name.lower().endswith(SUPPORTED_EXTS):
                    full = os.path.join(root, name)
                    if full not in self.file_paths:
                        self.file_paths.append(full)
                        self.listbox.insert(tk.END, full)
                        added += 1
        if added == 0:
            messagebox.showinfo("알림", "선택한 폴더에서 동영상 파일을 찾지 못했습니다.")

    def remove_selected(self):
        for idx in reversed(list(self.listbox.curselection())):
            del self.file_paths[idx]
            self.listbox.delete(idx)

    def clear_list(self):
        self.file_paths.clear()
        self.listbox.delete(0, tk.END)

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="저장할 폴더 선택")
        if folder:
            self.output_dir_var.set(folder)

    # ---------- 입력값 검증 ----------
    def _read_number(self, var, label, minimum, maximum, allow_blank=False, integer=True):
        text = var.get().strip()
        if not text:
            if allow_blank:
                return None
            messagebox.showwarning("알림", "{} 값을 입력해 주세요.".format(label))
            return "error"
        try:
            value = int(float(text)) if integer else float(text)
        except ValueError:
            messagebox.showwarning("알림", "{} 값이 숫자가 아닙니다.".format(label))
            return "error"
        if value < minimum or value > maximum:
            messagebox.showwarning("알림", "{} 값은 {} ~ {} 사이여야 합니다.".format(label, minimum, maximum))
            return "error"
        return value

    def _collect_options(self):
        width = self._read_number(self.width_var, "가로 크기", 0, 4000)
        if width == "error":
            return None
        if 0 < width < 80:
            messagebox.showwarning("알림", "가로 크기는 80px 이상이거나 0(원본)이어야 합니다.")
            return None

        fps = self._read_number(self.fps_var, "초당 프레임", 1, 50)
        if fps == "error":
            return None

        start = self._read_number(self.start_var, "시작 시간", 0, 86400, allow_blank=True, integer=False)
        if start == "error":
            return None
        duration = self._read_number(self.dur_var, "길이", 0.1, 86400, allow_blank=True, integer=False)
        if duration == "error":
            return None

        max_bytes = 0
        if self.limit_var.get():
            limit_mb = self._read_number(self.limit_mb_var, "목표 용량", 0.1, 2000, integer=False)
            if limit_mb == "error":
                return None
            max_bytes = int(limit_mb * 1024 * 1024)

        colors, dither = QUALITY_PRESETS[self.quality_var.get()]

        output_mode = self.output_mode.get()
        output_dir = self.output_dir_var.get().strip()
        if output_mode == "custom":
            if not output_dir:
                messagebox.showwarning("알림", "저장할 폴더를 지정해 주세요.")
                return None
            if not os.path.isdir(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("오류", "저장 폴더를 만들 수 없습니다:\n{}".format(e))
                    return None

        return {
            "width": width,
            "fps": fps,
            "colors": colors,
            "dither": dither,
            "start": start,
            "duration": duration,
            "loop_forever": self.loop_var.get(),
            "max_bytes": max_bytes,
            "output_mode": output_mode,
            "output_dir": output_dir,
        }

    # ---------- 변환 실행 ----------
    def start_conversion(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("알림", "이미 변환이 진행 중입니다.")
            return
        if not self.file_paths:
            messagebox.showwarning("알림", "변환할 동영상 파일을 먼저 추가해 주세요.")
            return

        opt = self._collect_options()
        if opt is None:
            return

        self.cancel_event = threading.Event()
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0)
        self._log_clear()
        self._log("총 {}개 파일 변환을 시작합니다...".format(len(self.file_paths)))
        self.status_var.set("변환 중...")

        self.worker_thread = threading.Thread(
            target=run_conversion,
            args=(list(self.file_paths), opt, self.progress_q, self.cancel_event),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_conversion(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.cancel_event.set()
            self.cancel_btn.configure(state="disabled")
            self.status_var.set("취소하는 중...")

    # ---------- 진행 상황 반영 ----------
    def _finish(self, message):
        self.status_var.set(message)
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                msg = self.progress_q.get_nowait()
                kind = msg[0]
                if kind == "start":
                    _, idx, total, name = msg
                    self.status_var.set("[{}/{}] 변환 중: {}".format(idx, total, name))
                elif kind == "progress":
                    _, idx, total, name, ratio = msg
                    overall = ((idx - 1) + ratio) / total * 100
                    self.progress.configure(value=overall)
                    self.status_var.set("[{}/{}] 변환 중: {}  ({:.0f}%)".format(idx, total, name, ratio * 100))
                elif kind == "log":
                    self._log(msg[1])
                elif kind == "ok":
                    _, idx, total, name, dst, size = msg
                    self.progress.configure(value=idx / total * 100)
                    self._log("[성공] {} → {}  ({})".format(name, dst, size))
                elif kind == "error":
                    _, idx, total, name, err = msg
                    self.progress.configure(value=idx / total * 100)
                    self._log("[실패] {} : {}".format(name, err))
                elif kind == "done":
                    _, ok_count, fail_count = msg
                    self._finish("완료: 성공 {}건 / 실패 {}건".format(ok_count, fail_count))
                    self._log("모든 작업이 끝났습니다. 성공 {}건, 실패 {}건.".format(ok_count, fail_count))
                    if fail_count == 0:
                        messagebox.showinfo("완료", "{}개 파일을 GIF로 변환했습니다.".format(ok_count))
                    else:
                        messagebox.showwarning(
                            "완료 (일부 실패)",
                            "성공 {}건, 실패 {}건입니다.\n로그를 확인해 주세요.".format(ok_count, fail_count),
                        )
                elif kind == "cancelled":
                    _, ok_count, fail_count = msg
                    self._finish("사용자가 취소했습니다 (성공 {}건)".format(ok_count))
                    self._log("변환을 취소했습니다. 성공 {}건.".format(ok_count))
                elif kind == "fatal":
                    self._log("[오류] {}".format(msg[1]))
                    self._finish("오류로 중단됨")
                    messagebox.showerror("오류", str(msg[1]))
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _log_clear(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
