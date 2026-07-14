#!/usr/bin/env python3
"""Hourly backup for PaleoNews — SQLite online backup (safe while container writes).

배포·데이터 계약(../devdocs/wiki/deploy-data-contract.md)의 백업 안전망.
paleonews 는 has_seed=false — 전 테이블이 운영 데이터(articles/dispatches/users/
memories/feeds/app_settings)이고 시스템 시드 레인이 없다. 따라서 **백업이 유일한
안전망**이다(장애·오배포 시 이 스냅샷들로 복원). fsis2026/scripts/backup_db.py 동형.

- DB: sqlite3 online backup API (컨테이너가 WAL 로 쓰는 중에도 안전한 일관 스냅샷)
- 최근 RETAIN_COUNT 개만 유지(오래된 것부터 삭제)
- deploy.sh 가 만든 pre_deploy 스냅샷은 PRE_DEPLOY_RETAIN 개 유지(-wal/-shm 형제 동반)
- cron 매시 정각 실행 상정
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
RETAIN_COUNT = 12          # hourly 트랙(12시간 치)
PRE_DEPLOY_RETAIN = 20     # deploy.sh 의 retention(20)과 동일 수치 — 두 곳이 다른 값으로 같은
                           # 디렉터리를 prune 하면 hourly 쪽이 실효 retention 을 조용히 깎는다.
MIN_FREE_GB = 2            # 여유 디스크가 이 밑이면 백업 중단(디스크 소진 재발 방지)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def backup_one(name: str, src: Path) -> Path | None:
    if not src.exists():
        log(f"{name}: source not found ({src}) — skip")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H")
    dest = BACKUP_DIR / f"{name}_{stamp}.sqlite3"
    tmp = dest.with_suffix(".sqlite3.tmp")
    try:
        with sqlite3.connect(str(src)) as source_conn, sqlite3.connect(str(tmp)) as dest_conn:
            source_conn.backup(dest_conn)
        tmp.replace(dest)  # 원자 rename(같은 fs)
        size_mb = dest.stat().st_size / (1024 * 1024)
        log(f"{name}: backup OK ({dest.name}, {size_mb:.1f} MB)")
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
    for name, src in SOURCES:
        backup_one(name, src)
        prune_old(name)
    prune_pre_deploy()


if __name__ == "__main__":
    main()
