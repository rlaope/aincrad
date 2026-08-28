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

_LOCATION_DESCRIPTIONS_KO = {
    "emberfall": "따뜻한 결정 샘을 중심으로 등불과 돌길이 이어진 마을입니다.",
    "emberfall-shop": "황동 덧문 안에 여행 장비와 결정 오염 방지 보급품이 쌓여 있습니다.",
    "emberfall-inn": "샘물의 온기가 바닥을 데워 긴 여정 뒤 몸을 회복하기 좋은 여관입니다.",
    "emberfall-quest-hall": "탐사대와 주민이 위험 정보와 의뢰를 공개적으로 교환하는 회관입니다.",
    "emberfall-plaza": "공지판과 안전한 길 안내 표식이 모인 넓은 중앙 광장입니다.",
    "emberfall-tavern": "정찰자들이 따뜻한 차를 마시며 검증된 소문을 나누는 지하 주점입니다.",
    "mossreach": "비에 젖은 유리빛 구릉 사이로 야생 짐승이 오가는 황야입니다.",
    "vault-1": "울림이 큰 석조 회랑을 점토 보초들이 순찰하고 있습니다.",
    "vault-2": "오래된 기록 선반이 물에 반쯤 잠기고 먹빛 생물이 움직이는 공간입니다.",
    "vault-3": "어두운 심연 위로 좁은 유리 다리가 이어진 통로입니다.",
    "vault-4": "고요한 수조 아래 압력 장치와 창백한 등껍질 생물이 숨어 있습니다.",
    "vault-5": "차가운 인공 달 주위를 빛 없는 황동 천체가 회전하는 방입니다.",
    "vault-6": "버려진 렌즈 절삭기가 멈추지 않고 움직이는 위험한 작업장입니다.",
    "vault-7": "온기 없는 등불 아래 검은 잎 덩굴이 무성하게 자란 온실입니다.",
    "vault-8": "거짓 계단을 밟으면 종이 울리는 아래로 향한 종탑입니다.",
    "vault-9": "반사된 문양을 맞춰야 열리는 아홉 개의 봉인문이 앞을 막습니다.",
    "vault-10": "빛을 삼키는 지도 장치와 최심부의 수호자가 기다리는 보스방입니다.",
}


def location_name_ko(location_id: str) -> str:
    """Return the Korean player-facing name for a canonical location id."""

    return _LOCATION_NAMES_KO.get(location_id, "미확인 지역")


def location_description_ko(location_id: str) -> str:
    """Return public Korean physical context for a canonical location id."""

    return _LOCATION_DESCRIPTIONS_KO.get(location_id, "확인된 지형 정보가 없습니다.")


def location_direction_ko(location_id: str) -> str:
    """Return a localized location name with the correct Korean 로/으로 particle."""

    name = location_name_ko(location_id)
    final = name[-1]
    if "가" <= final <= "힣":
        jongseong = (ord(final) - ord("가")) % 28
        particle = "로" if jongseong in {0, 8} else "으로"
    else:
        particle = "으로"
    return f"{name}{particle}"
