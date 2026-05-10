# RSS 피드 소스 DB 이관 (sources.txt → feeds 테이블)

**날짜**: 2026-05-10

## 배경

`009`에서 Dockerfile 버그를 수정하면서 `config.yaml`을 호스트 마운트로 옮기고, 다음으로 `sources.txt`도 같은 운명에 처할 차례였음. 그러나 web UI(`/settings`)에서 RSS 피드를 추가/삭제할 수 있는데도 그 변경이 컨테이너 안 파일에만 쓰이고 재시작 시 이미지 원본으로 복원되어 **영속화되지 않는 심각한 문제**가 드러남.

호스트 마운트로 우회하는 대신, 더 적절한 위치인 **DB로 옮기기로** 결정. 다중 사용자 기능이 이미 DB 기반인 것과 일관성도 맞고, 향후 last_fetched_at, last_error 같은 메타데이터 추가 여지도 생김.

## 변경 사항

### 1. `feeds` 테이블 신설

`paleonews/db.py`:

```sql
CREATE TABLE IF NOT EXISTS feeds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT UNIQUE NOT NULL,
    title      TEXT,
    is_active  BOOLEAN NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 2. CRUD 메서드

- `add_feed(url, title=None) -> int`
- `get_active_feeds()`, `get_all_feeds()`, `get_feed_by_url(url)`
- `remove_feed(feed_id)` (hard delete)
- `set_feed_active(feed_id, bool)` (임시 비활성화 — Cambridge처럼 자주 403 나는 피드 등에 활용)
- `has_any_feeds()`, `migrate_feeds_from_file(path)`

### 3. 자동 마이그레이션

`__main__.py:main()`에서 `init_tables()` 직후 1회 실행:

```python
sources_file = config.get("sources_file")
if sources_file:
    imported = db.migrate_feeds_from_file(sources_file)
    if imported:
        logger.info("Imported %d feeds from %s into DB", imported, sources_file)
```

`migrate_feeds_from_file`은 DB의 feeds 테이블이 비어있을 때만 동작하므로 idempotent. 한 번 import 후에는 sources.txt가 변경되어도 무시됨 (DB가 진실의 원천).

### 4. 사용처 모두 DB 사용으로 전환

| 위치 | 변경 전 | 변경 후 |
|---|---|---|
| `cmd_fetch` | `load_sources(config["sources_file"])` | `[f["url"] for f in db.get_active_feeds()]` |
| `cmd_sources` (CLI) | sources.txt read/write | `db.add_feed/remove_feed/set_feed_active/get_all_feeds` |
| `web.py /settings` | sources.txt read/write | `db.get_all_feeds()` |
| `web.py /settings/sources/add` | append to file | `db.add_feed(url)` |
| `web.py /settings/sources/remove` | rewrite file | `db.remove_feed(feed_id)` (form이 url 대신 id 전송) |
| `web.py /settings/sources/toggle` (신규) | (없음) | `db.set_feed_active(feed_id, bool)` |

### 5. CLI 확장

```bash
paleonews sources list                    # 전체 (활성 표시 포함)
paleonews sources add <url>
paleonews sources remove <url-or-id>
paleonews sources activate <url-or-id>    # 신규
paleonews sources deactivate <url-or-id>  # 신규
```

### 6. settings.html 개편

- 컬럼: `# / URL / 작업` → `ID / URL / 상태(badge) / 작업(토글+삭제)`
- 활성/비활성 토글 버튼 추가
- 삭제 form은 `url` 대신 `feed_id` 전송

### 7. `load_sources` 정리

`paleonews/fetcher.py`의 `load_sources` 함수는 그대로 두었지만 호출되는 곳이 없어 사실상 데드코드. `__main__.py`에서 unused import 제거. 추후 정리 가능.

## 검증

### 로컬

```python
db = Database(tempfile)
db.init_tables()
db.has_any_feeds()                          # False
db.migrate_feeds_from_file('sources.txt')   # 10
len(db.get_active_feeds())                  # 10
db.set_feed_active(1, False)
len(db.get_active_feeds())                  # 9
db.migrate_feeds_from_file('sources.txt')   # 0 (idempotent)
db.add_feed(existing_url)                   # IntegrityError ✓
```

기존 41개 테스트 모두 통과.

### 프로덕션 배포

```
$ docker exec paleonews python -m paleonews sources list
피드 소스 (10개, 활성 10개):
  [ ] 1. https://www.science.org/action/showFeed?...
  [ ] 2. https://www.sciencedaily.com/rss/fossils_ruins.xml
  ...
$ docker exec paleonews python -m paleonews fetch
수집: 310건, 신규: 0건   ← DB 기반 피드 정상 동작
```

자동 마이그레이션이 운영 DB에 10개 피드를 채웠고, fetch는 DB에서 URL을 읽어 정상 수집.

## 운영 영향

- **즉시 영속화 보장**: web UI/CLI에서 추가/삭제/토글한 피드가 DB에 저장되어 컨테이너 재시작/재배포 후에도 보존됨.
- **`/settings`에 활성/비활성 토글 등장**: 일시 차단된 피드(Cambridge 등)를 삭제 없이 비활성으로 두고 재활성 가능.
- **`config["sources_file"]`은 마이그레이션 시드 용도로만 잔존**: DB가 비어있는 환경(신규 배포)에서 첫 부팅 시 시드. 이후로는 무시됨.

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.2.4 | feeds 테이블 신설, sources.txt → DB 자동 마이그레이션, web/CLI/fetch 모두 DB 사용 |
