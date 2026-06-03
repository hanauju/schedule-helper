# Python Schedule Helper Tool Plan

## 1. Goal

Python으로 일정 작성을 도와주는 데스크톱 도구를 만든다. 사용자는 할 일, 일정 조건, 마감일, 우선순위, 반복 일정, 사용 가능한 시간대를 입력하고, 앱은 충돌이 적고 실행 가능한 일정안을 생성한다. 최종 목표는 실제로 사용할 수 있는 사용자 인터페이스까지 완성하는 것이다.

## 2. Product Scope

### Core Use Cases

- 사용자가 할 일과 일정을 입력한다.
- 각 항목에 예상 소요 시간, 마감일, 우선순위, 카테고리, 고정 여부를 지정한다.
- 앱이 빈 시간대에 작업을 자동 배치한다.
- 사용자가 생성된 일정을 직접 수정한다.
- 일정 데이터를 저장하고 다시 불러온다.
- 하루, 주간, 목록 뷰로 일정을 확인한다.

### Out Of Scope For First Version

- 여러 사용자 간 실시간 공유
- 외부 캘린더 양방향 동기화
- 모바일 앱
- 클라우드 계정 시스템
- 복잡한 AI 기반 자연어 일정 최적화

## 3. Proposed Tech Stack

- Language: Python 3.12+
- UI: PySide6
- Local storage: SQLite
- Scheduling logic: Python service layer
- Testing: pytest
- Packaging: PyInstaller

PySide6를 기본 UI 선택지로 둔다. Python 안에서 완성도 있는 데스크톱 앱을 만들기 좋고, 캘린더/테이블/폼 기반 인터페이스를 안정적으로 구성할 수 있다.

## 4. Project Phases

### Phase 1. Requirements And UX Definition

#### Tasks

- 주요 사용자 시나리오를 정리한다.
- 일정 입력 항목을 정의한다.
- 자동 배치 규칙을 정한다.
- 첫 화면, 일정 입력 화면, 주간 캘린더 화면의 흐름을 설계한다.
- MVP에서 반드시 필요한 기능과 이후 기능을 분리한다.

#### Deliverables

- 기능 요구사항 문서
- 화면 흐름 문서
- MVP 범위 목록

#### Done Criteria

- 사용자가 어떤 정보를 입력하는지 명확하다.
- 앱이 어떤 기준으로 일정을 생성하는지 설명할 수 있다.
- 첫 버전에서 만들 기능과 만들지 않을 기능이 구분되어 있다.

### Phase 2. Project Skeleton

#### Tasks

- Python 프로젝트 구조를 만든다.
- 의존성 관리 방식을 정한다.
- 앱 실행 진입점을 만든다.
- 테스트 디렉터리를 만든다.
- 기본 lint/format 명령을 정한다.

#### Suggested Structure

```text
schedule-helper/
  app/
    main.py
    ui/
    services/
    models/
    storage/
  tests/
  docs/
  pyproject.toml
  README.md
```

#### Deliverables

- 실행 가능한 빈 앱
- 기본 README
- 테스트 실행 환경

#### Done Criteria

- 명령 하나로 앱이 실행된다.
- 명령 하나로 테스트가 실행된다.
- 새 기능을 추가할 위치가 명확하다.

### Phase 3. Domain Model And Storage

#### Tasks

- 일정 항목 모델을 정의한다.
- 작업 항목 모델을 정의한다.
- 사용자 설정 모델을 정의한다.
- SQLite 스키마를 만든다.
- 저장, 조회, 수정, 삭제 기능을 구현한다.

#### Key Models

- Task: 이름, 예상 소요 시간, 마감일, 우선순위, 카테고리, 완료 여부
- Event: 제목, 시작 시각, 종료 시각, 고정 여부, 연결된 작업
- Availability: 사용 가능한 요일과 시간대
- Preference: 하루 최대 작업 시간, 기본 휴식 시간, 자동 배치 전략

#### Deliverables

- 데이터 모델 코드
- SQLite 저장소 코드
- 저장소 단위 테스트

#### Done Criteria

- 작업과 일정을 로컬에 저장할 수 있다.
- 앱을 껐다 켜도 데이터가 유지된다.
- 기본 CRUD 테스트가 통과한다.

### Phase 4. Scheduling Engine

#### Tasks

- 고정 일정과 사용 가능한 시간대를 계산한다.
- 작업을 우선순위와 마감일 기준으로 정렬한다.
- 빈 시간 슬롯을 찾는다.
- 작업을 가능한 시간대에 배치한다.
- 배치 실패 항목과 실패 이유를 반환한다.
- 기존 일정과 충돌하지 않도록 검증한다.

#### First Algorithm

1. 고정 일정을 먼저 캘린더에 배치한다.
2. 사용 가능한 시간대에서 고정 일정이 차지하는 시간을 제외한다.
3. 작업을 마감일이 가까운 순서, 우선순위가 높은 순서로 정렬한다.
4. 각 작업을 들어갈 수 있는 가장 이른 슬롯에 배치한다.
5. 들어가지 못한 작업은 미배치 목록에 넣는다.

#### Deliverables

- 일정 생성 서비스
- 충돌 검사 로직
- 자동 배치 단위 테스트

#### Done Criteria

- 고정 일정과 자동 배치 일정이 충돌하지 않는다.
- 마감일과 우선순위가 일정 생성에 반영된다.
- 배치 실패 항목을 사용자에게 설명할 수 있다.

### Phase 5. Core UI

#### Tasks

- 메인 윈도우를 만든다.
- 좌측에는 작업 목록과 빠른 추가 폼을 둔다.
- 중앙에는 주간 캘린더 뷰를 둔다.
- 우측에는 선택된 일정/작업의 세부 편집 패널을 둔다.
- 자동 일정 생성 버튼을 추가한다.
- 저장과 불러오기를 UI에 연결한다.

#### Main Views

- Today View: 오늘 할 일과 일정
- Week View: 주간 캘린더
- Task List View: 미배치 작업과 완료 작업
- Settings View: 사용 가능 시간대와 자동 배치 규칙

#### Deliverables

- PySide6 기반 메인 UI
- 작업 추가/수정/삭제 화면
- 주간 일정 표시 화면
- 자동 배치 실행 화면

#### Done Criteria

- 사용자가 UI만으로 작업을 추가할 수 있다.
- 사용자가 UI만으로 자동 일정을 생성할 수 있다.
- 생성된 일정이 화면에 즉시 반영된다.

### Phase 6. Manual Editing And Interaction

#### Tasks

- 일정 클릭 시 세부 정보를 표시한다.
- 일정 시간을 직접 수정할 수 있게 한다.
- 작업 완료 상태를 변경할 수 있게 한다.
- 일정 삭제와 복제를 지원한다.
- 충돌이 발생하면 사용자에게 경고한다.

#### Deliverables

- 편집 가능한 일정 UI
- 충돌 경고 UI
- 완료 처리 UI

#### Done Criteria

- 사용자가 생성된 일정을 직접 조정할 수 있다.
- 충돌이 발생하는 수정은 명확하게 표시된다.
- 수정된 데이터가 저장된다.

### Phase 7. Polish And Usability

#### Tasks

- 빈 상태 화면을 정리한다.
- 로딩, 저장 성공, 오류 메시지를 정리한다.
- 키보드 입력 흐름을 다듬는다.
- 날짜와 시간 입력 UX를 개선한다.
- 색상, 간격, 아이콘, 버튼 상태를 정돈한다.

#### Deliverables

- 완성도 있는 UI 스타일
- 사용자 친화적인 오류 메시지
- 기본 도움말 또는 README 사용법

#### Done Criteria

- 처음 실행한 사용자가 큰 설명 없이 주요 기능을 사용할 수 있다.
- 오류 상황이 조용히 실패하지 않는다.
- 화면 요소가 과하게 흔들리거나 겹치지 않는다.

### Phase 8. Testing And Validation

#### Tasks

- 일정 생성 엔진 테스트를 확장한다.
- 저장소 테스트를 확장한다.
- UI 주요 흐름을 수동 QA한다.
- 샘플 데이터를 만들어 실제 사용 흐름을 검증한다.
- 엣지 케이스를 점검한다.

#### Edge Cases

- 마감일이 지난 작업
- 너무 긴 작업
- 사용 가능한 시간이 없는 날
- 고정 일정이 하루를 대부분 차지하는 경우
- 같은 시간대에 여러 일정이 들어가려는 경우

#### Deliverables

- pytest 테스트
- 수동 QA 체크리스트
- 샘플 데이터

#### Done Criteria

- 핵심 로직 테스트가 통과한다.
- 저장/불러오기 흐름이 안정적이다.
- 주요 UI 흐름을 실제로 실행해 확인했다.

### Phase 9. Packaging And Release

#### Tasks

- PyInstaller로 실행 파일을 만든다.
- 앱 이름, 아이콘, 기본 설정 파일 위치를 정리한다.
- 첫 실행 시 데이터베이스를 자동 생성한다.
- 배포용 README를 작성한다.

#### Deliverables

- Windows 실행 파일
- 배포용 README
- 릴리스 체크리스트

#### Done Criteria

- 개발 환경 없이 앱을 실행할 수 있다.
- 새 사용자 환경에서도 기본 데이터베이스가 생성된다.
- 설치와 실행 방법이 문서화되어 있다.

## 5. MVP Feature Checklist

- [x] 작업 추가, 수정, 삭제
- [x] 고정 일정 추가, 수정, 삭제
- [x] 사용 가능 시간대 설정
- [x] 자동 일정 생성
- [x] 미배치 작업 목록 표시
- [x] 주간 캘린더 표시
- [x] 로컬 저장과 불러오기
- [x] 기본 설정 화면
- [x] 충돌 경고
- [x] 실행 파일 패키징

## 5.1 Implementation Status

현재 MVP 구현은 `app/` 패키지에 들어 있다. PySide6 UI, SQLite 저장소, 자동 배치 엔진, pytest 테스트, PyInstaller 패키징 스크립트까지 포함한다.

## 6. Suggested Milestones

### Milestone 1. Running Empty App

빈 PySide6 앱을 실행하고 기본 프로젝트 구조를 확정한다.

### Milestone 2. Data Works

작업과 일정을 SQLite에 저장하고 테스트로 검증한다.

### Milestone 3. Scheduler Works

샘플 작업과 고정 일정으로 자동 배치 결과를 만든다.

### Milestone 4. UI Works

UI에서 작업을 추가하고 자동 배치 결과를 볼 수 있다.

### Milestone 5. App Feels Usable

편집, 오류 메시지, 빈 상태, 설정 화면까지 정리한다.

### Milestone 6. App Can Ship

테스트와 패키징을 마치고 실행 파일로 배포할 수 있다.

## 7. Immediate Next Step

다음 작업은 Phase 1 산출물을 더 구체화하는 것이다. 특히 아래 세 가지를 먼저 확정하면 구현 속도가 빨라진다.

- 앱 형태: 데스크톱 앱으로 진행한다.
- 기본 뷰: 주간 캘린더를 중심 화면으로 둔다.
- 자동 배치 기준: 마감일 우선, 우선순위 보조 기준으로 시작한다.

이후 바로 Phase 2로 넘어가 프로젝트 골격을 만들 수 있다.
