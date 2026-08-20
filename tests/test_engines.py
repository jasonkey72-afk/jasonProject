"""엔진(UI 제외) 동작 확인 테스트.

    python -m unittest discover -s tests -v

tkinter 나 Windows COM 없이도 실행되는 부분만 검증한다.
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aistudio.engines import namelist, video_gif  # noqa: E402
from aistudio.engines.common import human_size, target_path, unique_path  # noqa: E402
from aistudio.runner import Emitter  # noqa: E402


def make_emitter():
    return Emitter(queue.Queue(), threading.Event())


class CommonTest(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(2048), "2.0 KB")
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "보고서.pdf"
            self.assertEqual(unique_path(first), first)
            first.write_text("x", encoding="utf-8")
            self.assertEqual(unique_path(first).name, "보고서 (2).pdf")

    def test_target_path_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "자료.xlsx"
            src.write_text("x", encoding="utf-8")
            same = target_path(src, "same", "", ".pdf", True)
            self.assertEqual(same, src.with_suffix(".pdf"))

            other = Path(tmp) / "out"
            custom = target_path(src, "custom", str(other), ".pdf", True)
            self.assertEqual(custom.parent, other)
            self.assertTrue(other.is_dir())


class VideoGifTest(unittest.TestCase):
    def test_parse_timecode(self):
        self.assertIsNone(video_gif.parse_timecode(""))
        self.assertEqual(video_gif.parse_timecode("12"), 12)
        self.assertEqual(video_gif.parse_timecode("1:05"), 65)
        self.assertEqual(video_gif.parse_timecode("00:01:05.5"), 65.5)
        with self.assertRaises(ValueError):
            video_gif.parse_timecode("어제")

    def test_build_filter_high_quality(self):
        chain = video_gif.build_filter(12, 480, 128, "sierra2_4a", True)
        self.assertIn("fps=12", chain)
        self.assertIn("scale=480:-1:flags=lanczos", chain)
        self.assertIn("palettegen=max_colors=128", chain)
        self.assertIn("paletteuse=dither=sierra2_4a", chain)

    def test_build_filter_fast_and_original_size(self):
        chain = video_gif.build_filter(8, 0, 64, "none", False)
        self.assertEqual(chain, "fps=8")

    def test_end_before_start_rejected(self):
        with self.assertRaises(ValueError):
            video_gif.convert(
                {"files": [__file__], "start": "0:10", "end": "0:02", "out_mode": "same"},
                make_emitter(),
            )


class NameListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "보고서").mkdir()
        (root / "보고서" / "1분기.xlsx").write_text("a", encoding="utf-8")
        (root / "보고서" / "메모.txt").write_text("bb", encoding="utf-8")
        (root / "영상").mkdir()
        (root / "영상" / "소개.mp4").write_text("ccc", encoding="utf-8")
        (root / "읽어보기.md").write_text("dddd", encoding="utf-8")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def _scan(self, **overrides):
        params = {
            "root": str(self.root), "recursive": True, "max_depth": 0,
            "include_files": True, "include_folders": True, "include_hidden": False,
            "ext_filter": "", "name_contains": "", "sort_by": "kind",
        }
        params.update(overrides)
        return namelist.scan(params, make_emitter())

    def test_scan_counts(self):
        result = self._scan()
        self.assertEqual(result["folders"], 2)
        self.assertEqual(result["files"], 4)
        self.assertEqual(result["total_bytes"], 1 + 2 + 3 + 4)
        self.assertEqual([row["no"] for row in result["rows"]], list(range(1, 7)))

    def test_folders_only_and_depth(self):
        result = self._scan(include_files=False)
        self.assertEqual(result["files"], 0)
        self.assertTrue(all(row["is_dir"] for row in result["rows"]))

        shallow = self._scan(recursive=False)
        self.assertEqual({row["name"] for row in shallow["rows"]},
                         {"보고서", "영상", "읽어보기.md"})

    def test_extension_and_keyword_filter(self):
        only_xlsx = self._scan(ext_filter="xlsx, mp4", include_folders=False)
        self.assertEqual({row["name"] for row in only_xlsx["rows"]}, {"1분기.xlsx", "소개.mp4"})

        keyword = self._scan(name_contains="분기")
        self.assertEqual([row["name"] for row in keyword["rows"]], ["1분기.xlsx"])

    def test_missing_folder_raises(self):
        with self.assertRaises(ValueError):
            namelist.scan({"root": str(self.root / "없는폴더")}, make_emitter())

    def test_export_formats(self):
        rows = self._scan()["rows"]
        columns = namelist.selected_columns({"ext": True, "relpath": True, "parent": False,
                                             "size": True, "mtime": True})
        self.assertEqual([key for key, _label in columns],
                         ["no", "name", "kind", "ext", "relpath", "size", "size_bytes", "mtime"])
        for fmt in ("csv", "txt", "tree", "md"):
            dst = Path(self.tmp.name) / f"목록{namelist.EXPORT_EXT[fmt]}"
            saved = namelist.export(rows, str(self.root), fmt, columns, dst)
            content = saved.read_text(encoding="utf-8-sig")
            self.assertIn("1분기.xlsx", content, fmt)
            self.assertTrue(saved.stat().st_size > 0)

        csv_text = (Path(self.tmp.name) / "목록.csv").read_bytes()
        self.assertTrue(csv_text.startswith(b"\xef\xbb\xbf"), "엑셀 호환용 BOM 이 있어야 한다")
        tree_text = (Path(self.tmp.name) / "목록.txt").read_text(encoding="utf-8")
        self.assertIn("보고서/", tree_text)

    def test_clipboard_text_is_tab_separated(self):
        rows = self._scan()["rows"]
        columns = namelist.selected_columns({})
        text = namelist.clipboard_text(rows, columns)
        header = text.splitlines()[0]
        self.assertEqual(header.split("\t")[:3], ["번호", "이름", "종류"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
