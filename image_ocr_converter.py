"""
이미지 OCR 변환기
====================
그림 파일(jpg/jpeg/png/bmp/tiff/gif)을 이미지 첨부가 불가능한 환경(예: 사내 LLM 챗봇)에서도
사용할 수 있도록, OCR(광학 문자 인식)로 이미지 속 글자를 텍스트로 추출해 주는 프로그램입니다.

- Tesseract OCR 엔진(무료/오픈소스)을 사용하여 이미지 속 텍스트를 인식합니다.
- 인식된 텍스트는 화면에서 바로 복사하거나, 이미지와 같은 이름의 .txt 파일로 저장할 수 있습니다.
- 여러 개의 이미지를 한 번에 선택하여 일괄 변환할 수 있습니다.

실행하려면 이 PC에 Tesseract-OCR 엔진이 설치되어 있어야 합니다.
(https://github.com/UB-Mannheim/tesseract/wiki 에서 Windows용 설치파일 다운로드)
"""

import os
import sys
import threading
import queue
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp")

LANGUAGE_OPTIONS = [
    ("한국어 + 영어", "kor+eng"),
    ("한국어", "kor"),
    ("영어", "eng"),
]

# Windows에 Tesseract를 기본 경로로 설치했을 때 흔히 발견되는 위치
COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

TESSERACT_INSTALL_MSG = (
    "Tesseract-OCR 엔진을 찾을 수 없습니다.\n\n"
    "아래 주소에서 Windows용 설치파일을 내려받아 설치한 뒤 다시 실행해 주세요.\n"
    "https://github.com/UB-Mannheim/tesseract/wiki\n\n"
    "설치 시 'Additional language data'에서 Korean(kor)을 함께 선택하면\n"
    "한글 인식도 가능합니다.\n\n"
    "이미 설치했는데도 이 메시지가 보이면, '설정 > Tesseract 경로 지정...' 에서\n"
    "tesseract.exe 파일 위치를 직접 지정해 주세요."
)


class OcrError(Exception):
    pass


def locate_tesseract(pytesseract):
    """설치된 tesseract.exe 경로를 자동으로 찾아 pytesseract에 설정한다."""
    import shutil

    found = shutil.which("tesseract")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return True

    for candidate in COMMON_TESSERACT_PATHS:
        if os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True

    return False


def convert_one_file(image_path: Path, lang: str, pytesseract, Image) -> str:
    """단일 이미지 파일에서 텍스트를 추출한다."""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            text = pytesseract.image_to_string(img, lang=lang)
    except Exception as e:
        raise OcrError(str(e)) from e
    return text.strip()


def run_ocr(file_paths, lang, save_txt, combined_path, progress_q):
    """백그라운드 스레드에서 실행되는 일괄 OCR 루프."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        progress_q.put((
            "fatal",
            "필요한 파이썬 패키지가 설치되어 있지 않습니다.\n"
            "pip install -r requirements.txt 를 먼저 실행해 주세요.",
        ))
        return

    if not locate_tesseract(pytesseract):
        progress_q.put(("fatal", TESSERACT_INSTALL_MSG))
        return

    total = len(file_paths)
    success_count = 0
    fail_count = 0
    combined_chunks = []

    for idx, src in enumerate(file_paths, start=1):
        src_path = Path(src)
        progress_q.put(("start", idx, total, src_path.name))
        try:
            text = convert_one_file(src_path, lang, pytesseract, Image)
            success_count += 1

            if save_txt:
                txt_path = src_path.with_suffix(".txt")
                txt_path.write_text(text, encoding="utf-8")

            combined_chunks.append(f"===== {src_path.name} =====\n{text}\n")
            progress_q.put(("ok", idx, total, src_path.name, text))
        except OcrError as e:
            fail_count += 1
            progress_q.put(("error", idx, total, src_path.name, str(e)))
        except Exception:
            fail_count += 1
            progress_q.put(("error", idx, total, src_path.name, traceback.format_exc()))

    if combined_path and combined_chunks:
        try:
            Path(combined_path).write_text("\n".join(combined_chunks), encoding="utf-8")
        except Exception as e:
            progress_q.put(("combined_error", str(e)))

    progress_q.put(("done", success_count, fail_count))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("이미지 OCR 변환기")
        self.geometry("820x680")
        self.minsize(680, 520)

        self.file_paths = []
        self.results = {}  # 파일 경로 -> 추출된 텍스트
        self.progress_q = queue.Queue()
        self.worker_thread = None

        self._build_ui()
        self.after(150, self._poll_queue)

    # ---------- UI 구성 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", **pad)

        ttk.Button(top_frame, text="이미지 추가...", command=self.add_files).pack(side="left")
        ttk.Button(top_frame, text="폴더 추가...", command=self.add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(top_frame, text="선택 항목 제거", command=self.remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(top_frame, text="목록 전체 지우기", command=self.clear_list).pack(side="left", padx=(6, 0))

        ttk.Label(top_frame, text="인식 언어:").pack(side="left", padx=(20, 4))
        self.lang_var = tk.StringVar(value=LANGUAGE_OPTIONS[0][1])
        lang_combo = ttk.Combobox(
            top_frame,
            state="readonly",
            width=14,
            values=[label for label, _ in LANGUAGE_OPTIONS],
        )
        lang_combo.current(0)
        lang_combo.bind("<<ComboboxSelected>>", lambda e: self.lang_var.set(
            dict((label, code) for label, code in LANGUAGE_OPTIONS)[lang_combo.get()]
        ))
        lang_combo.pack(side="left")

        main_pane = ttk.Panedwindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True, **pad)

        list_frame = ttk.LabelFrame(main_pane, text="이미지 파일 목록 (클릭하면 결과 미리보기)")
        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=list_scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        list_scroll.pack(side="right", fill="y", pady=6)
        self.listbox.bind("<<ListboxSelect>>", self._on_select_item)
        main_pane.add(list_frame, weight=1)

        preview_frame = ttk.LabelFrame(main_pane, text="추출된 텍스트 (여기서 바로 복사해서 붙여넣으세요)")
        self.preview_text = tk.Text(preview_frame, wrap="word")
        preview_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_scroll.set)
        self.preview_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        preview_scroll.pack(side="right", fill="y", pady=6)
        main_pane.add(preview_frame, weight=2)

        preview_btn_frame = ttk.Frame(self)
        preview_btn_frame.pack(fill="x", padx=10)
        ttk.Button(preview_btn_frame, text="이 텍스트 클립보드에 복사", command=self.copy_preview).pack(side="left")

        option_frame = ttk.LabelFrame(self, text="저장 옵션")
        option_frame.pack(fill="x", **pad)

        self.save_txt_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            option_frame,
            text="이미지와 같은 이름의 .txt 파일로 각각 저장 (예: 사진1.png → 사진1.txt)",
            variable=self.save_txt_var,
        ).pack(anchor="w", padx=6, pady=2)

        self.combined_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            option_frame,
            text="모든 결과를 하나의 텍스트 파일로도 합쳐서 저장",
            variable=self.combined_var,
        ).pack(anchor="w", padx=6, pady=2)

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)

        self.convert_btn = ttk.Button(action_frame, text="텍스트로 변환 시작", command=self.start_conversion)
        self.convert_btn.pack(side="left")

        self.progress = ttk.Progressbar(action_frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))

        log_frame = ttk.LabelFrame(self, text="진행 로그")
        log_frame.pack(fill="both", **pad)

        self.log_text = tk.Text(log_frame, height=6, state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        log_scroll.pack(side="right", fill="y", pady=6)

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

    # ---------- 파일 목록 관리 ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="이미지 파일 선택",
            filetypes=[
                ("이미지 파일", "*.jpg *.jpeg *.png *.bmp *.tiff *.tif *.gif *.webp"),
                ("모든 파일", "*.*"),
            ],
        )
        for p in paths:
            if p not in self.file_paths:
                self.file_paths.append(p)
                self.listbox.insert(tk.END, Path(p).name)

    def add_folder(self):
        folder = filedialog.askdirectory(title="폴더 선택")
        if not folder:
            return
        added = 0
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(SUPPORTED_EXTS):
                    full = os.path.join(root, name)
                    if full not in self.file_paths:
                        self.file_paths.append(full)
                        self.listbox.insert(tk.END, Path(full).name)
                        added += 1
        if added == 0:
            messagebox.showinfo("알림", "선택한 폴더에서 이미지 파일을 찾지 못했습니다.")

    def remove_selected(self):
        selected = list(self.listbox.curselection())
        for idx in reversed(selected):
            removed = self.file_paths.pop(idx)
            self.results.pop(removed, None)
            self.listbox.delete(idx)

    def clear_list(self):
        self.file_paths.clear()
        self.results.clear()
        self.listbox.delete(0, tk.END)
        self.preview_text.delete("1.0", tk.END)

    def _on_select_item(self, _event):
        selected = self.listbox.curselection()
        if not selected:
            return
        path = self.file_paths[selected[0]]
        text = self.results.get(path, "(아직 변환되지 않았습니다)")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, text)

    def copy_preview(self):
        text = self.preview_text.get("1.0", tk.END).strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("클립보드에 복사되었습니다.")

    # ---------- 변환 실행 ----------
    def start_conversion(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("알림", "이미 변환이 진행 중입니다.")
            return
        if not self.file_paths:
            messagebox.showwarning("알림", "변환할 이미지 파일을 먼저 추가해 주세요.")
            return

        combined_path = None
        if self.combined_var.get():
            combined_path = filedialog.asksaveasfilename(
                title="합쳐진 결과 텍스트 파일 저장 위치",
                defaultextension=".txt",
                initialfile="ocr_결과_모음.txt",
                filetypes=[("텍스트 파일", "*.txt")],
            )
            if not combined_path:
                return

        self.convert_btn.configure(state="disabled")
        self.progress.configure(value=0, maximum=len(self.file_paths))
        self._log_clear()
        self._log(f"총 {len(self.file_paths)}개 이미지 변환을 시작합니다...")
        self.status_var.set("변환 중...")

        self.worker_thread = threading.Thread(
            target=run_ocr,
            args=(
                list(self.file_paths),
                self.lang_var.get(),
                self.save_txt_var.get(),
                combined_path,
                self.progress_q,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    # ---------- 진행 상황 반영 ----------
    def _poll_queue(self):
        try:
            while True:
                msg = self.progress_q.get_nowait()
                kind = msg[0]
                if kind == "start":
                    _, idx, total, name = msg
                    self.status_var.set(f"[{idx}/{total}] 인식 중: {name}")
                elif kind == "ok":
                    _, idx, total, name, text = msg
                    self.progress.configure(value=idx)
                    self.results[self.file_paths[idx - 1]] = text
                    preview = text[:40].replace("\n", " ")
                    self._log(f"[성공] {name} : {preview}{'...' if len(text) > 40 else ''}")
                elif kind == "error":
                    _, idx, total, name, err = msg
                    self.progress.configure(value=idx)
                    self._log(f"[실패] {name} : {err}")
                elif kind == "combined_error":
                    self._log(f"[오류] 통합 파일 저장 실패: {msg[1]}")
                elif kind == "done":
                    _, ok_count, fail_count = msg
                    self.status_var.set(f"완료: 성공 {ok_count}건 / 실패 {fail_count}건")
                    self._log(f"모든 작업이 끝났습니다. 성공 {ok_count}건, 실패 {fail_count}건.")
                    self.convert_btn.configure(state="normal")
                    if fail_count == 0:
                        messagebox.showinfo("완료", f"{ok_count}개 이미지에서 텍스트를 추출했습니다.\n목록에서 파일을 클릭하면 결과를 볼 수 있습니다.")
                    else:
                        messagebox.showwarning(
                            "완료 (일부 실패)",
                            f"성공 {ok_count}건, 실패 {fail_count}건입니다.\n로그를 확인해 주세요.",
                        )
                elif kind == "fatal":
                    self._log(f"[오류] {msg[1]}")
                    self.status_var.set("오류로 중단됨")
                    self.convert_btn.configure(state="normal")
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
