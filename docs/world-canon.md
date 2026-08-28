# The Glass Frontier 세계관 정본

세계 ID는 `glassfrontier`, 제목은 **The Glass Frontier**다. 구조화된 콘텐츠 정본은
wheel에 포함되는 package resource
`src/aincrad/content/data/glassfrontier_world.json`이다. 세계 콘텐츠를 변경할 때는
loader, validator, runtime scenario, life-event catalog, replay tests를 함께 확인한다.

## Emberfall

따뜻한 shard spring 주변에 세워진 등불 마을이다.

- `emberfall-shop` — **Cinderstock Exchange**: 장비·보급품 거래
- `emberfall-inn` — **The Quiet Wick**: HP/MP 회복과 보관
- `emberfall-quest-hall` — **Wayfinder Assembly**: 의뢰 등록·완료
- `emberfall-plaza` — **Prismwake Square**: 공지와 길 안내
- `emberfall-tavern` — **The Copper Comet**: 식사와 검증된 소문

각 시설에는 `controller="rules"`인 규칙 기반 NPC가 정확히 하나 있어야 한다. `emberfall-shop`의 Orrin은
`orrin-cracked-crate` incident로 `금 간 화물 상자`를 제시한다. 이는 `상자를 살펴본다`/`정중히 거절한다`로
시작하고 조사 선택은 `금 간 등불을 짚어준다`/`할인가에 흠집 등불을 산다`로 끝나는 deterministic response path다.
원문 자유 입력은 콘텐츠·world state가 아니라 현재 prompt alias를 canonical response ID로 고르는 UI 경계에만 있다.

## Mossreach Wilds

비에 젖은 유리빛 구릉의 사냥 권역이며 다음 세 node가 Emberfall과 Starless Vault 입구를
순서대로 연결한다.

- `mossreach-terraces` — **이끼자락 층계**: 마을 남문 아래의 젖은 습지 층계
- `mossreach` — **이끼자락 황야**: 기존 핵심 사냥터와 후보 모험가 시작 위치
- `mossreach-vaultgate` — **금고 어귀 절벽**: Starless Vault 봉인문 앞의 절벽 관문

한 시간의 MOVE는 `emberfall → mossreach-terraces → mossreach → mossreach-vaultgate →
vault-1` 중 인접 edge 하나만 통과한다. 원거리 node는 지도에서 거리와 경유지를 볼 수 있지만
직접 건너뛸 수 없다.

## The Starless Vault

`vault-1`부터 `vault-10`까지 이어지는 10단계 던전이다. `vault-10`은
**Chamber of the Null Cartographer** 보스방이다.

- boss ID: `null-cartographer`
- transition ID: `aurora-lift-floor-2`
- 다음 월드 층: `2`

던전 단계, 연결, 보스방, 보상, 전이 ID를 바꿀 때 fixture, runtime scenario,
life-event catalog, validator, replay tests를 같은 변경에서 갱신한다.

## IP 경계

기존 상용 작품의 캐릭터, 고유 설정, 명칭, 자산을 복제하지 않는다. 공개 배포 전에
`Aincrad` 작업명과 부유성/층 구조의 IP·브랜딩을 별도로 검토한다.
