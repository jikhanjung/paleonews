# 템플릿이 wheel 에서 빠져 5개 페이지가 500 (0.3.3) — 소급 기록

**날짜**: 2026-08-17 (릴리스 당일)
**기록 시점**: 같은 날 늦게. 릴리스 당시엔 `DEPLOY.md` 델타만 남고 devlog 가 없어 소급 작성한다.
**근거**: 커밋 `55d9f54`, `DEPLOY.md` 0.3.3 행.
**재발**: 같은 모양이 0.3.7 Django 전환에서 다시 나왔다 —
`devlog/20260817_018_p2_django_port.md` 참조.

## 무슨 일

`pyproject.toml` 에 `[tool.setuptools.package-data]` 가 없었다. setuptools 는 `.py` 가 아닌
파일을 기본으로 담지 않으므로 `paleonews/templates/*.html` **6개가 빌드된 패키지에서 통째로
빠졌다.**

`web.py` 는 템플릿을 `Path(__file__).parent / "templates"`, 즉 **설치된 패키지 안**에서 찾는다.
따라서 운영에서 템플릿을 렌더하는 모든 라우트가 `TemplateNotFound` 로 터졌다 —
대시보드·기사·사용자·상세·설정 **5개 페이지 전부 500**.

## 왜 오래 숨었나

실패가 **import 시점이 아니라 요청 시점**이라서다. 컨테이너는 멀쩡히 뜨고 `/healthz` 는 200 을
돌려준다 → 배포 smoke 가 통과한다. **UI 는 죽어 있는데 배포는 초록불이었다.**

> smoke 를 설계할 때 기억할 것: **헬스 엔드포인트만 찔러보는 것은 "프로세스가 살아 있다"를
> 증명할 뿐 "무언가를 서빙한다"를 증명하지 않는다.**

## 수정과 검증

`pyproject.toml` 에 package-data 선언 추가:

```toml
[tool.setuptools.package-data]
paleonews = ["templates/*.html"]
```

이미지를 빌드해 **운영 DB 사본에 붙여** 확인했다: `site-packages/paleonews/` 밑에 템플릿이
실제로 존재하고, `/`·`/articles`·`/users`·`/settings` 가 전부 200, 대시보드가 실제 내용 15KB 를
렌더했다.

## 이 교훈이 실제로 값을 했다 (0.3.7)

Django 전환에서 Jinja2 `DIRS` 를 `BASE_DIR / "paleonews" / "templates"` 로 잡았는데, 이미지에선
`paleonews` 가 site-packages 에 설치되므로 그 경로가 없다 → **repo 테스트는 통과하고 이미지에서만
전 화면이 500.** 0.3.3 과 정확히 같은 모양이다.

이번엔 배포 전에 잡혔다. 이유는 하나 — **이미지를 빌드해 운영 사본에 붙여보는 절차를 밟았기
때문**이고, 그 절차가 관행이 된 계기가 0.3.3 이다. 그 뒤로 모든 릴리스에서 `/healthz` 가 아니라
**실제 페이지**를 확인한다(0.3.4~0.3.8 의 배포 후 확인 항목이 전부 그렇게 적혀 있다).

## 파생 규칙

**비-`.py` 자산을 추가하면 `package-data` 에 함께 등록한다.** 이 규칙은 `DEPLOY.md` 0.3.3 행과
`pyproject.toml` 주석에 남아 있다. Django 층(`config/`·`news/`)은 wheel 에 넣지 않고 이미지에
소스로 싣는 방식이라(`packages.find` 가 `paleonews*` 만 잡는다) 같은 함정을 피한다.
