# AI Studio — 업무 자동화 통합 도구

여러 개로 흩어져 있던 변환 프로그램(MP4 → GIF, XLSX → PDF, PPTX → PDF)과
새로 만든 **파일 & 폴더 이름 목록** 기능을 **하나의 창**에서 실행할 수 있게 통합한
Windows 데스크톱 프로그램입니다.

```
python ai_studio.py        (개발용 실행)
dist\AI_Studio.exe         (배포용 실행파일)
```

## 화면 구성

좌측 내비게이션에서 기능을 고르면 오른쪽 화면이 바뀝니다. 어떤 기능을 쓰든
`파일 추가 → 옵션 선택 → 저장 위치 → 실행` 흐름이 동일합니다.

| 메뉴 | 하는 일 |
|---|---|
| **홈** | 기능 바로가기 + 이 PC 의 실행 환경(Excel / PowerPoint / ffmpeg) 점검 |
| **MP4 → GIF** | 동영상을 팔레트 최적화 방식으로 변환해 선명하고 가벼운 GIF 생성 |
| **XLSX → PDF** | Excel 파일을 서식·표·한글 그대로 PDF 로 일괄 변환 |
| **PPTX → PDF** | 슬라이드 / 유인물 / 노트 형태를 골라 PDF 로 일괄 변환 |
| **이름 목록** | 폴더 안의 파일·폴더 이름을 수집해 CSV·텍스트·트리·마크다운으로 저장 |

### 디자인

- 딥네이비 다크 테마 + 보라→시안 그라디언트 포인트
- 둥근 모서리 버튼, 토글 스위치, 세그먼트 컨트롤, 그라디언트 진행바를
  tkinter Canvas 로 직접 그려 구현 (추가 UI 라이브러리 설치 불필요)
- 모든 변환은 백그라운드 스레드에서 돌아가므로 작업 중에도 창이 멈추지 않고,
  **중지** 버튼으로 언제든 취소할 수 있습니다.

## 기능별 상세

### 1. MP4 → GIF

- 지원 입력: mp4, mov, avi, mkv, wmv, webm, m4v, mpg, flv
- 옵션: 초당 프레임, 가로 폭(0 = 원본), 색상 수, 디더링, 무한 반복,
  구간 자르기(`0:05 ~ 0:12`), 고품질 팔레트(2-pass) 사용 여부
- 프리셋 버튼(메신저 공유 / 표준 / 고화질)으로 한 번에 설정 가능
- 파일별 변환 진행률이 % 로 표시됩니다.

> **ffmpeg 필요**: `pip install imageio-ffmpeg` 로 설치하면 자동으로 인식합니다.
> 또는 `ffmpeg.exe` 를 프로그램(exe)과 같은 폴더, `ffmpeg\`, `bin\` 하위 폴더에
> 두거나 시스템 PATH 에 등록해도 됩니다. `build.bat` 으로 빌드하면 ffmpeg 가
> exe 안에 함께 포함됩니다.

### 2. XLSX → PDF

- 지원 입력: xlsx, xlsm, xls, xlsb, csv
- 설치된 Microsoft Excel 로 "인쇄하듯" 변환하므로 셀 서식·병합·표·한글이
  깨지지 않습니다.
- 옵션: 한 페이지 폭에 맞추기(열 잘림 방지), 표준/최소 화질
- **원본 보호**: 읽기 전용으로 열고 저장하지 않은 채 닫으므로 원본은 변경되지 않습니다.

### 3. PPTX → PDF

- 지원 입력: pptx, pptm, ppt, ppsx, pps
- 옵션: 페이지 구성(슬라이드 / 유인물 2·3·6 / 노트), 숨겨진 슬라이드 포함,
  인쇄 품질
- 원본은 읽기 전용으로만 열립니다.

### 4. 파일 & 폴더 이름 목록 (신규)

- 대상 폴더를 고르면 그 안의 파일·폴더 **이름**을 표로 정리합니다.
- 수집 옵션: 파일/폴더 포함 여부, 하위 폴더 검색, 검색 깊이, 숨김 항목,
  확장자 필터(`xlsx, pdf, mp4`), 이름 포함 검색, 정렬 기준
- 결과 미리보기(번호·이름·종류·확장자·크기·수정일시·상대 경로)
- 저장 형식: **CSV(엑셀)**, 텍스트 목록, 텍스트 트리, 마크다운 표
  - CSV 는 UTF-8 BOM 으로 저장해 엑셀에서 한글이 깨지지 않습니다.
- **클립보드로 복사**를 누르면 탭 구분 텍스트가 복사되어 엑셀에 바로 붙여넣을 수 있습니다.

## 설치 및 실행

### 배포받은 분 (부서원)

`AI_Studio.exe` 를 더블클릭하면 끝입니다. Python 설치가 필요 없습니다.
(Excel / PowerPoint 변환 기능만 해당 Office 프로그램이 설치되어 있어야 합니다.)

### 담당자 — exe 만들기 (1회)

Windows PC + Python 3.9 이상 환경에서:

```bat
build.bat
```

완료되면 `dist\AI_Studio.exe` 가 만들어집니다. 이 파일 하나만 배포하면 됩니다.

> 리눅스/맥에서는 Windows용 exe 를 만들 수 없으므로 반드시 Windows PC 에서
> `build.bat` 을 실행해 주세요.

### 개발용 실행

```bat
pip install -r requirements.txt
python ai_studio.py
```

Windows 가 아닌 환경에서도 창은 뜨며, MP4 → GIF 와 이름 목록 기능은 그대로
동작합니다. Excel / PowerPoint 변환은 Office COM 자동화를 쓰기 때문에
Windows 에서만 실행됩니다(화면에 안내가 표시됩니다).

### 테스트

```bat
python -m unittest discover -s tests -v
```

UI 없이 변환·수집 로직만 검증하므로 어떤 OS 에서도 실행할 수 있습니다.

## 폴더 구조

```
ai_studio.py                  통합 프로그램 실행 파일
aistudio/
  app.py                      메인 윈도우 · 사이드바 내비게이션 · 환경 점검
  theme.py                    색상 / 폰트 / ttk 다크 테마
  widgets.py                  버튼·스위치·세그먼트·진행바 등 커스텀 위젯
  runner.py                   백그라운드 작업 실행 + 진행 상황 전달
  engines/                    실제 변환 로직 (UI 와 분리 → 단독 테스트 가능)
    video_gif.py  excel_pdf.py  ppt_pdf.py  namelist.py  common.py
  pages/                      화면별 구성
    home_page.py  video_gif_page.py  excel_pdf_page.py
    ppt_pdf_page.py  namelist_page.py  converter.py  base.py
tests/test_engines.py         엔진 단위 테스트
excel_to_pdf_converter.py     (예전 버전) Excel 전용 단독 프로그램
```

## 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| "Microsoft Excel 을 찾을 수 없습니다" | 해당 PC 에 Excel 미설치. 설치 후 다시 실행 |
| "Microsoft PowerPoint 를 찾을 수 없습니다" | 해당 PC 에 PowerPoint 미설치 |
| "ffmpeg 를 찾을 수 없습니다" | `pip install imageio-ffmpeg` 또는 ffmpeg.exe 를 exe 와 같은 폴더에 배치 |
| 특정 Office 파일만 실패 | 암호 보호 파일이거나 다른 프로그램에서 열려 있는 경우. 파일을 닫고 재시도 |
| GIF 용량이 너무 큼 | 가로 폭·초당 프레임·색상 수를 줄이거나 '메신저 공유' 프리셋 사용 |
| 목록 CSV 의 한글이 깨짐 | 엑셀에서 열 때 UTF-8 로 열기. (기본 저장은 BOM 포함이라 대부분 정상) |
