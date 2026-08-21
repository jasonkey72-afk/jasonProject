"""
exe 빌드 스크립트
==================
build_splitter.bat 이 이 파일을 실행합니다.

배치 파일(.bat)은 cmd.exe 가 한글(UTF-8)과 줄바꿈에 매우 민감해서
조금만 어긋나도 "내부 또는 외부 명령이 아닙니다" 오류가 납니다.
그래서 배치 파일에는 영문 몇 줄만 두고, 실제 빌드 작업과 한글 안내는
모두 이 파이썬 파일에서 처리합니다.
(파이썬은 인코딩 문제 없이 한글을 출력합니다)

직접 실행할 수도 있습니다:
    python build_exe.py              실행파일 만들기
    python build_exe.py splitter     (같은 동작 — 배치 파일이 이렇게 부른다)
    python build_exe.py --dry-run    실제 빌드 없이 계획만 출력
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 출력이 파일로 넘어가도 한글 때문에 죽지 않도록
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 9)


@dataclass
class Target:
    key: str
    title: str
    script: str
    # PyInstaller 에 넘기는 이름은 반드시 영문만 사용한다.
    # (한글을 넘기면 환경에 따라 깨지므로, 빌드 후 파이썬이 한글 이름으로 바꾼다)
    build_name: str
    final_name: str
    packages: list = field(default_factory=list)
    optional_packages: list = field(default_factory=list)
    extra_args: list = field(default_factory=list)
    windows_only: bool = False
    note: str = ""


TARGETS = {
    "splitter": Target(
        key="splitter",
        title="Office 파일 분할기",
        script="office_file_splitter.py",
        build_name="OfficeFileSplitter",
        final_name="Office_파일_분할기.exe",
        packages=["openpyxl", "python-docx", "python-pptx", "pypdf"],
        optional_packages=["tkinterdnd2"],
        extra_args=[
            "--collect-data", "docx",
            "--collect-data", "pptx",
            "--collect-data", "openpyxl",
        ],
        note="받는 분의 PC에 Python 도, Microsoft Office 도 필요 없습니다.",
    ),
}


# ---------------------------------------------------------------------------
# 화면 출력
# ---------------------------------------------------------------------------

def line(char="─", width=64):
    print(char * width)


def banner(text):
    print()
    line()
    print(f"  {text}")
    line()


def step(n, total, text):
    print(f"\n[{n}/{total}] {text}")


def ok(text):
    print(f"      OK  {text}")


def fail(text):
    print(f"      !!  {text}")


def human_size(num_bytes):
    num = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024 or unit == "GB":
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}GB"


# ---------------------------------------------------------------------------
# 준비 확인
# ---------------------------------------------------------------------------

def check_python():
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 이상이 필요합니다. "
             f"(현재 {platform.python_version()})")
        print("      https://www.python.org/downloads/ 에서 최신 버전을 설치해 주세요.")
        return False
    ok(f"Python {platform.python_version()} ({sys.executable})")
    return True


def run(cmd, quiet=False):
    """명령을 실행하고 성공 여부와 출력을 돌려준다."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace",
        )
    except FileNotFoundError as e:
        return False, str(e)
    if proc.returncode != 0 and not quiet:
        tail = "\n".join(proc.stdout.strip().splitlines()[-15:])
        print(tail)
    return proc.returncode == 0, proc.stdout


# 패키지 이름과 실제로 import 하는 이름이 다른 경우
MODULE_OF = {
    "python-docx": "docx",
    "python-pptx": "pptx",
    "pyinstaller": "PyInstaller",
}


def module_of(package):
    return MODULE_OF.get(package, package.replace("-", "_"))


def module_available(module_name):
    success, _ = run([sys.executable, "-c", f"import {module_name}"], quiet=True)
    return success


def ensure_packages(packages, required=True):
    """
    필요한 패키지를 갖춘다.
    이미 있으면 설치하지 않고, 설치에 실패해도 이미 쓸 수 있으면 그대로 진행한다.
    (pypi 접속이 막힌 사내망 PC에서도 미리 설치되어 있으면 빌드가 된다)
    """
    if not packages:
        return True

    missing = [p for p in packages if not module_available(module_of(p))]
    if not missing:
        ok("이미 설치되어 있습니다: " + ", ".join(packages))
        return True

    # sys.executable 을 쓰므로 지금 실행 중인 파이썬에 정확히 설치된다
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + missing
    success, _ = run(cmd, quiet=not required)
    if success:
        ok("설치 완료: " + ", ".join(missing))
        return True

    still_missing = [p for p in missing if not module_available(module_of(p))]
    if not still_missing:
        ok("설치는 건너뛰었지만 이미 사용할 수 있습니다: " + ", ".join(missing))
        return True

    if required:
        fail("설치 실패: " + ", ".join(still_missing))
        print("      인터넷 연결 또는 사내 프록시 설정을 확인해 주세요.")
        print("      사내망이라면 아래처럼 다시 시도해 보세요:")
        print(f"      {Path(sys.executable).name} -m pip install "
              f"--trusted-host pypi.org --trusted-host files.pythonhosted.org "
              + " ".join(still_missing))
    else:
        fail("설치하지 못했습니다 (없어도 프로그램은 동작합니다): " + ", ".join(still_missing))
    return False


# ---------------------------------------------------------------------------
# 빌드
# ---------------------------------------------------------------------------

def build(target: Target, dry_run=False, skip_install=False) -> bool:
    banner(f"{target.title}  실행파일 만들기")

    if target.windows_only and sys.platform != "win32" and not dry_run:
        fail(f"{target.title} 는 Windows 에서만 빌드할 수 있습니다. (현재: {sys.platform})")
        return False

    script = ROOT / target.script
    if not script.exists():
        fail(f"{target.script} 파일을 찾을 수 없습니다. 압축을 푼 폴더 전체가 필요합니다.")
        return False

    total = 4
    step(1, total, "준비 상태를 확인합니다")
    if not check_python():
        return False
    ok(f"소스 파일 확인: {target.script}")

    step(2, total, "필요한 패키지를 설치합니다")
    if skip_install or dry_run:
        ok("건너뜀 (--skip-install)")
    else:
        if not ensure_packages(target.packages, required=True):
            return False
        if not ensure_packages(["pyinstaller"], required=True):
            return False

    extra = list(target.extra_args)
    if target.optional_packages:
        step(3, total, "선택 기능을 확인합니다 (없어도 프로그램은 동작합니다)")
        for name in target.optional_packages:
            if not (skip_install or dry_run):
                ensure_packages([name], required=False)
            module = module_of(name)
            if dry_run or module_available(module):
                extra += ["--collect-all", module]
                ok(f"{name} 포함 — 드래그 앤 드롭을 쓸 수 있습니다")
            else:
                fail(f"{name} 없이 빌드합니다 — 파일은 클릭해서 선택하면 됩니다")
    else:
        step(3, total, "선택 기능 없음")

    step(4, total, "실행파일을 만듭니다 (몇 분 걸릴 수 있습니다)")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed",
        "--name", target.build_name,          # 영문 이름으로 빌드 (인코딩 사고 방지)
        "--distpath", "dist",
        "--workpath", "build",
        "--specpath", "build",
    ] + extra + [target.script]

    print("      " + " ".join(cmd[1:]))
    if dry_run:
        ok("--dry-run 이므로 실제로 빌드하지는 않았습니다.")
        return True

    success, _ = run(cmd)
    if not success:
        fail("빌드에 실패했습니다. 위의 메시지를 확인해 주세요.")
        return False

    built = ROOT / "dist" / (target.build_name + (".exe" if sys.platform == "win32" else ""))
    if not built.exists():
        fail(f"결과 파일을 찾을 수 없습니다: {built}")
        return False

    # 영문 이름으로 만든 뒤 한글 이름으로 바꾼다 (배치 파일에 한글을 넣지 않기 위함)
    final_name = target.final_name if sys.platform == "win32" else target.final_name.replace(".exe", "")
    final = built.with_name(final_name)
    try:
        if final.exists():
            final.unlink()
        built.rename(final)
    except OSError:
        # 이름 변경이 막히면(사용 중 등) 영문 이름 그대로 둔다
        final = built
        fail(f"이름을 바꾸지 못해 영문 이름 그대로 둡니다: {built.name}")

    ok(f"만들어졌습니다: {final}  ({human_size(final.stat().st_size)})")
    return True


def summary(results):
    banner("빌드 결과")
    for title, success, path in results:
        mark = "완료" if success else "실패"
        print(f"  [{mark}] {title}")
        if success and path:
            print(f"         {path}")
    if any(s for _, s, _ in results):
        print()
        print("  이제 dist 폴더 안의 파일 하나만 부서원들에게 전달하면 됩니다.")
        print("  (받는 분은 Python 을 설치할 필요가 없습니다)")
    print()


def main():
    parser = argparse.ArgumentParser(description="exe 빌드")
    parser.add_argument("target", nargs="?", default="splitter",
                        choices=["splitter"])
    parser.add_argument("--dry-run", action="store_true",
                        help="실제로 빌드하지 않고 실행할 명령만 보여 준다")
    parser.add_argument("--skip-install", action="store_true",
                        help="패키지 설치 단계를 건너뛴다")
    args = parser.parse_args()

    keys = [args.target]
    results = []
    for key in keys:
        target = TARGETS[key]
        success = build(target, dry_run=args.dry_run, skip_install=args.skip_install)
        path = ""
        if success and not args.dry_run:
            for name in (target.final_name, target.final_name.replace(".exe", ""),
                         target.build_name + ".exe", target.build_name):
                candidate = ROOT / "dist" / name
                if candidate.exists():
                    path = str(candidate)
                    break
        results.append((target.title, success, path))

    summary(results)
    return 0 if all(s for _, s, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
