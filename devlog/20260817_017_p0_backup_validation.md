# P0 — 백업 검증 (0.3.5)

**날짜**: 2026-08-17
**계획**: `devlog/20260817_P08_django_standardization_plan.md` §P0
**짝**: naverland `devlog/20260817_017_p0_characterization_tests_backup_validation.md`(같은 날 동형 적용)

## 왜

계약 문서(`../devdocs/wiki/deploy-data-contract.md` §규범요약 MUST)가 **paleonews·naverland 를
백업 검증 미준수 2/5 로 이름 붙여 놓았다** — 나머지 3개(cdGTS 0.1.68 · fsis2026 0.5.85 ·
fcmanager 0.6.24)는 이미 상환했다. P08 표준화 계획의 P0 는 이걸 먼저 갚는다. 전환 중에는
백업이 유일한 되돌림 수단이라 **전환 전에** 끝나야 한다.

`sqlite3.backup()` 은 소스 페이지를 **검증 없이** 복사한다. 소스가 깨져 있으면 스냅샷도 조용히
깨진 채 채택되고, 그 상태로 prune 이 계속 돌면 **RETAIN_COUNT 시간이면 성한 스냅샷이 전부 사라진다**
= 백업이 스스로를 오염시켜 복구 대상 자체가 소멸한다. `has_seed=false` 라 백업이 **유일한**
안전망인 프로젝트에서 이건 안전망의 사본을 안전망이라 부르고 있던 상태다.

## 무엇을

1. 스냅샷마다 `PRAGMA integrity_check`. 검사 대상은 **라이브 소스가 아니라 방금 만든 스냅샷** —
   소스가 깨졌으면 backup 이 그대로 복사하므로 스냅샷 손상 ⇒ 소스 손상이 성립하고,
   라이브 DB 에 긴 read 트랜잭션을 걸지 않는다.
2. 실패 시 ① **미채택**(로테이션 밖) ② **prune 중단**(과거 성한 스냅샷 보존) ③ 증거 사본 1개
   (`paleonews_INTEGRITY_FAIL.corrupt`, 확장자가 `.sqlite3` 가 아니라 prune glob 에 안 걸린다)
   ④ DB 옆 `INTEGRITY_FAIL` 센티넬 ⑤ `exit 1`
3. 센티넬 → `/healthz` **status=degraded**(HTTP 는 **200 유지** — 서비스는 살아 있고 배포도 성공한
   것이다. deploy.sh 의 healthz 대기가 여기서 막히면 안 된다) → `smoke.sh` 실패
4. 복구되면 다음 정시 검사에서 **자동 해제**

**센티넬을 아무도 안 읽으면 "검사가 있다는 착각"만 만든다** — 계약이 명시적으로 경고하는 실패
모양이다. 그래서 healthz·smoke 까지 한 세트로 붙였고, 그 고리를 `tests/test_healthz.py` 3건이 지킨다.

## retention 12 → 24

집 공통값. paleonews 엔 아직 daily·오프사이트 트랙이 **없어서** 이 hourly 창이 안전망 전부다.
상위 트랙이 생겼을 때 granularity 갭(`RETAIN_COUNT × 주기 ≥ 상위 간격`)이 안 생기게 하고,
**integrity_check 가 못 잡는 논리적 손상**(파이프라인 버그로 행이 잘못 지워지는 부류 — 구조는
멀쩡해서 검사를 통과한다)을 알아챌 시간을 하루로 벌기 위해.

## 곁다리 — 고아 사이드카

`with sqlite3.connect(...)` 는 **트랜잭션 컨텍스트지 close 가 아니다**(파이썬 sqlite3 의 고전적 함정).
커넥션이 열린 채 tmp 를 rename 해서 `-wal`/`-shm` 이 고아로 남을 수 있었다. 명시적 close +
스냅샷을 `journal_mode=DELETE` 로 내려 해소했다 — 읽기 전용 integrity_check 가 WAL DB 에 `-shm` 을
만들어놓고 치울 권한이 없어 매시 고아 2개를 남기는 문제도 같이 사라진다(fsis2026 이 먼저 밟은 지점).

**데이터 손실은 없었다**: 실측에서 `-wal` 이 0바이트였고 스냅샷 행 수(2,948)가 소스와 일치했다.

## 검증

스크래치 사본에 고의로 손상을 주입해 3단계 실측:

```
1) 정상      → 채택, journal_mode=delete, 행수 2948/2948 일치, 고아 0개, exit=0
2) 손상 주입 → 미채택, exit=1, 증거 보존, 과거 스냅샷 3개 그대로, 센티넬 생성
3) 복구      → 센티넬 자동 해제, 정상 채택
```

테스트 54 → 57(healthz degraded 고리 3건 추가).

## 곁다리 발견 — 기존 테스트 헬퍼의 잠복 버그

`tests/test_log_redact.py` 의 `_capture()` 가 `root.level = INFO` 로 **직접 대입**하고 있었다.
파이썬 logging 은 로거별로 "이 레벨이 켜졌나"를 캐시하고(`Logger._cache`), 그 캐시는
**`setLevel()` 이 호출하는 `manager._clear_cache()` 로만** 지워진다. 직접 대입은 캐시를 안 지운다.

평소엔 드러나지 않다가, 새로 넣은 healthz 테스트가 TestClient 를 통해 **실제 httpx 요청**을
만들면서 `httpx` 로거 캐시에 `INFO=False` 가 박히자 그 뒤 `_capture` 가 레코드를 통째로
놓치기 시작했다(= 리댁션 테스트가 빈 문자열을 검사하며 통과할 뻔). `root.setLevel()` 로 교체.

프로덕션 코드 문제는 아니지만, **테스트 순서에 따라 조용히 무력화되는 테스트**라 고쳐 둘 값어치가 있다.
