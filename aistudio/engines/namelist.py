"""폴더 안의 파일 & 폴더 이름 목록을 뽑아내는 엔진.

지정한 폴더를 훑어 이름/종류/확장자/경로/크기/수정일시를 표로 정리하고,
CSV(엑셀) · 텍스트 · 트리 · 마크다운 형식으로 저장할 수 있다.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from .common import human_size

COLUMNS = [
    ("no", "번호"),
    ("name", "이름"),
    ("kind", "종류"),
    ("ext", "확장자"),
    ("parent", "상위 폴더"),
    ("relpath", "상대 경로"),
    ("size", "크기"),
    ("size_bytes", "크기(바이트)"),
    ("mtime", "수정일시"),
    ("depth", "깊이"),
]

BASE_COLUMNS = ["no", "name", "kind"]

SORT_OPTIONS = [
    ("name", "이름순"),
    ("kind", "폴더 먼저"),
    ("size", "크기순 (큰 것부터)"),
    ("mtime", "수정일순 (최근부터)"),
    ("path", "경로순"),
]

EXPORT_FORMATS = [
    ("csv", "CSV (엑셀에서 열기)"),
    ("txt", "텍스트 목록"),
    ("tree", "텍스트 트리"),
    ("md", "마크다운 표"),
]

EXPORT_EXT = {"csv": ".csv", "txt": ".txt", "tree": ".txt", "md": ".md"}


def _is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            import stat

            return bool(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            return False
    return False


def _parse_ext_filter(text: str) -> set[str]:
    """'jpg, .png; mp4' → {'.jpg', '.png', '.mp4'}"""
    result = set()
    for token in (text or "").replace(";", ",").replace(" ", ",").split(","):
        token = token.strip().lower()
        if not token:
            continue
        result.add(token if token.startswith(".") else "." + token)
    return result


def _entry_row(path: Path, root: Path, is_dir: bool) -> dict:
    try:
        stat_result = path.stat()
        size_bytes = 0 if is_dir else stat_result.st_size
        mtime = datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        size_bytes, mtime = 0, ""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    return {
        "name": path.name,
        "kind": "폴더" if is_dir else "파일",
        "ext": "" if is_dir else path.suffix.lower(),
        "parent": str(path.parent),
        "relpath": str(rel),
        "size": "-" if is_dir else human_size(size_bytes),
        "size_bytes": size_bytes,
        "mtime": mtime,
        "depth": len(rel.parts) - 1,
        "path": str(path),
        "is_dir": is_dir,
    }


def scan(params: dict, em) -> dict:
    """params: root, recursive, max_depth, include_files, include_folders,
    include_hidden, ext_filter, name_contains, sort_by"""
    root_text = (params.get("root") or "").strip()
    if not root_text:
        raise ValueError("목록을 만들 폴더를 먼저 선택해 주세요.")
    root = Path(root_text)
    if not root.is_dir():
        raise ValueError(f"폴더를 찾을 수 없습니다: {root}")

    include_files = params.get("include_files", True)
    include_folders = params.get("include_folders", True)
    include_hidden = params.get("include_hidden", False)
    recursive = params.get("recursive", True)
    max_depth = int(params.get("max_depth", 0) or 0)
    ext_filter = _parse_ext_filter(params.get("ext_filter", ""))
    keyword = (params.get("name_contains") or "").strip().lower()

    em.pulse(True)
    em.status(f"'{root.name}' 폴더를 읽는 중...")
    em.log(f"대상 폴더: {root}", "head")

    rows: list[dict] = []
    scanned = 0
    for current_root, dir_names, file_names in os.walk(root):
        em.raise_if_cancelled()
        current = Path(current_root)
        depth = len(current.relative_to(root).parts)

        if not include_hidden:
            dir_names[:] = [d for d in dir_names if not _is_hidden(current / d)]
        dir_names.sort(key=str.lower)
        file_names.sort(key=str.lower)

        if include_folders:
            for name in dir_names:
                rows.append(_entry_row(current / name, root, True))
        if include_files:
            for name in file_names:
                path = current / name
                if not include_hidden and _is_hidden(path):
                    continue
                if ext_filter and path.suffix.lower() not in ext_filter:
                    continue
                rows.append(_entry_row(path, root, False))

        scanned += len(dir_names) + len(file_names)
        if scanned and scanned % 500 == 0:
            em.status(f"{scanned:,}개 항목 확인 중...")

        if not recursive:
            dir_names[:] = []
        elif max_depth and depth + 1 >= max_depth:
            dir_names[:] = []

    if keyword:
        rows = [r for r in rows if keyword in r["name"].lower()]

    sort_by = params.get("sort_by", "kind")
    if sort_by == "name":
        rows.sort(key=lambda r: r["name"].lower())
    elif sort_by == "kind":
        rows.sort(key=lambda r: (r["relpath"].lower().count(os.sep), not r["is_dir"], r["name"].lower()))
    elif sort_by == "size":
        rows.sort(key=lambda r: r["size_bytes"], reverse=True)
    elif sort_by == "mtime":
        rows.sort(key=lambda r: r["mtime"], reverse=True)
    else:
        rows.sort(key=lambda r: r["relpath"].lower())

    for i, row in enumerate(rows, start=1):
        row["no"] = i

    folders = sum(1 for r in rows if r["is_dir"])
    files = len(rows) - folders
    total_bytes = sum(r["size_bytes"] for r in rows if not r["is_dir"])

    em.pulse(False)
    em.progress(1, 1)
    em.log(f"폴더 {folders:,}개 · 파일 {files:,}개 (합계 {human_size(total_bytes)})", "ok")
    em.status(f"완료: {len(rows):,}개 항목")

    return {
        "ok": len(rows), "fail": 0, "rows": rows, "root": str(root),
        "folders": folders, "files": files, "total_bytes": total_bytes,
    }


# ------------------------------------------------------------------ 내보내기
def selected_columns(options: dict) -> list[tuple[str, str]]:
    """체크박스 상태에 따라 내보낼 열 구성을 정한다."""
    keys = list(BASE_COLUMNS)
    if options.get("ext", True):
        keys.append("ext")
    if options.get("relpath", True):
        keys.append("relpath")
    if options.get("parent", False):
        keys.append("parent")
    if options.get("size", True):
        keys += ["size", "size_bytes"]
    if options.get("mtime", True):
        keys.append("mtime")
    labels = dict(COLUMNS)
    return [(key, labels[key]) for key in keys]


def build_tree_text(rows: list[dict], root: str) -> str:
    """상대 경로를 이용해 트리 모양 텍스트를 만든다."""
    lines = [str(root)]
    ordered = sorted(rows, key=lambda r: r["relpath"].lower())
    for row in ordered:
        parts = Path(row["relpath"]).parts
        indent = "    " * (len(parts) - 1)
        # 폴더는 이름 끝에 / 를 붙여 파일과 구분한다 (모든 편집기에서 깨지지 않도록 기호만 사용)
        name = row["name"] + ("/" if row["is_dir"] else "")
        lines.append(f"{indent}└── {name}")
    return "\n".join(lines)


def build_text(rows: list[dict], columns) -> str:
    header = " | ".join(label for _key, label in columns)
    lines = [header, "-" * max(len(header), 20)]
    for row in rows:
        lines.append(" | ".join(str(row.get(key, "")) for key, _label in columns))
    return "\n".join(lines)


def build_markdown(rows: list[dict], columns) -> str:
    head = "| " + " | ".join(label for _key, label in columns) + " |"
    sep = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [head, sep]
    for row in rows:
        cells = [str(row.get(key, "")).replace("|", "\\|") for key, _label in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def export(rows: list[dict], root: str, fmt: str, columns, dst: Path) -> Path:
    """선택한 형식으로 파일에 저장하고 저장 경로를 반환한다."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        # utf-8-sig 로 저장해야 엑셀에서 한글이 깨지지 않는다
        with open(dst, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([label for _key, label in columns])
            for row in rows:
                writer.writerow([row.get(key, "") for key, _label in columns])
    else:
        if fmt == "tree":
            content = build_tree_text(rows, root)
        elif fmt == "md":
            content = build_markdown(rows, columns)
        else:
            content = build_text(rows, columns)
        dst.write_text(content + "\n", encoding="utf-8")
    return dst


def clipboard_text(rows: list[dict], columns) -> str:
    """엑셀에 바로 붙여넣을 수 있도록 탭으로 구분한 텍스트."""
    lines = ["\t".join(label for _key, label in columns)]
    for row in rows:
        lines.append("\t".join(str(row.get(key, "")) for key, _label in columns))
    return "\n".join(lines)
