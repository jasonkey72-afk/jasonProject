"""
Spotfire(.dxp) → Excel 변환/검색 도구
======================================
TIBCO Spotfire를 실행하지 않고도 ".dxp" 분석 파일 안에 저장된 데이터 테이블을
직접 읽어 Excel(.xlsx)로 변환하거나, 키워드로 검색해서 해당 데이터만 추출합니다.

동작 원리
---------
Spotfire 7.0 이상에서 저장된 .dxp 파일은 내부적으로 ZIP 압축 패키지이며, 그 안에
데이터 테이블이 SBDF(Spotfire Binary Data Format) 형식으로 저장되어 있습니다.
이 도구는 .dxp를 열지 않고 그 내부 구조를 직접 읽어 데이터 테이블을 찾아냅니다.
(Spotfire 7.0 이전의 구버전 바이너리 형식이거나, 내장 데이터 없이 외부 DB에만
연결되어 있는 .dxp는 지원하지 않습니다.)
"""

import os
import re
import sys
import zipfile
import tempfile
import threading
import queue
import traceback
import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pandas as pd

SUPPORTED_EXTS = (".dxp",)
SBDF_MAGIC = b"\xdf\x5b"
EXCEL_MAX_DATA_ROWS = 1_048_576 - 1  # 헤더 1행 제외
_INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")
_GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
_NAME_ATTR_RE = re.compile(r'[Nn]ame="([^"]{1,120})"')


class ConversionError(Exception):
    pass


# ---------- .dxp 내부 데이터 테이블 탐색 ----------

def _collect_table_name_hints(zf: zipfile.ZipFile) -> dict:
    """xml 등 텍스트 항목에서 GUID ↔ 표시 이름 힌트를 찾는다 (찾지 못해도 변환에는 지장 없음)."""
    hints = {}
    for info in zf.infolist():
        if info.is_dir() or info.file_size > 3_000_000:
            continue
        lower = info.filename.lower()
        if not (lower.endswith(".xml") or lower.endswith(".txt")):
            continue
        try:
            with zf.open(info) as f:
                text = f.read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        for m in _GUID_RE.finditer(text):
            guid = m.group(1)
            if guid in hints:
                continue
            # GUID와 Name 속성은 보통 같은 XML 태그 안에 있으므로, 해당 태그 범위로 한정해서 찾는다.
            tag_start = text.rfind("<", 0, m.start())
            tag_end = text.find(">", m.end())
            if tag_start == -1 or tag_end == -1:
                continue
            nm = _NAME_ATTR_RE.search(text[tag_start:tag_end + 1])
            if nm:
                hints[guid] = nm.group(1)
    return hints


def find_dxp_tables(dxp_path: Path, log=lambda msg: None):
    """.dxp(zip) 안에서 SBDF 데이터 테이블을 찾아 (표시이름, 내부경로, DataFrame) 리스트로 반환한다."""
    import spotfire.sbdf as sbdf

    try:
        zf = zipfile.ZipFile(dxp_path)
    except zipfile.BadZipFile as e:
        raise ConversionError(
            "이 파일은 압축(zip) 기반 형식이 아닙니다. "
            "Spotfire 7.0 이상에서 저장된 .dxp 파일만 지원합니다."
        ) from e

    tables = []
    with zf:
        guid_name_map = _collect_table_name_hints(zf)
        candidates = [info for info in zf.infolist() if not info.is_dir() and info.file_size >= 8]

        for info in candidates:
            try:
                with zf.open(info) as fh:
                    head = fh.read(2)
            except Exception:
                continue
            if head != SBDF_MAGIC:
                continue

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".sbdf", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                    with zf.open(info) as src:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            tmp.write(chunk)
                df = sbdf.import_data(str(tmp_path))
            except Exception as e:
                log(f"  [건너뜀] {info.filename}: 데이터 테이블로 읽을 수 없음 ({e})")
                continue
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            guid = Path(info.filename).stem
            display_name = guid_name_map.get(guid) or guid_name_map.get(info.filename) or Path(info.filename).name
            tables.append((display_name, info.filename, df))
            log(f"  [발견] 데이터 테이블 '{display_name}' ({len(df)}행 x {len(df.columns)}열)")

    if not tables:
        log("  이 파일에서 내장 데이터 테이블을 찾지 못했습니다.")
    return tables


# ---------- Excel 저장용 정리 ----------

def _clean_cell_value(value):
    if isinstance(value, bytes):
        return f"<바이너리 {len(value)} bytes>"
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _clean_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """openpyxl로 저장 가능하도록 시간대 정보/바이너리 값 등을 정리한다."""
    df = df.copy()
    for col in df.columns:
        series = df[col]
        if series.dtype == "object":
            df[col] = series.map(_clean_cell_value)
        elif str(series.dtype).startswith("datetime64") and getattr(series.dt, "tz", None) is not None:
            df[col] = series.dt.tz_localize(None)
    return df


def _sanitize_sheet_name(name: str, used: set) -> str:
    name = _INVALID_SHEET_CHARS.sub("_", str(name)).strip() or "Sheet"
    name = name[:31]
    base, i = name, 2
    while name in used:
        suffix = f"_{i}"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


def _move_sheet_to_front(writer, sheet_name):
    book = writer.book
    idx = book.sheetnames.index(sheet_name)
    book.move_sheet(sheet_name, offset=-idx)


# ---------- 검색 ----------

def search_in_tables(tables, keyword: str, case_sensitive: bool):
    """추출된 테이블에서 키워드가 포함된 행을 찾아 (표시이름, 매칭행 DataFrame) 리스트로 반환한다."""
    needle = keyword if case_sensitive else keyword.lower()
    results = []
    for display_name, _entry, df in tables:
        if df.empty:
            continue

        def row_matches(row):
            for val in row:
                if val is None:
                    continue
                text = str(val)
                if not case_sensitive:
                    text = text.lower()
                if needle in text:
                    return True
            return False

        mask = df.apply(row_matches, axis=1)
        matched = df[mask]
        if not matched.empty:
            results.append((display_name, matched))
    return results


# ---------- Excel 작성 ----------

def write_excel_full(tables, dst_path: Path):
    used_names = set()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(dst_path, engine="openpyxl") as writer:
        if not tables:
            pd.DataFrame({"안내": ["이 파일에서 추출 가능한 데이터 테이블을 찾지 못했습니다."]}).to_excel(
                writer, sheet_name="안내", index=False
            )
            return

        summary_rows = []
        for display_name, _entry, df in tables:
            sheet = _sanitize_sheet_name(display_name, used_names)
            clean = _clean_dataframe_for_excel(df)
            truncated = len(clean) > EXCEL_MAX_DATA_ROWS
            if truncated:
                clean = clean.iloc[:EXCEL_MAX_DATA_ROWS]
            clean.to_excel(writer, sheet_name=sheet, index=False)
            summary_rows.append(
                {
                    "시트명": sheet,
                    "원본 테이블": display_name,
                    "행수": len(df),
                    "열수": len(df.columns),
                    "비고": "Excel 행 제한으로 일부만 저장됨" if truncated else "",
                }
            )
        summary_sheet = _sanitize_sheet_name("요약", used_names)
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name=summary_sheet, index=False)
        _move_sheet_to_front(writer, summary_sheet)


def write_excel_search(tables, search_results, keyword: str, dst_path: Path):
    used_names = set()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(dst_path, engine="openpyxl") as writer:
        if not search_results:
            pd.DataFrame({"안내": [f"'{keyword}' 검색 결과가 없습니다. (검색된 테이블 수: {len(tables)}개)"]}).to_excel(
                writer, sheet_name="검색결과", index=False
            )
            return

        overview_rows = []
        for display_name, matched in search_results:
            sheet = _sanitize_sheet_name(f"{display_name}_검색", used_names)
            clean = _clean_dataframe_for_excel(matched)
            truncated = len(clean) > EXCEL_MAX_DATA_ROWS
            if truncated:
                clean = clean.iloc[:EXCEL_MAX_DATA_ROWS]
            clean.to_excel(writer, sheet_name=sheet, index=False)
            overview_rows.append(
                {
                    "시트명": sheet,
                    "원본 테이블": display_name,
                    "매칭 행수": len(matched),
                    "비고": "Excel 행 제한으로 일부만 저장됨" if truncated else "",
                }
            )
        summary_sheet = _sanitize_sheet_name("검색요약", used_names)
        pd.DataFrame(overview_rows).to_excel(writer, sheet_name=summary_sheet, index=False)
        _move_sheet_to_front(writer, summary_sheet)


# ---------- 변환 실행 ----------

def convert_one_file(src_path: Path, dst_path: Path, mode: str, keyword: str, case_sensitive: bool, log):
    tables = find_dxp_tables(src_path, log=log)
    if mode == "convert":
        write_excel_full(tables, dst_path)
    else:
        results = search_in_tables(tables, keyword, case_sensitive)
        write_excel_search(tables, results, keyword, dst_path)


def run_conversion(file_paths, output_mode, output_dir, mode, keyword, case_sensitive, progress_q):
    """백그라운드 스레드에서 실행되는 일괄 변환 루프."""
    try:
        try:
            import spotfire.sbdf  # noqa: F401
        except ImportError:
            progress_q.put(
                ("fatal", "'spotfire' 패키지가 설치되어 있지 않습니다. 'pip install -r requirements.txt'로 설치해 주세요.")
            )
            return

        total = len(file_paths)
        success_count = 0
        fail_count = 0
        suffix = "_변환.xlsx" if mode == "convert" else "_검색결과.xlsx"

        for idx, src in enumerate(file_paths, start=1):
            src_path = Path(src)
            dst_dir = src_path.parent if output_mode == "same" else Path(output_dir)
            dst_path = dst_dir / (src_path.stem + suffix)

            progress_q.put(("start", idx, total, src_path.name))
            log = lambda msg, idx=idx, total=total: progress_q.put(("info", idx, total, msg))
            try:
                convert_one_file(src_path, dst_path, mode, keyword, case_sensitive, log)
                success_count += 1
                progress_q.put(("ok", idx, total, src_path.name, str(dst_path)))
            except Exception as e:
                fail_count += 1
                progress_q.put(("error", idx, total, src_path.name, str(e)))

        progress_q.put(("done", success_count, fail_count))
    except Exception:
        progress_q.put(("fatal", traceback.format_exc()))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Spotfire(.dxp) → Excel 변환/검색 도구")
        self.geometry("760x640")
        self.minsize(680, 560)

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

        list_frame = ttk.LabelFrame(self, text="변환할 .dxp 파일 목록")
        list_frame.pack(fill="both", expand=True, **pad)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scrollbar.pack(side="right", fill="y", pady=6)

        mode_frame = ttk.LabelFrame(self, text="작업 방식")
        mode_frame.pack(fill="x", **pad)

        self.mode_var = tk.StringVar(value="convert")
        ttk.Radiobutton(
            mode_frame, text="전체 데이터를 Excel로 변환", value="convert",
            variable=self.mode_var, command=self._toggle_search_fields
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4, columnspan=4)

        ttk.Radiobutton(
            mode_frame, text="키워드로 검색해서 해당 데이터만 추출", value="search",
            variable=self.mode_var, command=self._toggle_search_fields
        ).grid(row=1, column=0, sticky="w", padx=6, pady=4)

        self.keyword_var = tk.StringVar()
        self.keyword_entry = ttk.Entry(mode_frame, textvariable=self.keyword_var, state="disabled", width=30)
        self.keyword_entry.grid(row=1, column=1, sticky="we", padx=6, pady=4)
        mode_frame.columnconfigure(1, weight=1)

        self.case_sensitive_var = tk.BooleanVar(value=False)
        self.case_sensitive_chk = ttk.Checkbutton(
            mode_frame, text="대소문자 구분", variable=self.case_sensitive_var, state="disabled"
        )
        self.case_sensitive_chk.grid(row=1, column=2, sticky="w", padx=6, pady=4)

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

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)

        self.convert_btn = ttk.Button(action_frame, text="시작", command=self.start_conversion)
        self.convert_btn.pack(side="left")

        self.progress = ttk.Progressbar(action_frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))

        log_frame = ttk.LabelFrame(self, text="진행 로그")
        log_frame.pack(fill="both", expand=True, **pad)

        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        log_scroll.pack(side="right", fill="y", pady=6)

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

    def _toggle_search_fields(self):
        state = "normal" if self.mode_var.get() == "search" else "disabled"
        self.keyword_entry.configure(state=state)
        self.case_sensitive_chk.configure(state=state)

    def _toggle_output_dir(self):
        state = "normal" if self.output_mode.get() == "custom" else "disabled"
        self.output_dir_entry.configure(state=state)
        self.browse_btn.configure(state=state)

    # ---------- 파일 목록 관리 ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Spotfire .dxp 파일 선택",
            filetypes=[("Spotfire 파일", "*.dxp"), ("모든 파일", "*.*")],
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
                if name.lower().endswith(SUPPORTED_EXTS):
                    full = os.path.join(root, name)
                    if full not in self.file_paths:
                        self.file_paths.append(full)
                        self.listbox.insert(tk.END, full)
                        added += 1
        if added == 0:
            messagebox.showinfo("알림", "선택한 폴더에서 .dxp 파일을 찾지 못했습니다.")

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
            messagebox.showwarning("알림", "이미 작업이 진행 중입니다.")
            return
        if not self.file_paths:
            messagebox.showwarning("알림", "변환할 .dxp 파일을 먼저 추가해 주세요.")
            return

        mode = self.mode_var.get()
        keyword = self.keyword_var.get().strip()
        if mode == "search" and not keyword:
            messagebox.showwarning("알림", "검색할 키워드를 입력해 주세요.")
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
        self._log(f"총 {len(self.file_paths)}개 파일 작업을 시작합니다...")
        self.status_var.set("작업 중...")

        self.worker_thread = threading.Thread(
            target=run_conversion,
            args=(
                list(self.file_paths),
                output_mode,
                output_dir,
                mode,
                keyword,
                self.case_sensitive_var.get(),
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
                    self.status_var.set(f"[{idx}/{total}] 처리 중: {name}")
                elif kind == "info":
                    _, idx, total, text = msg
                    self._log(text)
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
                        messagebox.showinfo("완료", f"{ok_count}개 파일 처리를 완료했습니다.")
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
