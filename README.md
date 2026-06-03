# Schedule Helper

Python으로 만든 데스크톱 일정 도우미입니다. 작업, 고정 일정, 사용 가능 시간대를 입력하면 주간 캘린더에 자동으로 일정을 배치합니다.

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

- 작업 추가, 완료, 삭제
- 고정 일정 추가, 수정, 삭제
- 평일/주말 사용 가능 시간대 설정
- 마감일과 우선순위 기반 자동 배치
- 주간 캘린더 보기
- SQLite 로컬 저장

## 데이터 위치

기본 데이터베이스는 아래 위치에 생성됩니다.

```text
%LOCALAPPDATA%\ScheduleHelper\schedule_helper.sqlite3
```

테스트나 개발 중 다른 데이터베이스를 쓰려면 `SCHEDULE_HELPER_DB` 환경 변수를 지정할 수 있습니다.
