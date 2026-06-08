# Schedule Helper

Python으로 만든 집중형 데스크톱 도구입니다. 오늘 할 일과 일정을 가볍게 정리하고, 특정 화면에 머무르는 집중 시간을 뽀모도로 방식으로 기록하며, 빠른 메모를 작성 시각과 함께 저장합니다.

## 실행

```powershell
.\.venv\Scripts\python.exe -m app.main
```

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 패키징

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

성공하면 실행 파일은 `dist\ScheduleHelper\ScheduleHelper.exe`에 생성됩니다.

## 주요 기능

- Focus Desk 중심 화면
- 뽀모도로 목표 시간 설정
- 시작, 일시정지, 재개, 완료
- 현재 열린 프로그램 목록 감지
- 지정한 프로그램에 머문 집중 시간과 이탈 시간 기록
- 오늘 할 일과 오늘 일정 빠른 추가
- 작성 시각이 저장되는 빠른 메모
- 작은 창에서 남은 시간과 집중 상태를 보여주는 위젯 모드
- SQLite 로컬 저장

## 집중 세션

화면 상단의 Focus Desk에서 집중할 일, 집중 대상 화면, 목표 시간을 정하고 `시작`을 누릅니다. 대상 화면을 지정하면 앱은 Windows foreground window를 확인해 해당 프로그램이 맨 앞에 있을 때만 집중 시간으로 계산합니다. 다른 프로그램으로 벗어나거나 자리 비움 기준을 넘기면 이탈 시간으로 기록됩니다.

## 빠른 메모

빠른 메모 칸에 내용을 입력하고 `Ctrl+Enter`를 누르면 저장됩니다. 메모에는 작성 시각이 자동 기록되고, 진행 중인 집중 세션이 있으면 그 세션과 연결됩니다.

## 데이터 위치

기본 데이터베이스는 아래 위치에 생성됩니다.

```text
%LOCALAPPDATA%\ScheduleHelper\schedule_helper.sqlite3
```

테스트나 개발 중 다른 데이터베이스를 쓰려면 `SCHEDULE_HELPER_DB` 환경 변수를 지정할 수 있습니다.

