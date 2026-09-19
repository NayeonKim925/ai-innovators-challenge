# UI 자산

- 로고: `frontend/public/brand-mark.png`. 이번 구현에서 imagegen으로 생성한 독자적인 작업 공간 심볼이다. 특정 회사의 로고를 복제하지 않았으며 최종 상표 등록 가능성을 검토했다는 의미는 아니다.
- 생성 방향: 텍스트 없이 열린 각진 육각형, 네이비 `#18333B` 프레임, 청록 `#167D7B` 연결 신호선과 사각 노드, 투명 배경, 작은 크기에서도 인식 가능한 절제된 공학적 심볼. **Continuum(컨티뉴엄)** 워드마크와 사용한다. 심볼을 다시 생성하지 않고 기존 자산과 실제 글꼴 텍스트를 조합한다.
- 브랜드 메시지·표기: [BRAND.md](BRAND.md). 시각 견본: [brand-board.html](brand-board.html). 새 이름을 적용해도 API·AWS 리소스명과 저장 ID는 유지한다.
- 글꼴: [Pretendard 공식 저장소](https://github.com/orioncactus/pretendard), 로컬 Variable WOFF2. 재배포 라이선스는 `frontend/public/fonts/OFL.txt`에 함께 보관한다.
- 아이콘: `lucide-react` 패키지. 아이콘만 사용한 컨트롤에는 aria-label을 제공한다.
- 외부 레퍼런스 캡처: `.lazyweb/quick-references/investigation-2026-09-17/references/`. 내부 리서치 기록용이며 프로덕션 웹 번들에 포함하지 않는다.
