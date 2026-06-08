# Focus-Oriented UI Redesign Plan

## 1. Background

현재 앱은 일정, 작업, 사용 시간, 설정이 각각 분리된 칸과 탭에 들어가 있어 전체적으로 산만하다. 사용자가 원하는 방향은 단순한 스케줄러보다, 오늘 해야 할 일과 지금 집중해야 할 화면을 정하고, 뽀모도로와 메모를 함께 기록하는 집중 도구에 가깝다.

이번 개편의 목표는 다음과 같다.

- 스케줄 관리, 뽀모도로, 일시정지를 한 화면에서 자연스럽게 사용한다.
- 샘플 데이터와 자동 배치처럼 당장 필요하지 않은 기능은 제거하거나 숨긴다.
- 특정 화면이나 프로그램에 머물러야 하는 집중 시간을 정하고 체크한다.
- 앱을 작게 줄였을 때도 남은 시간과 집중 상태를 위젯처럼 볼 수 있다.
- 노션의 빠른 메모처럼 즉시 기록하고, 메모가 작성된 시간을 자동 저장한다.

## 2. Product Direction

### From

- 주간 캘린더 중심
- 여러 폼과 테이블이 나뉜 관리형 UI
- 자동 배치 버튼이 주요 액션
- 샘플 데이터 버튼이 툴바에 노출

### To

- 오늘의 집중 세션 중심
- 일정, 타이머, 메모가 한 작업 흐름 안에 있는 UI
- 사용자가 직접 정한 집중 시간과 대상 화면을 체크
- 빠른 메모와 기록 타임라인 중심
- 필요할 때만 펼치는 세부 설정

## 3. UX Principles

- 첫 화면은 오늘 집중할 일, 남은 시간, 빠른 메모만 보여준다.
- 기능별 박스 나열을 줄이고, 하나의 흐름처럼 배치한다.
- 주요 액션은 `시작`, `일시정지`, `완료`, `메모`로 제한한다.
- 캘린더는 보조 정보로 두고, 주간 전체보다는 오늘 일정에 집중한다.
- 샘플 데이터는 앱 UI에서 제거한다.
- 자동 배치는 첫 화면에서 제거하고, 필요하면 향후 고급 기능으로 숨긴다.
- 집중 상태와 남은 시간은 앱이 작아졌을 때도 유지해서 보여준다.

## 4. New Information Architecture

### Primary Screen: Focus Desk

앱의 첫 화면이다.

- 상단: 오늘 날짜, 현재 집중 상태, 작은 설정 버튼
- 중앙: 현재 집중 세션
- 하단 또는 우측: 빠른 메모 타임라인
- 보조 영역: 오늘 일정과 할 일 목록

### Secondary Screen: Plan

오늘 또는 이번 주 할 일을 정리하는 화면이다.

- 할 일 추가
- 오늘 할 일 정렬
- 간단한 시작 예정 시간 지정
- 완료 처리

### Secondary Screen: History

기록 확인 화면이다.

- 집중 세션 기록
- 프로그램별 사용 시간
- 메모 타임라인
- 날짜별 필터

### Secondary Screen: Settings

자주 쓰지 않는 설정을 모은다.

- 뽀모도로 기본값
- 자리 비움 기준
- 집중 대상 프로그램 감지 설정
- 데이터베이스 위치

## 5. Main Screen Layout

### Top Bar

- 오늘 날짜
- 현재 집중 모드 상태
- compact mode 전환 버튼
- 설정 버튼

### Focus Area

가장 큰 영역으로 배치한다.

- 현재 집중할 일 제목
- 집중 대상 프로그램 또는 창
- 목표 집중 시간
- 경과 시간
- 남은 시간
- 집중 유지율
- 시작 버튼
- 일시정지 버튼
- 재개 버튼
- 완료 버튼

### Today Strip

Focus Area 아래에 얇게 배치한다.

- 오늘의 다음 일정
- 오늘의 할 일 3-5개
- 새 할 일 빠른 추가

### Quick Memo

항상 접근 가능한 입력창으로 둔다.

- 한 줄 또는 여러 줄 메모 입력
- `Ctrl+Enter`로 저장
- 저장 시각 자동 기록
- 현재 집중 세션, 현재 프로그램, 현재 일정과 자동 연결
- 바로 아래에 최근 메모 5개 표시

## 6. Compact Widget Mode

앱을 작게 줄였을 때 별도 위젯처럼 보여주는 모드다.

### Widget Content

- 현재 세션 제목
- 남은 시간
- 집중 대상 앱 이름
- 집중 유지 상태
- 일시정지/재개 버튼
- 메모 빠른 입력 버튼

### Behavior

- 항상 위에 표시 옵션을 제공한다.
- 기본 창보다 훨씬 작은 크기로 전환된다.
- 닫기가 아니라 숨김/트레이 동작으로 이어질 수 있다.
- 메인 화면으로 돌아가는 버튼을 둔다.

### First Implementation

처음에는 별도 트레이 앱까지 만들지 않고, 같은 PySide6 창을 compact layout으로 전환한다. 이후 필요하면 `QSystemTrayIcon`과 별도 floating window로 확장한다.

## 7. Focus Session Behavior

### Session Inputs

- 집중할 일
- 집중 대상 프로그램
- 목표 집중 시간
- 뽀모도로 길이
- 휴식 길이
- 한 화면에 머물러야 하는 최소 시간

### Session States

- Ready
- Running
- Paused
- Break
- Completed
- Interrupted

### Tracking Rules

- 등록한 프로그램 또는 선택한 창이 foreground일 때만 집중 시간으로 인정한다.
- 다른 앱으로 벗어나면 이탈 시간으로 기록한다.
- 사용자가 일시정지하면 집중 시간과 이탈 판정을 멈춘다.
- 자리 비움 기준을 넘으면 자동 일시정지하거나 이탈로 기록한다.
- 목표 시간이 끝나면 완료 상태로 전환하고 기록을 저장한다.

### Metrics

- 목표 시간
- 실제 집중 시간
- 이탈 시간
- 일시정지 시간
- 집중 유지율
- 연결된 메모 수

## 8. Pomodoro And Pause

### Pomodoro Defaults

- 집중 25분
- 휴식 5분
- 긴 휴식 15분
- 긴 휴식은 4회 집중 후

### Required Controls

- 시작
- 일시정지
- 재개
- 건너뛰기
- 완료
- 세션 취소

### UI Placement

뽀모도로는 독립된 기능 박스가 아니라 Focus Area의 타이머 모드로 넣는다.

## 9. Quick Memo

### Requirements

- 메모 입력은 첫 화면에서 바로 가능해야 한다.
- 메모 저장 시각은 자동 기록한다.
- 메모는 현재 집중 세션과 자동 연결할 수 있다.
- 집중 세션이 없으면 단독 메모로 저장한다.
- 메모 목록은 최신순으로 보여준다.

### Fields

- id
- body
- created_at
- linked_focus_session_id
- linked_task_id
- linked_program_name

## 10. Data Model Changes

### New Tables

#### focus_sessions

- id
- title
- task_id
- target_process_name
- target_window_title
- planned_seconds
- focused_seconds
- paused_seconds
- away_seconds
- started_at
- ended_at
- status

#### focus_events

- id
- focus_session_id
- event_type
- started_at
- ended_at
- duration_seconds
- metadata

event_type examples:

- running
- paused
- away
- break

#### quick_notes

- id
- body
- created_at
- focus_session_id
- task_id
- process_name

### Existing Tables To Reuse

- tasks
- events
- app_targets
- app_usage_sessions

### Existing Features To Remove Or Demote

- 샘플 데이터 버튼 제거
- 자동 배치 버튼 제거
- 주간 캘린더를 첫 화면에서 보조 화면으로 이동
- 복잡한 일정 편집 폼은 필요할 때만 펼치기

## 11. Implementation Phases

### Phase 1. Product Simplification

#### Tasks

- 샘플 데이터 버튼과 관련 UI 제거
- 자동 배치 버튼을 제거하거나 Settings/Advanced로 이동
- 첫 화면의 기본 탭 구조를 Focus Desk 중심으로 재배치
- 기존 기능 중 유지할 것과 숨길 것을 확정

#### Done Criteria

- 첫 화면에서 샘플 데이터와 자동 배치가 보이지 않는다.
- 사용자는 앱을 열자마자 집중 세션을 시작할 수 있다.

### Phase 2. Focus Session Data Layer

#### Tasks

- focus_sessions 테이블 추가
- focus_events 테이블 추가
- quick_notes 테이블 추가
- 저장소 CRUD 구현
- 집중 시간 계산 유틸리티 구현

#### Done Criteria

- 집중 세션을 저장하고 다시 불러올 수 있다.
- 일시정지, 이탈, 휴식 시간이 별도 이벤트로 저장된다.
- 메모가 작성 시각과 함께 저장된다.

### Phase 3. Focus Timer Service

#### Tasks

- 세션 상태 머신 구현
- 시작/일시정지/재개/완료/취소 처리
- 뽀모도로 집중/휴식 전환 처리
- foreground 프로그램 감지와 연결
- 이탈 시간과 집중 시간을 계산

#### Done Criteria

- 타이머가 1초 단위로 안정적으로 갱신된다.
- 일시정지 중에는 집중 시간이 증가하지 않는다.
- 지정한 프로그램을 벗어나면 이탈 시간이 증가한다.
- 목표 시간이 끝나면 세션이 완료된다.

### Phase 4. Focus Desk UI

#### Tasks

- 기존 우측 탭 중심 UI를 줄인다.
- 중앙에 Focus Area를 만든다.
- 오늘 할 일과 다음 일정을 얇은 보조 영역으로 배치한다.
- 빠른 메모 입력창과 최근 메모 목록을 추가한다.
- 프로그램 선택 드롭다운을 Focus Area 안으로 이동한다.

#### Done Criteria

- 사용자는 첫 화면에서 집중 대상, 시간, 메모를 모두 다룰 수 있다.
- 큰 테이블과 여러 폼이 첫 화면을 압도하지 않는다.
- UI가 한 가지 주요 행동, 즉 지금 집중하기를 중심으로 보인다.

### Phase 5. Compact Widget Mode

#### Tasks

- compact mode 전환 버튼 추가
- compact layout 구현
- 남은 시간, 집중 유지 상태, 일시정지 버튼 표시
- 메인 화면으로 돌아가기 구현
- 창 크기 축소 시 compact mode 자동 제안 또는 자동 전환 검토

#### Done Criteria

- 작은 창에서도 남은 시간과 집중 상태를 볼 수 있다.
- compact mode에서 일시정지/재개가 가능하다.
- 메인 화면으로 쉽게 돌아갈 수 있다.

### Phase 6. History And Review

#### Tasks

- 날짜별 집중 기록 보기
- 프로그램별 사용 시간 보기
- 메모 타임라인 보기
- 집중 세션별 메모 필터

#### Done Criteria

- 오늘 어떤 앱에 얼마나 집중했는지 확인할 수 있다.
- 특정 세션에서 작성한 메모를 확인할 수 있다.
- 메모가 작성된 시간이 명확히 보인다.

### Phase 7. Polish

#### Tasks

- 전체 시각 밀도 낮추기
- 반복되는 테이블 줄이기
- 버튼 이름과 위치 정리
- 빈 상태 문구 정리
- 키보드 단축키 추가

#### Suggested Shortcuts

- `Ctrl+Enter`: 메모 저장
- `Space`: 타이머 일시정지/재개
- `Ctrl+N`: 새 빠른 메모
- `Ctrl+Shift+F`: compact mode 전환

#### Done Criteria

- 첫 화면에서 어디를 봐야 하는지 명확하다.
- 자주 쓰는 기능이 한 화면에 있다.
- 보조 기능은 시야를 방해하지 않는다.

## 12. Testing Plan

### Unit Tests

- Focus session 상태 전환
- 일시정지 시간 계산
- 이탈 시간 계산
- 뽀모도로 완료/휴식 전환
- 빠른 메모 저장
- 메모와 세션 연결

### UI Smoke Tests

- 앱 실행
- 집중 세션 시작
- 일시정지/재개
- 메모 저장
- compact mode 전환
- 추적 대상 프로그램 선택

### Manual QA

- 화면을 작게 줄였을 때 compact mode가 보기 좋은지 확인
- 다른 앱으로 전환할 때 이탈 시간이 기록되는지 확인
- 자리 비움 기준을 넘었을 때 집중 시간이 멈추는지 확인
- 메모 작성 시각이 실제 작성 시각으로 저장되는지 확인

## 13. Recommended First Cut

가장 먼저 할 구현 범위는 아래로 제한한다.

1. 샘플 데이터 버튼 제거
2. 자동 배치 버튼 제거
3. Focus Desk 첫 화면 추가
4. 뽀모도로 시작/일시정지/재개/완료 구현
5. 빠른 메모 저장과 작성 시각 표시
6. 현재 열린 프로그램 드롭다운을 Focus Desk로 이동
7. compact mode 1차 구현

이 범위까지 구현하면 앱의 성격이 분명하게 바뀐다. 이후 기록 분석과 세부 설정을 다듬는다.

## 14. Implementation Status

1차 구현 완료 항목:

- 샘플 데이터 버튼 제거
- 자동 배치 버튼 제거
- Focus Desk 첫 화면 추가
- 뽀모도로 목표/휴식 설정 UI 추가
- 시작, 일시정지, 재개, 완료 구현
- 대상 프로그램 foreground 여부 기반 집중/이탈 시간 계산
- 빠른 메모 저장과 작성 시각 기록
- 현재 열린 프로그램 드롭다운을 Focus Desk에 배치
- compact widget mode 1차 구현
- 집중 세션, 세션 이벤트, 빠른 메모 SQLite 저장

다음 개선 후보:

- 집중 기록 분석 화면 고도화
- 세션별 메모 필터
- 트레이 아이콘과 독립 floating widget
- 휴식 알림음 또는 시스템 알림
