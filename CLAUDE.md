# 프로젝트: VOC 접수 판단·응답 보조

과제 제출용 1인 프로젝트. Streamlit 앱(`app.py`), 로직 `voc/`, 메뉴 설정 `config/menus.json`, SQLite `data/voc.db`(모의 데이터만). 판정 흐름 LangGraph(`voc/graph.py`), Claude는 AWS Bedrock(`.env`의 AWS 자격 증명).

## 명령
- 실행: `streamlit run app.py`
- 테스트: `python -m pytest -q` (conftest가 `VOC_USE_LLM=0`으로 Bedrock 미호출, 임시 DB 사용)
- MCP 서버 단독 실행: `python -m voc.mcp_server`
- 라운드 평가(실제 Bedrock, 토큰 사용): `python -m evaluation.run_eval --round N` → `evaluation/roundN_report.md`. 설계 `evaluation/design.md`, 계획 `evaluation/plan.md`

## 규칙
- 정책(1차보다 먼저): `config/menus.json`의 `policies` 표현(예: 해외 법인, 현지 법인, 해외 임직원)이 본문에 있으면 처리 불가 + 고정 문구로 종료(LLM 미호출, match_source='policy'). 국내 임직원 전용 포털이라 해외 법인 임직원 사용·해외 법인 접속 불가. "해외 출장"처럼 법인 언급 없는 문의는 막지 않음.
- 1차: 본문에 메뉴명/별칭 부분 문자열이 있으면 처리 가능. 다중 매칭 시 각 메뉴 누적 +1.
- 2차(LLM 사용 시): 판정 에이전트(create_agent + ToolStrategy(JudgeResult))가 MCP `list_menus`·로컬 `search_similar_vocs`(Titan+Chroma)로 판정. 미등록 메뉴는 버림. 오류 시 3차.
- 3차: 과거 메뉴명 판정 VOC와 bigram 자카드 유사도 ≥ 0.5인 최유사 건의 메뉴를 차용. 2·3차 비교 기준은 match_source='menu' 건만.
- 처리 불가 건은 이력만 저장, 누적 제외. 누적(등록자 무관) 3 이상이면 모의 DB 조회 + 조회 에이전트 요약.
- 안내 문구: LLM 사용 가능하면 Bedrock Claude(10초 타임아웃), 실패·미설정이면 템플릿.
- 개인정보(주민번호·전화·이메일)는 저장·LLM 전달 전에 가림.
- `search_similar_vocs`는 MCP 서버(stdio) 안에서 임베딩·Chroma가 응답하지 않아 로컬 도구로 둠. MCP로 옮기지 말 것.
- 기본 모델 Sonnet 4.6(`global.anthropic.claude-sonnet-4-6`, `VOC_BEDROCK_MODEL`로 변경). 2026-11-12 us-east-1의 Sonnet 4.5 일일 한도 초과로 4.6으로 변경, 평가 라운드도 4.6. 계정 일일 토큰 한도에 걸리면 규칙 모드로 대체되며, 한도는 매일 갱신됨.
- 빈/공백 입력은 경고만 표시하고 저장하지 않음.
- 범위 외 금지: 화면 메뉴 편집, 발표 자료 등. 문서는 README.md, SERVICE.md, 기대값표(`data/sample_vocs_expected.csv`), 평가 폴더(`evaluation/`: 과제 기준·설계·계획·인-아웃 세트·라운드 리포트)만.
- 평가 개선은 판정 쪽(에이전트·검색·가드레일)에서만. 별칭 추가나 평가 정답·`seed_history.csv` 변경으로 점수를 올리지 않음.
- 개인정보는 그래프 실행 전(`run_voc`)에 가림: LangSmith가 그래프 입력을 기록하기 때문.

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

