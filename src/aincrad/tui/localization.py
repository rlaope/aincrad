from __future__ import annotations

_LOCATION_NAMES_KO = {
    "emberfall": "잿불마을",
    "emberfall-shop": "잿불창고 교역소",
    "emberfall-inn": "고요한 심지 여관",
    "emberfall-quest-hall": "길잡이 회관",
    "emberfall-plaza": "빛결 광장",
    "emberfall-tavern": "구리 혜성 주점",
    "mossreach": "이끼자락 황야",
    "vault-1": "메아리 회랑",
    "vault-2": "물에 잠긴 기록보관소",
    "vault-3": "밤유리 둑길",
    "vault-4": "고요한 저수조",
    "vault-5": "흑단 천구의실",
    "vault-6": "황혼 작업장",
    "vault-7": "잿빛 온실",
    "vault-8": "거꾸로 선 종탑",
    "vault-9": "왕관 없는 대기실",
    "vault-10": "공허 지도제작자의 방",
}


def location_name_ko(location_id: str) -> str:
    """Return the Korean player-facing name for a canonical location id."""

    return _LOCATION_NAMES_KO.get(location_id, "미확인 지역")
