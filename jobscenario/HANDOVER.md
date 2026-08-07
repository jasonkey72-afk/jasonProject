# jobScenario 개발 인수인계

다른 환경에서 이어서 개발할 사람을 위한 문서입니다.
사용법은 `README.md`, 테스트는 `tests/README.md` 를 보세요.

## 1. 바로 시작하기

```bat
pip install -r requirements.txt
python jobscenario_main.py          :: 프로그램 실행
python tests\test_webauto.py        :: 동작 확인 (실제 브라우저가 뜹니다)
python tests\test_runner.py
build_jobscenario.bat               :: dist\jobScenario.exe 생성
```

Python 3.9 이상, Edge 또는 Chrome 설치 필요. 외부 라이브러리는 `selenium` 하나뿐이고,
화면은 표준 `tkinter` 로 만들어 별도 UI 라이브러리가 없습니다.

## 2. 구조 한눈에 보기

```
jobscenario_main.py        진입점 (라이브러리 없을 때 안내 메시지까지 처리)
jobscenario/
  webauto/                 ★ 웹 자동화 공용 모듈 (다른 프로젝트에 그대로 복사 가능)
    locator.py               SmartLocator — 요소를 찾아내는 핵심
    picker.py                요소 선택기 — 화면에서 클릭해 선택자 수집
    actions.py               WebActions — 클릭/입력/선택/대기 등 고수준 동작
    driver.py                Edge/Chrome 실행, 전용 프로필, 로컬 드라이버 탐지
  core/
    models.py                Scenario / Step / ACTIONS 목록 / 변수 치환
    storage.py               JSON 저장·불러오기
    runner.py                실행 엔진 (전체 일괄 / 단계별) + Session
    programs.py              사내 프로그램 실행
  ui/
    app.py                   메인 화면
    step_dialog.py           단계 등록 창
    theme.py                 색상·버튼·카드 (색만 바꾸면 전체 분위기가 바뀜)
```

의존 방향은 **ui → core → webauto** 한 방향입니다. `webauto` 는 jobScenario 를 전혀 모르므로
따로 떼어 다른 프로젝트에 쓸 수 있습니다.

## 3. 반드시 알아야 할 설계 결정

### (1) 요소를 찾는 순서 — 함부로 바꾸지 말 것

`locator.py` 의 `_search_all_frames()` 는 전략을 **신뢰도로 두 단계로 나눠** 시도합니다.

1. **강한 전략**(`STRONG_MIN=50` 이상: id, data-*, name, aria, placeholder, 라벨, 글자, id 포함 CSS)
   → 현재 프레임 → 등록된 프레임 → 최상위 → **모든 iframe** 순으로 탐색
2. **약한 전략**(절대 XPath, id 없는 경로형 CSS)
   → **등록될 때의 프레임 안에서만** 탐색

이 순서를 합치면 iframe 안 요소의 절대 경로가 최상위 화면의 **엉뚱한 버튼**을 먼저 잡습니다.
(실제로 겪었고 `tests/test_webauto.py` 의 "iframe 안 요소 선택 + 프레임 경로 복원" 이 이를 막습니다.)

### (2) 선택자는 하나가 아니라 여러 개를 저장한다

`picker.build_target()` 은 요소 하나에서 id / data-* / name / aria-label / placeholder /
라벨 글자 / 보이는 글자 / CSS 경로 / 절대 XPath 를 **모두** 뽑아 `Target` 에 담습니다.
화면이 조금 바뀌어 한 전략이 깨져도 나머지로 찾아가기 위한 것이므로,
"정리한다고" 선택자 개수를 줄이면 안정성이 떨어집니다.

### (3) 브라우저는 Session 이 들고 있는다

`runner.Session` 이 드라이버를 보관하므로 **단계별 실행 사이에도 브라우저가 유지**됩니다.
"3단계에서 실패 → 고친 뒤 3단계만 다시 실행" 이 가능한 이유입니다.
`Runner` 는 매 실행마다 새로 만들어도 되지만 `Session` 은 프로그램이 살아 있는 동안 하나만 씁니다.

### (4) UI 스레드 규칙

실행은 백그라운드 스레드에서 돌고, 화면 갱신은 `queue` 에 넣어 `_drain_events()` 가
**UI 스레드에서만** 처리합니다. 작업 스레드에서 위젯을 직접 만지면 안 됩니다.
사용자 입력이 필요할 때는 `_ask_from_thread()` 처럼 `after(0, ...)` 로 UI 스레드에 넘기세요.

## 4. 기능 추가하는 법

### 새 동작(action) 추가 — 3곳만 고치면 됩니다

1. `core/models.py` 의 `ACTIONS` 에 항목 추가
   ```python
   "print_page": {"label": "화면 인쇄", "group": "웹",
                  "need_target": False, "value_label": ""},
   ```
2. 실제 동작이 웹이면 `webauto/actions.py` 에 메서드 추가
3. `core/runner.py` 의 `_execute()`(웹) 또는 `_execute_local()`(프로그램)에 분기 한 줄 추가

화면(콤보박스, 입력칸 활성화, 찾아보기 버튼)은 `ACTIONS` 를 보고 자동으로 맞춰지므로
UI 는 손대지 않아도 됩니다.

### 새 탐색 전략 추가

`locator.py` 의 `STRATEGY_SCORE` 에 점수를 정하고 `strategies_for_*()` 또는
`picker.build_target()` 에서 만들어 넣으면 됩니다. 점수가 `STRONG_MIN` 이상이면
모든 프레임에서 시도되므로, **다른 화면에도 우연히 맞을 수 있는 전략은 50 미만**으로 두세요.

## 5. 아직 없는 것 (다음 개발 후보)

| 항목 | 메모 |
|---|---|
| 예약 실행 | "매일 아침 8시 자동 실행" — Windows 작업 스케줄러에 등록하는 기능 |
| 조건 분기 / 반복 | 지금은 단계를 위에서 아래로 한 번만 실행. "값이 0이면 건너뛰기" 같은 분기 없음 |
| 시나리오 이어붙이기 | 다른 시나리오를 한 단계로 불러 실행 |
| 데스크톱 프로그램 조작 | 지금은 실행/파일 열기까지만. 창 안의 버튼 클릭은 `pywinauto` 등이 필요 |
| 사용자 조작 기록(레코더) | 클릭·입력을 통째로 녹화해 단계를 자동 생성 |
| 결과 후처리 | 내려받은 엑셀을 같은 저장소의 Excel→PDF 변환기와 연결 |

## 6. Playwright 검토 결과 (2026-08)

"Selenium 대신/함께 Playwright 를 쓰면 어떤가" 를 검토했고 **당분간 쓰지 않기로** 했습니다.
같은 논의가 반복되지 않도록 근거를 남깁니다.

**Playwright 가 나은 점**
- 드라이버 버전을 맞출 필요가 없다(`channel="msedge"` 로 설치된 Edge 를 CDP 로 직접 조작).
  Edge 가 업데이트될 때마다 드라이버를 다시 배포해야 하는 문제가 사라진다 — 가장 큰 장점.
- Shadow DOM 통과, trace viewer, codegen(레코더)

**그럼에도 쓰지 않는 이유**
1. **스레드 제약**: Playwright 동기 API 는 객체를 만든 스레드에서만 쓸 수 있다.
   지금 브라우저는 ①실행 워커 스레드 ②요소 선택기 스레드 ③UI 스레드(대상 확인) 세 곳에서
   접근한다. Playwright 로 가려면 전담 워커 + 명령 큐 구조로 다시 짜야 하고,
   그 중심에 "단계별 실행 사이 브라우저 유지" 라는 핵심 기능이 걸려 있다.
2. **배포 크기**: 휠이 46MB(Node 드라이버 내장). exe 가 15~20MB → 55~60MB 가 된다.
   PyInstaller 로 Node 드라이버를 묶는 것도 까다로워 "빌드 스크립트 더블클릭이면 끝" 이 깨질 수 있다.
3. **엔진 둘 = 유지보수 둘**: 부서에서 쓰는 도구에 재현 경로가 두 배가 된다.

**대신 한 것** — 이득의 상당 부분을 훨씬 싸게 흡수했다.
- Shadow DOM 탐색 (`locator.py` 의 `BY_DEEP`)
- 실패 시 화면·HTML 자동 저장 (trace viewer 의 실용적 대체)
- 브라우저/드라이버 버전 비교 후 받아야 할 버전까지 안내 (`driver.diagnose`)

**다시 검토해야 할 신호**
- React/Vue 기반 신규 사내 시스템이 늘어 Shadow DOM/동적 렌더링에서 계속 막힐 때
- 드라이버 버전 때문에 분기에 두세 번 이상 재배포해야 할 때

**갈아탈 때 알아둘 것**: `Target` 이 저장하는 선택자가 전부 표준 CSS/XPath 라
Playwright 가 그대로 받는다. 즉 **탐색 로직 재작성이 아니라 어댑터 한 겹**이면 되고,
프레임 순회는 `page.frames`(평평한 목록)로 지금보다 단순해진다.
미리 추상화 계층을 만들어 둘 필요는 없다.

## 7. 자주 막히는 부분

- **드라이버 버전**: 브라우저와 드라이버의 **주 버전이 같아야** 합니다. 사내망에서 자동
  내려받기가 막히면 `msedgedriver.exe` 를 exe 옆에 두세요(`driver.py` 가 자동 인식).
- **exe 빌드는 Windows 에서만**: 리눅스/컨테이너에서는 Windows exe 를 만들 수 없습니다.
- **실패 기록**: 단계가 실패하면 `%LOCALAPPDATA%\jobScenario\failures` 에
  화면·HTML·주소가 자동으로 남습니다. 원인 파악은 여기서 시작하세요.
- **테스트에 브라우저가 필요**: 화면 없이 돌리려면 `JOBSCN_TEST_HEADLESS=1`.
  단, 사내 사이트는 headless 를 막는 경우가 있어 실사용은 화면 있는 실행을 권장합니다.
- **한글 폰트**: UI 는 "맑은 고딕" 기준입니다. 다른 OS 에서는 `ui/theme.py` 의 `FONT` 를 바꾸세요.
