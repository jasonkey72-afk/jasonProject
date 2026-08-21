"""
배치 파일(.bat) 안전성 검사
============================
cmd.exe 는 .bat 파일을 UTF-8 이 아니라 OEM 코드페이지(한국어 Windows 는 949)로 읽는다.
그래서 아래 세 가지가 있으면 줄이 깨져서
"내부 또는 외부 명령, 실행할 수 있는 프로그램, 또는 배치 파일이 아닙니다" 오류가 난다.

  1) 한글 등 ASCII 가 아닌 글자
  2) LF 줄바꿈 (리눅스/맥에서 만든 파일)  ← 반드시 CRLF 여야 한다
  3) 줄 끝의 ^ (줄 연속) — 위 두 가지와 겹치면 확실히 깨진다

이 검사는 위 문제가 다시 들어오는 것을 막는다.
실행:  python tests/test_batch_files.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"    OK  {message}")


def check_bat(path: Path):
    print(f"\n[{path.name}]")
    data = path.read_bytes()

    non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
    if non_ascii:
        pos = non_ascii[0][0]
        near = data[max(0, pos - 40):pos + 10].decode("utf-8", "replace")
        raise AssertionError(
            f"{path.name}: ASCII 가 아닌 글자가 {len(non_ascii)}바이트 있습니다. "
            f"cmd.exe 가 깨뜨립니다.\n         위치 근처: ...{near}\n"
            f"         → 한글 메시지는 build_exe.py 로 옮기세요."
        )
    check(True, "ASCII 문자만 사용한다 (한글 없음)")

    check(not data.startswith(b"\xef\xbb\xbf"),
          "UTF-8 BOM 이 없다 (BOM 이 있으면 첫 줄이 명령으로 인식되지 않는다)")

    lone_lf = data.replace(b"\r\n", b"").count(b"\n")
    check(lone_lf == 0,
          f"모든 줄이 CRLF 로 끝난다 (LF 단독 {lone_lf}개)")
    check(data.count(b"\r\n") > 0, "줄바꿈이 실제로 들어 있다")

    text = data.decode("ascii")
    caret_lines = [i + 1 for i, ln in enumerate(text.split("\r\n")) if ln.rstrip().endswith("^")]
    check(not caret_lines,
          f"줄 끝 ^ (줄 연속)을 쓰지 않는다 {caret_lines or ''}")

    check(text.endswith("\r\n"), "파일이 줄바꿈으로 끝난다")
    check('cd /d "%~dp0"' in text,
          "실행 위치를 배치 파일 폴더로 옮긴다 (어디서 실행해도 동작)")
    check("pause" in text, "창이 바로 닫히지 않도록 pause 가 있다")

    # 배치 파일이 부르는 파일이 실제로 있는지
    for referenced in ("build_exe.py", "docs\\help_python_ko.txt"):
        if referenced in text:
            target = ROOT / referenced.replace("\\", "/")
            check(target.exists(), f"참조 파일이 실제로 있다: {referenced}")


def check_help_text(path: Path):
    print(f"\n[{path.name}]")
    data = path.read_bytes()
    check(not data.startswith(b"\xef\xbb\xbf"),
          "BOM 이 없다 (type 으로 출력할 때 깨지지 않도록)")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise AssertionError(f"UTF-8 로 읽을 수 없습니다: {e}")
    check(True, "UTF-8 로 정상적으로 읽힌다")
    lone_lf = data.replace(b"\r\n", b"").count(b"\n")
    check(lone_lf == 0, f"CRLF 줄바꿈이다 (메모장에서 한 줄로 붙지 않음) (LF 단독 {lone_lf}개)")


def check_gitattributes():
    print("\n[.gitattributes]")
    path = ROOT / ".gitattributes"
    check(path.exists(), "파일이 있다 (git 이 .bat 을 LF 로 바꾸지 못하게)")
    text = path.read_text(encoding="utf-8")
    check("*.bat text eol=crlf" in text, ".bat 은 항상 CRLF 로 받도록 지정되어 있다")


def main():
    bats = sorted(ROOT.glob("*.bat"))
    if not bats:
        raise AssertionError("검사할 .bat 파일이 없습니다.")
    print(f"검사할 배치 파일 {len(bats)}개: " + ", ".join(b.name for b in bats))
    for bat in bats:
        check_bat(bat)

    help_txt = ROOT / "docs" / "help_python_ko.txt"
    if help_txt.exists():
        check_help_text(help_txt)

    check_gitattributes()
    print("\n배치 파일 검사를 모두 통과했습니다.")


if __name__ == "__main__":
    main()
