# P06 Django 전환 재평가 (보류 결정)

**날짜**: 2026-07-14
**대상**: `devlog/20260324_P06_django_migration_plan.md`
**결론**: **현재 시점 전환 보류.** 실익(코드량 감소) 대비 손실(재작업·빌링 리스크)이 큼.

## 배경

P06 은 2026-03-24 작성. 그 이후 두 건의 대형 작업이 들어가면서 계획의 전제가 바뀜:

- **배포·데이터 계약 정렬 (0.3.0/0.3.1, 2026-07-14)** — `deploy.toml` 매니페스트 + `/healthz` + `backup_db.py` + WAL 형제 스냅샷 + `.mig` 스키마 지문 게이트 + 단일 컨테이너(root) self-heal
- **구독 빌링 수정 (0.2.8, 2026-06)** — `claude_code` provider `CLAUDE_CODE_OAUTH_TOKEN`, `all` 모드 단일 컨테이너(cron+bot+web, root)

## 코드 규모 재측정 (P06 표는 낡음)

| 모듈 | P06 기준 | 현재(0.3.1) |
|------|---------|-------------|
| db.py | 432 | 579 |
| web.py | 261 | 395 |
| templates | 502 | 729 |
| __main__ | 603 | 617 |

순감소는 계획의 ~700줄보다 커지지만, 전체 ~3,300줄 단일 개발자 프로젝트라 코드량 감소 자체는 약한 동기. db.py 579줄 중 실제 쿼리 메서드는 ~250줄이고 나머지는 DDL + `_migrate()`로, 안정적으로 동작하며 유지보수 부담이 낮음.

## 전환에 반대하는 근거

1. **방금 끝낸 배포 계약을 통째로 재설계해야 함 (최대 리스크).** 0.3.0 인프라 전체가 SQLite + db.py + 단일 컨테이너(root)에 맞춰짐. Django 의 `migrate --noinput`/`collectstatic`/gunicorn WSGI/멀티서비스 compose 가 백업·마이그레이션 게이트와 어긋나 재작업 필요. 어제 투자분 폐기.

2. **P06 의 3-서비스 compose(web/pipeline/bot 분리)가 구독 빌링을 깰 위험.** 현재 `all` 모드 단일 컨테이너는 0.2.8 에서 복구한 구독 토큰 빌링과 직결(메모리: `ANTHROPIC_API_KEY` 존재 시 구독 빌링 파손). 서비스 분리는 claude CLI 인증 표면을 3배로 늘림.

3. **"Django Admin 60줄 대체"는 과대평가.** 현재 web.py 는 순수 CRUD 가 아님 — 파이프라인 실행 버튼+상태 폴링(`/pipeline/run`, `/pipeline/status`), provider·모델 드롭다운 설정 편집(`app_settings` overlay, `/settings/models/update`), 소스·키워드·이메일 편집. 전부 Django custom action/view 로 재작성 필요(P06 리스크 #5 자인). "763→60줄"은 재작성 비용 누락.

4. **`app_settings` overlay 는 Django settings 에 안 맞음.** `config.yaml`(베이스) + DB overlay + 매 요청 재구성 패턴은 프로세스-정적 Django settings 와 성격이 다름. `PIPELINE_CONFIG` 로딩을 유지해야 해 config.py 도 실제론 삭제 안 됨.

5. **SQLite 동시성 악화 (P06 리스크 #1 자기모순).** 현재 단일 컨테이너 co-location 이 경합을 줄이는데, 3개 컨테이너가 bind-mount SQLite 하나를 두드리면 경합 증가.

6. **인증 불필요.** nginx 뒤 자기호스팅 단일 관리자 환경이라 Django auth 는 실수요 없음.

## Django 가 실제 유리해지는 조건 (미래 트리거)

- 웹 UI 야심 확대 (다중 관리자, 복잡 관계형 조회, 리치 UI)
- 스키마 churn 급증 (현재 스키마는 안정적)
- 실제 인증 요구 발생

## 권장 조치

- **전면 전환 보류.** P06 은 "웹앱으로 성장 시" 참고 문서로 보존.
- ORM/Admin 이 아쉬우면 값싼 부분 도입 고려:
  - 마이그레이션만 → Alembic/SQLModel 만 얹기
  - 조회 UI 만 → 같은 DB 읽기 전용 Django Admin 보조 뷰(파이프라인·배포는 현행 유지)
