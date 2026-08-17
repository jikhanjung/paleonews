#!/usr/bin/env python3
"""Hourly backup for PaleoNews — SQLite online backup (safe while container writes).

배포·데이터 계약(../devdocs/wiki/deploy-data-contract.md)의 백업 안전망.
paleonews 는 has_seed=false — 전 테이블이 운영 데이터(articles/dispatches/users/
memories/feeds/app_settings)이고 시스템 시드 레인이 없다. 따라서 **백업이 유일한
안전망**이다(장애·오배포 시 이 스냅샷들로 복원). fsis2026/scripts/backup_db.py 동형.

- DB: sqlite3 online backup API (컨테이너가 WAL 로 쓰는 중에도 안전한 일관 스냅샷)
- **스냅샷마다 PRAGMA integrity_check → 실패하면 채택도 prune 도 하지 않는다**(아래 참조)
- 최근 RETAIN_COUNT 개만 유지(오래된 것부터 삭제)
- deploy.sh 가 만든 pre_deploy 스냅샷은 PRE_DEPLOY_RETAIN 개 유지(-wal/-shm 형제 동반)
- cron 매시 정각 실행 상정

**왜 검증하는가** (계약 §규범요약 MUST, cdGTS 0.1.68 · fsis2026 0.5.85 · fcmanager 0.6.24 동형):
`sqlite3.backup()` 은 소스 페이지를 **검증 없이** 복사한다. 소스가 깨져 있으면 스냅샷도 조용히
깨진 채 만들어지고, 그 상태로 prune 이 계속 돌면 **RETAIN_COUNT 시간이면 성한 스냅샷이 전부 사라진다**
= 백업이 스스로를 오염시켜 복구 대상 자체가 소멸한다. 그래서:
  1. 검사에 걸린 스냅샷은 **채택하지 않는다**(로테이션 밖) + **prune 을 건너뛴다**(과거 성한 것 보존)
  2. DB 디렉터리에 센티넬(INTEGRITY_FAIL)을 남긴다 → `/healthz` degraded → `smoke.sh` 실패
     (로그에만 남기면 아무도 안 읽는다 — 계약이 경고하는 "검사가 있다는 착각")

⚠️ **논리적 손상은 이 검사로 안 잡힌다** — 파이프라인 버그로 행이 잘못 지워져도 구조는 멀쩡해서
integrity_check 는 통과한다. 그건 retention 창(RETAIN_COUNT 시간) 안에 사람이 알아채야 한다.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("PALEONEWS_ROOT", "/srv/paleonews"))
BACKUP_DIR = ROOT / "backup"
PRE_DEPLOY_DIR = BACKUP_DIR / "pre_deploy"
SOURCES = [
    ("paleonews", ROOT / "data" / "paleonews.db"),
]
RETAIN_COUNT = 24          # hourly 트랙(24시간 치). 집 공통값 — 계약 §백업 레인 granularity 규칙은
                           # RETAIN_COUNT × 주기 ≥ 상위(daily/오프사이트) 트랙 간격. paleonews 엔
                           # 아직 daily·오프사이트 트랙이 **없어서** 이 hourly 창이 안전망 전부다.
                           # 12 → 24 로 올린 이유: 상위 트랙이 생겼을 때 갭이 안 생기게 + 논리적
                           # 손상(integrity_check 로 안 걸리는 것)을 알아챌 시간을 하루로 벌기 위해.
SENTINEL_NAME = "INTEGRITY_FAIL"
PRE_DEPLOY_RETAIN = 20     # deploy.sh 의 retention(20)과 동일 수치 — 두 곳이 다른 값으로 같은
                           # 디렉터리를 prune 하면 hourly 쪽이 실효 retention 을 조용히 깎는다.
MIN_FREE_GB = 2            # 여유 디스크가 이 밑이면 백업 중단(디스크 소진 재발 방지)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def integrity_check(path: Path) -> list[str]:
    """PRAGMA integrity_check — 통과면 [], 실패면 문제 문자열 목록.

    라이브 소스가 아니라 **방금 만든 스냅샷**을 검사한다: (a) 소스가 깨졌으면 backup() 이 그대로
    복사하므로 스냅샷 손상 ⇒ 소스 손상이 성립하고, (b) 라이브 DB 에 긴 read 를 걸지 않는다.
    """
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as e:
        return [f"열기/PRAGMA 실패: {e}"]      # 헤더부터 깨진 경우 — 손상으로 취급
    finally:
        if conn is not None:
            conn.close()
    return [r[0] for r in rows if r and r[0] != "ok"]


def raise_sentinel(db_dir: Path, problems: list[str]):
    """DB 디렉터리에 손상 플래그 → /healthz degraded → smoke 실패(사람이 보는 경로로 나간다)."""
    body = [
        f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} backup_db.py: PRAGMA integrity_check 실패.',
        "이 파일이 있는 한 /healthz 는 degraded 이고 smoke 는 실패한다.",
        "백업 로테이션 prune 은 중단됐다 — backup/ 의 과거 스냅샷이 복구 후보다.",
        "조치 후 다음 정시 검사가 통과하면 자동으로 지워진다.",
        "",
        *problems[:20],
    ]
    try:
        (db_dir / SENTINEL_NAME).write_text("\n".join(body) + "\n")
    except OSError as e:
        log(f"경고: 센티넬 기록 실패 ({db_dir / SENTINEL_NAME}: {e}) — smoke 가 못 잡는다")


def clear_sentinel(db_dir: Path):
    """검사 통과 시 자기 해제 — 손상이 고쳐졌는데 degraded 로 남아 있으면 안 된다."""
    sentinel = db_dir / SENTINEL_NAME
    if sentinel.exists():
        try:
            sentinel.unlink()
            log(f"integrity OK — 센티넬 해제({sentinel})")
        except OSError as e:
            log(f"경고: 센티넬 해제 실패 ({sentinel}: {e})")


def sanitize_egress(conn: sqlite3.Connection) -> int:
    """스냅샷 **사본**에서 bearer 토큰(`django_session`)을 지운다. 반환: 지운 행 수.

    ★ **대상은 스냅샷 사본뿐 — 라이브 운영 DB 는 읽기만 한다.** 로그인한 사용자는 무영향.

    왜 (계약 §백업 레인 MUST, cdGTS 151 · fcmanager 0.6.25 · fsis2026 0.5.87 동형):
      `django_session.session_key` 는 **쿠키에 담기는 값 그 자체(bearer 토큰)** 다. 사본을 읽은
      사람이 그걸 **운영에** 되제시하면 운영이 자기 DB 에서 그 행을 찾아 자기 SECRET_KEY 로
      디코드해 **그 사용자로 로그인된다**. ⚠️ **SECRET_KEY 가 달라도 안 막힌다** — 그 공격은
      해독을 하지 않는다("prod/test 키가 다르니 안전"은 틀렸다). 받는 쪽에선 키 불일치로
      무용지물이라, **주는 쪽엔 위험하고 받는 쪽엔 쓸모없는 순수 손해** = 지워서 잃는 게 없다.

    비밀번호 해시(`auth_user.password`)는 **남긴다** — 성질이 다르다(강한 KDF 라 그냥 쓸 수 없고,
    지우면 사본으로 로그인 확인을 못 한다).

    **초크포인트를 여기(hourly)에 두는 이유**: 하위 트랙(오프사이트·미러·수동 scp)은 전부 이
    산출물을 소비하므로 한 번 지우면 **구조적으로** 덮인다. 반대로 반출 스크립트마다 지우면
    트랙이 늘 때 빠뜨린다. 롤백용 pre_deploy 스냅샷은 **호스트를 안 떠나므로** 위생 대상이
    아니다(deploy.sh 가 만들고 이 스크립트는 prune 만 한다) → `rollback --db=restore` 는 무영향.

    ⚠️ paleonews 는 0.3.6 까지 세션 테이블 자체가 없었다(FastAPI). Django admin 도입(P08 §P2)으로
    생기며, 테이블이 없으면 조용히 0 을 돌려준다.

    **VACUUM 은 무조건 한다.** DELETE 는 행만 지우고, 과거에 지워진 세션(로그아웃·만료 정리)의
    잔류는 free page 에 남아 `backup()` 이 페이지째 복사해 간다. 남고 안 남고가 sqlite 빌드
    설정(`secure_delete`)에 갈리는데 그건 통제 밖이라 조건을 따지지 않는다 — 비용은 1초 미만이다.
    """
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='django_session'"
    ).fetchone()
    n = conn.execute("DELETE FROM django_session").rowcount if has_table else 0
    conn.commit()                       # VACUUM 은 트랜잭션 안에서 못 돈다 → 먼저 닫는다
    conn.execute("VACUUM")
    return n


def backup_one(name: str, src: Path) -> Path | None:
    if not src.exists():
        log(f"{name}: source not found ({src}) — skip")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H")
    dest = BACKUP_DIR / f"{name}_{stamp}.sqlite3"
    tmp = dest.with_suffix(".sqlite3.tmp")
    try:
        # `with sqlite3.connect(...)` 를 쓰지 않는다 — 그건 **트랜잭션** 컨텍스트지 close 가 아니다
        # (파이썬 sqlite3 의 고전적 함정). 단명 cron 프로세스라 GC 가 닫아주긴 했지만,
        # GC 타이밍에 기대는 정합성은 계약이 아니고 아래 integrity_check 가 정적인 파일을 봐야 한다.
        source_conn = dest_conn = None
        purged, sanitize_err = 0, None
        try:
            source_conn = sqlite3.connect(str(src))
            dest_conn = sqlite3.connect(str(tmp))
            source_conn.backup(dest_conn)       # online backup API — writer 상주해도 일관 스냅샷
            try:
                # 반출 위생 — **채택 전에** 지운다(위 sanitize_egress docstring 참조).
                purged = sanitize_egress(dest_conn)
                # backup 은 소스의 저널 모드까지 복사 → 스냅샷이 WAL 로 뜬다(운영 소스가 WAL).
                # **아카이브는 WAL 일 이유가 없다**(동시 writer 가 없다). DELETE 로 내려
                # -wal/-shm 이 아예 존재하지 않게 만든다 — 특히 아래 integrity_check 는 mode=ro 로 여는데,
                # **읽기 전용 커넥션은 WAL DB 의 -shm 을 만들어놓고 치울 권한이 없어** 매시 고아 2개가 쌓인다.
                dest_conn.execute("PRAGMA journal_mode=DELETE")
            except sqlite3.DatabaseError as e:
                # ⚠️ 손상된 소스면 여기서 터진다(VACUUM 이 malformed 로 죽는다). 예외를 밖으로
                # 던지면 아래 무결성 게이트를 건너뛰어 **센티넬도 증거 사본도 안 남는다**
                # (= smoke 가 못 잡음). 삼키고 게이트가 판정하게 넘긴다.
                sanitize_err = e
                log(f"{name}: 위생/journal_mode 단계 실패({e}) — 무결성 게이트에 판정을 넘긴다")
        finally:
            for conn in (dest_conn, source_conn):
                if conn is not None:
                    conn.close()

        # 채택 전 게이트 — 깨진 스냅샷은 로테이션에 들어가지 않는다.
        problems = integrity_check(tmp)
        if problems:
            log(f"{name}: !! INTEGRITY FAIL — 스냅샷 미채택. 라이브 DB({src}) 손상으로 간주.")
            for p in problems[:5]:
                log(f"{name}:    {p}")
            # 증거는 **하나만** 남긴다: 최초 손상이 가장 정보가 많고, 매시 쌓이면 디스크가 샌다.
            # 확장자가 .sqlite3 가 아니라 prune_old() 의 glob 에도 안 걸린다.
            evidence = BACKUP_DIR / f"{name}_INTEGRITY_FAIL.corrupt"
            if evidence.exists():
                tmp.unlink()
                log(f"{name}: 증거 사본 이미 있음({evidence.name}) — 이번 것은 버림")
            else:
                tmp.replace(evidence)
                log(f"{name}: 증거 사본 보존 → {evidence.name}")
            raise_sentinel(src.parent, problems)
            return None

        if sanitize_err is not None:
            # 무결성은 통과했는데 위생만 실패 = 손상이 아닌 다른 문제(권한 등). 센티넬은 올리지
            # 않는다(DB 손상 신호가 아니다). 다만 **세션이 실린 스냅샷을 채택하느니 백업을 거른다** —
            # 이 사본은 언젠가 호스트를 떠난다(계약: 위생 실패 시 반출 중단).
            log(f"{name}: !! 반출 위생 실패 — 스냅샷 미채택({sanitize_err})")
            tmp.unlink(missing_ok=True)
            return None

        tmp.replace(dest)  # 원자 rename(같은 fs)
        clear_sentinel(src.parent)
        size_mb = dest.stat().st_size / (1024 * 1024)
        log(f"{name}: backup OK ({dest.name}, {size_mb:.1f} MB, integrity ok, session {purged}행 제거)")
        return dest
    except Exception as e:
        log(f"{name}: ERROR {e}")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return None


def prune_old(name: str, suffix: str = ".sqlite3"):
    """RETAIN_COUNT 개의 최신 스냅샷만 유지; 나머지 삭제."""
    snapshots = []
    for f in BACKUP_DIR.glob(f"{name}_*{suffix}"):
        stem = f.name[: -len(suffix)] if f.name.endswith(suffix) else f.stem
        parts = stem.split("_")
        if len(parts) < 3:
            continue
        try:
            dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H")
        except ValueError:
            continue
        snapshots.append((dt, f))
    snapshots.sort(key=lambda x: x[0], reverse=True)
    deleted = 0
    for _, f in snapshots[RETAIN_COUNT:]:
        try:
            f.unlink()
            deleted += 1
        except OSError:
            pass
    if deleted:
        log(f"{name}: pruned {deleted} old snapshot(s)")


def prune_pre_deploy():
    """deploy.sh 가 만든 pre_deploy 스냅샷의 최근 PRE_DEPLOY_RETAIN 개만 유지.

    파일명: paleonews_pre_deploy_X.Y.Z_YYYYMMDD_HHMMSS.sqlite3 (deploy.sh 스냅샷 단계).
    본체만 unlink 하면 -wal/-shm/.mig 사이드카가 고아로 누적된다 → 동반 삭제.
    """
    if not PRE_DEPLOY_DIR.is_dir():
        return
    snapshots = sorted(
        PRE_DEPLOY_DIR.glob("paleonews_pre_deploy_*.sqlite3"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    deleted = 0
    for f in snapshots[PRE_DEPLOY_RETAIN:]:
        for p in (f, Path(f"{f}-wal"), Path(f"{f}-shm"), Path(f"{f}.mig")):
            try:
                p.unlink()
            except OSError:
                pass
        deleted += 1
    if deleted:
        log(f"pre_deploy: pruned {deleted} old snapshot(s) (+사이드카)")


def check_disk_space() -> bool:
    """여유 디스크가 임계치 미만이면 백업 중단(디스크 소진으로 백업이 DB 를 손상시키는 것 방지)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(BACKUP_DIR).free / (1024 ** 3)
    if free_gb < MIN_FREE_GB:
        msg = f"ABORT: free disk {free_gb:.2f} GB < {MIN_FREE_GB} GB threshold — skipping backup"
        log(msg)
        print(f"ERROR: {msg}", file=sys.stderr)
        return False
    return True


def main():
    if not check_disk_space():
        sys.exit(1)
    failed = False
    for name, src in SOURCES:
        if backup_one(name, src) is None:
            # 스냅샷을 못 만들었거나(디스크/IO) 무결성에 걸렸다. 어느 쪽이든 **prune 하지 않는다** —
            # 새 스냅샷 없이 과거를 지우면 보관 창이 소리 없이 줄어든다(계약 MUST).
            failed = True
            log(f"{name}: prune 건너뜀(스냅샷 미채택) — 과거 스냅샷 보존")
            continue
        prune_old(name)
    prune_pre_deploy()
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
