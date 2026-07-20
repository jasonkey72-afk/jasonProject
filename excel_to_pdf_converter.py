"""
Excel to PDF 변환기
====================
Microsoft Excel을 자동화(COM)하여 xlsx/xls/xlsm 파일을 원본 그대로 PDF로 변환합니다.
- 원본 파일은 읽기 전용으로 열고 저장하지 않으므로 절대 손상되지 않습니다.
- 실제 Excel 렌더링 엔진을 사용하므로 한글을 포함한 서식/내용이 깨지지 않습니다.
- 여러 개의 파일을 한 번에 선택하여 일괄 변환할 수 있습니다.

실행하려면 이 PC에 Microsoft Excel이 설치되어 있어야 합니다.
"""

import os
import sys
import threading
import queue
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

SUPPORTED_EXTS = (".xlsx", ".xlsm", ".xls")

# xlTypePDF
XL_TYPE_PDF = 0
# xlQualityStandard
XL_QUALITY_STANDARD = 0


class ConversionError(Exception):
    pass


def convert_one_file(excel_app, src_path: Path, dst_path: Path, fit_to_width: bool):
    """단일 Excel 파일을 PDF로 변환한다. 원본은 절대 수정/저장하지 않는다."""
    wb = None
    try:
        wb = excel_app.Workbooks.Open(
            str(src_path),
            UpdateLinks=0,
            ReadOnly=True,
            IgnoreReadOnlyRecommended=True,
            Notify=False,
        )

        if fit_to_width:
            for ws in wb.Worksheets:
                try:
                    ws.PageSetup.Zoom = False
                    ws.PageSetup.FitToPagesWide = 1
                    ws.PageSetup.FitToPagesTall = False
                except Exception:
                    # 일부 시트(차트 시트 등)는 PageSetup 속성이 없을 수 있으므로 무시
                    pass

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        wb.ExportAsFixedFormat(
            Type=XL_TYPE_PDF,
            Filename=str(dst_path),
            Quality=XL_QUALITY_STANDARD,
            IncludeDocProperties=True,
            IgnorePrintAreas=False,
            OpenAfterPublish=False,
        )
    finally:
        if wb is not None:
            # SaveChanges=False : 원본 파일은 절대 변경/저장하지 않는다
            wb.Close(SaveChanges=False)


def run_conversion(file_paths, output_mode, output_dir, fit_to_width, progress_q):
    """백그라운드 스레드에서 실행되는 일괄 변환 루프."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel_app = None
    try:
        try:
            excel_app = win32com.client.DispatchEx("Excel.Application")
        except Exception:
            progress_q.put(("fatal", "Microsoft Excel을 찾을 수 없습니다. 이 PC에 Excel이 설치되어 있는지 확인해 주세요."))
            return

        excel_app.Visible = False
        excel_app.DisplayAlerts = False
        excel_app.ScreenUpdating = False

        total = len(file_paths)
        success_count = 0
        fail_count = 0

        for idx, src in enumerate(file_paths, start=1):
            src_path = Path(src)
            if output_mode == "same":
                dst_dir = src_path.parent
            else:
                dst_dir = Path(output_dir)
            dst_path = dst_dir / (src_path.stem + ".pdf")

            progress_q.put(("start", idx, total, src_path.name))
            try:
                convert_one_file(excel_app, src_path, dst_path, fit_to_width)
                success_count += 1
                progress_q.put(("ok", idx, total, src_path.name, str(dst_path)))
            except Exception as e:
                fail_count += 1
                progress_q.put(("error", idx, total, src_path.name, str(e)))

        progress_q.put(("done", success_count, fail_count))
    except Exception:
        progress_q.put(("fatal", traceback.format_exc()))
    finally:
        try:
            if excel_app is not None:
                excel_app.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Excel → PDF 변환기")
        self.geometry("720x560")
        self.minsize(640, 480)

        self.file_paths = []
        self.progress_q = queue.Queue()
        self.worker_thread = None

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

        list_frame = ttk.LabelFrame(self, text="변환할 Excel 파일 목록")
        list_frame.pack(fill="both", expand=True, **pad)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scrollbar.pack(side="right", fill="y", pady=6)

        option_frame = ttk.LabelFrame(self, text="저장 위치")
        option_frame.pack(fill="x", **pad)

        self.output_mode = tk.StringVar(value="same")
        ttk.Radiobutton(
            option_frame, text="원본 파일과 같은 폴더에 저장", value="same",
            variable=self.output_mode, command=self._toggle_output_dir
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4, columnspan=3)

        ttk.Radiobutton(
            option_frame, text="다른 폴더에 저장:", value="custom",
            variable=self.output_mode, command=self._toggle_output_dir
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.output_dir_var = tk.StringVar()
        self.output_dir_entry = ttk.Entry(option_frame, textvariable=self.output_dir_var, state="disabled")
        self.output_dir_entry.grid(row=1, column=1, sticky="we", padx=6, pady=4)
        option_frame.columnconfigure(1, weight=1)

        self.browse_btn = ttk.Button(option_frame, text="찾아보기...", command=self.browse_output_dir, state="disabled")
        self.browse_btn.grid(row=1, column=2, sticky="w", padx=6, pady=4)

        self.fit_to_width_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            option_frame,
            text="인쇄 시 한 페이지 폭에 맞추기 (열이 잘리지 않도록 자동 축소)",
            variable=self.fit_to_width_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)

        self.convert_btn = ttk.Button(action_frame, text="PDF로 변환 시작", command=self.start_conversion)
        self.convert_btn.pack(side="left")

        self.progress = ttk.Progressbar(action_frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))

        log_frame = ttk.LabelFrame(self, text="진행 로그")
        log_frame.pack(fill="both", expand=True, **pad)

        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
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

    # ---------- 파일 목록 관리 ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Excel 파일 선택",
            filetypes=[("Excel 파일", "*.xlsx *.xlsm *.xls"), ("모든 파일", "*.*")],
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
            for name in files:
                if name.lower().endswith(SUPPORTED_EXTS) and not name.startswith("~$"):
                    full = os.path.join(root, name)
                    if full not in self.file_paths:
                        self.file_paths.append(full)
                        self.listbox.insert(tk.END, full)
                        added += 1
        if added == 0:
            messagebox.showinfo("알림", "선택한 폴더에서 Excel 파일을 찾지 못했습니다.")

    def remove_selected(self):
        selected = list(self.listbox.curselection())
        for idx in reversed(selected):
            del self.file_paths[idx]
            self.listbox.delete(idx)

    def clear_list(self):
        self.file_paths.clear()
        self.listbox.delete(0, tk.END)

    # ---------- 변환 실행 ----------
    def start_conversion(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("알림", "이미 변환이 진행 중입니다.")
            return
        if not self.file_paths:
            messagebox.showwarning("알림", "변환할 Excel 파일을 먼저 추가해 주세요.")
            return

        output_mode = self.output_mode.get()
        output_dir = self.output_dir_var.get().strip()
        if output_mode == "custom":
            if not output_dir:
                messagebox.showwarning("알림", "저장할 폴더를 지정해 주세요.")
                return
            if not os.path.isdir(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("오류", f"저장 폴더를 만들 수 없습니다:\n{e}")
                    return

        self.convert_btn.configure(state="disabled")
        self.progress.configure(value=0, maximum=len(self.file_paths))
        self._log_clear()
        self._log(f"총 {len(self.file_paths)}개 파일 변환을 시작합니다...")
        self.status_var.set("변환 중...")

        self.worker_thread = threading.Thread(
            target=run_conversion,
            args=(
                list(self.file_paths),
                output_mode,
                output_dir,
                self.fit_to_width_var.get(),
                self.progress_q,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="저장할 폴더 선택")
        if folder:
            self.output_dir_var.set(folder)

    # ---------- 진행 상황 반영 ----------
    def _poll_queue(self):
        try:
            while True:
                msg = self.progress_q.get_nowait()
                kind = msg[0]
                if kind == "start":
                    _, idx, total, name = msg
                    self.status_var.set(f"[{idx}/{total}] 변환 중: {name}")
                elif kind == "ok":
                    _, idx, total, name, dst = msg
                    self.progress.configure(value=idx)
                    self._log(f"[성공] {name} → {dst}")
                elif kind == "error":
                    _, idx, total, name, err = msg
                    self.progress.configure(value=idx)
                    self._log(f"[실패] {name} : {err}")
                elif kind == "done":
                    _, ok_count, fail_count = msg
                    self.status_var.set(f"완료: 성공 {ok_count}건 / 실패 {fail_count}건")
                    self._log(f"모든 작업이 끝났습니다. 성공 {ok_count}건, 실패 {fail_count}건.")
                    self.convert_btn.configure(state="normal")
                    if fail_count == 0:
                        messagebox.showinfo("완료", f"{ok_count}개 파일을 PDF로 변환했습니다.")
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
    if sys.platform != "win32":
        print("이 프로그램은 Microsoft Excel COM 자동화를 사용하므로 Windows에서만 실행할 수 있습니다.")
        sys.exit(1)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
