"""
.dxp 파일 내부 구조 진단 도구
==============================
Spotfire_dxp_Excel_변환기가 데이터 테이블을 찾지 못할 때, 원인을 파악하기 위한
진단 도구입니다. 실제 데이터 값(셀 내용)은 전혀 출력하지 않고, 파일 내부 구조
(ZIP 항목 이름, 크기, 처음 몇 바이트의 16진수 값)만 출력합니다.

사용법:
    python diagnose_dxp.py 파일경로.dxp

결과를 파일로 저장하려면:
    python diagnose_dxp.py 파일경로.dxp > 진단결과.txt
"""

import sys
import zipfile
from pathlib import Path

SBDF_MAGIC = b"\xdf\x5b"
ZIP_MAGIC = b"PK\x03\x04"
GZIP_MAGIC = b"\x1f\x8b"
MAX_ENTRIES_SHOWN = 60
SCAN_LIMIT_BYTES = 20 * 1024 * 1024  # 항목 내부에서 SBDF 시그니처를 찾아볼 최대 범위(앞부분)


def _find_signature_offset(data: bytes, sig: bytes):
    idx = data.find(sig)
    return idx if idx >= 0 else None


def diagnose(path: Path):
    print(f"파일: {path}")
    print(f"크기: {path.stat().st_size:,} bytes\n")

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        print("결과: ZIP(zip) 형식이 아닙니다. Spotfire 7.0 이전의 구버전 바이너리 .dxp로 보입니다.")
        with open(path, "rb") as f:
            head = f.read(16)
        print(f"파일 처음 16바이트(hex): {head.hex(' ')}")
        return

    entries = [i for i in zf.infolist() if not i.is_dir()]
    print(f"ZIP 안의 전체 항목 수: {len(entries)}")
    print(f"(크기 상위 {min(MAX_ENTRIES_SHOWN, len(entries))}개 항목만 아래에 표시합니다)\n")

    header = f"{'항목 이름':<66} {'크기(bytes)':>13}  처음8바이트(hex)      항목맨앞SBDF  내부어딘가SBDF(offset)"
    print(header)
    print("-" * len(header))

    sbdf_at_start = 0
    sbdf_inside = 0
    nested_zip = 0
    nested_gzip = 0

    entries_sorted = sorted(entries, key=lambda i: -i.file_size)
    for info in entries_sorted[:MAX_ENTRIES_SHOWN]:
        try:
            with zf.open(info) as f:
                data = f.read(min(info.file_size, SCAN_LIMIT_BYTES))
        except Exception as e:
            print(f"{info.filename:<66} (읽기 실패: {e})")
            continue

        head8 = data[:8]
        starts_sbdf = head8[:2] == SBDF_MAGIC
        inside_offset = None if starts_sbdf else _find_signature_offset(data, SBDF_MAGIC)

        if starts_sbdf:
            sbdf_at_start += 1
        if inside_offset is not None:
            sbdf_inside += 1
        if head8[:4] == ZIP_MAGIC:
            nested_zip += 1
        if head8[:2] == GZIP_MAGIC:
            nested_gzip += 1

        name = info.filename if len(info.filename) <= 66 else info.filename[:63] + "..."
        print(
            f"{name:<66} {info.file_size:>13,}  {head8.hex(' '):<20}  "
            f"{'YES' if starts_sbdf else '-':<12} "
            f"{inside_offset if inside_offset is not None else '-'}"
        )

    print("-" * len(header))
    print(f"\n항목 맨 앞이 SBDF 매직넘버(DF 5B)로 시작하는 항목: {sbdf_at_start}개")
    print(f"항목 내부 어딘가에서 SBDF 매직넘버가 발견된 항목: {sbdf_inside}개 (표시된 상위 항목 기준)")
    print(f"ZIP 시그니처(PK)로 시작하는 항목(중첩 zip 가능성): {nested_zip}개")
    print(f"GZIP 시그니처로 시작하는 항목(추가 압축 가능성): {nested_gzip}개")

    if sbdf_at_start == 0 and sbdf_inside == 0 and nested_zip == 0 and nested_gzip == 0:
        print(
            "\n→ 상위 항목들에서 SBDF/ZIP/GZIP 시그니처를 전혀 찾지 못했습니다. "
            "이 결과를 공유해 주시면 실제 저장 구조를 다시 분석하겠습니다."
        )
    elif nested_zip > 0 or nested_gzip > 0:
        print(
            "\n→ 중첩된 zip/gzip으로 보이는 항목이 있습니다. 데이터가 한 번 더 압축되어 "
            "저장되어 있을 가능성이 있습니다."
        )
    elif sbdf_inside > 0:
        print(
            "\n→ 항목 내부(맨 앞이 아닌 위치)에서 SBDF 시그니처가 발견되었습니다. "
            "각 항목 앞에 별도의 헤더가 붙어 있는 구조로 보입니다."
        )


def main():
    if len(sys.argv) != 2:
        print("사용법: python diagnose_dxp.py 파일경로.dxp")
        sys.exit(1)
    diagnose(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
