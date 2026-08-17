"""Jinja2 환경 — 기존 템플릿이 FastAPI 시절과 똑같이 렌더되게 한다.

템플릿 자체는 한 글자도 고치지 않는다(P08 §P2 포팅 원칙: 예쁘게 다시 쓰다 값이 바뀌는 것이
유일한 실패 모드다). 여기서 하는 건 Django 쪽 이름 몇 개를 넣어주는 것뿐이다.
"""
from jinja2 import Environment


def environment(**options):
    env = Environment(**options)
    # 지금 템플릿들은 `request`·`url` 을 쓰지 않는다(확인함). 나중에 필요해지면 여기에 넣는다.
    return env
