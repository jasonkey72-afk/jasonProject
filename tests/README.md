# 테스트

실제 브라우저를 띄워 웹 자동화가 정말 동작하는지 확인합니다. (총 32건)

```bat
pip install selenium
python tests\test_webauto.py     :: 요소 탐색 / 요소 선택기 11건
python tests\test_runner.py      :: 시나리오 실행 / 저장 21건
```

기본값은 사내 환경과 같은 **Edge** 입니다. 아래 환경변수로 바꿀 수 있습니다.

| 환경변수 | 설명 |
|---|---|
| `JOBSCN_TEST_BROWSER` | `edge`(기본) / `chrome` |
| `JOBSCN_TEST_HEADLESS` | `1` 이면 화면 없이 실행 |
| `JOBSCN_TEST_ATTACH` | `127.0.0.1:9222` — 이미 실행 중인 브라우저에 연결 |
| `JOBSCN_TEST_DRIVER` | 드라이버 실행 파일 경로(자동 탐지가 안 될 때만) |

`tests/pages/portal.html` 이 사내 포털을 흉내 낸 시험용 화면입니다.
표 안의 입력창, 글자만 있는 버튼, iframe 안의 결재 화면처럼
**실제로 자동화가 자주 실패하는 구조**를 일부러 담아 두었습니다.

새 기능을 추가하면 이 두 파일에 검증을 함께 넣어 주세요.
