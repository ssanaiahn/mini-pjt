# 프로젝트: VOC 접수 판단·응답 보조

과제 제출용 1인 프로젝트. Streamlit 앱(`app.py`), 로직 `voc/`, 메뉴 설정 `config/menus.json`, SQLite `data/voc.db`(모의 데이터만).

## 명령
- 실행: `streamlit run app.py`
- 테스트: `python -m pytest -q` (API 키 없이 템플릿 경로, 임시 DB 사용)

## 규칙
- 판정은 규칙 기반: 본문에 메뉴명/별칭 부분 문자열이 있으면 처리 가능. 다중 매칭 시 각 메뉴 누적 +1.
- 처리 불가 건은 이력만 저장, 누적 제외. 누적(등록자 무관) 3 이상이면 모의 DB 조회.
- 안내 문구: `ANTHROPIC_API_KEY`가 있으면 Claude API(10초 타임아웃), 실패·없음이면 템플릿.
- 빈/공백 입력은 경고만 표시하고 저장하지 않음.
- 범위 외 금지: 화면 메뉴 편집, 발표 자료 등. 문서는 README.md, SERVICE.md, 기대값표(`data/sample_vocs_expected.csv`)만.

## 개발 워크플로우 (Ouroboros)

```
Interview → Seed → Execute → Evaluate
    ↑                           ↓
    └─── Evolutionary Loop ─────┘
```

| Command | Loads |
|---------|-------|
| `ooo` | — |
| `ooo interview` | `ouroboros:socratic-interviewer` |
| `ooo seed` | `ouroboros:seed-architect` |
| `ooo run` | MCP required |
| `ooo evolve` | MCP: `evolve_step` |
| `ooo evaluate` | `ouroboros:evaluator` |
| `ooo unstuck` | `ouroboros:{persona}` |
| `ooo status` | MCP: `session_status` |
| `ooo setup` | — |
| `ooo help` | — |

- 현재 Seed: `seed_f1b636967d57` (v1.1.0)
- 에이전트는 필요할 때 로드: socratic-interviewer, ontologist, seed-architect, evaluator, advocate, contrarian, judge, hacker, simplifier, researcher, architect

