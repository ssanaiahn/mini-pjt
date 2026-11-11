# SERVICE

## 목적
VOC 접수 담당자가 VOC가 등록 메뉴로 처리 가능한지 빠르게 판단하고, 처리 불가 건에는 안내 문구 초안을, 자주 들어오는 VOC에는 관련 계정·업무 데이터와 요약을 함께 확인하도록 돕는다.

## 기능 흐름 (LangGraph, `voc/graph.py`)
```
validate ─(빈 입력)→ 경고만 표시, 저장 안 함
   │
 guard: 개인정보(주민번호·전화번호·이메일) 가리기
   │
 rule_match: 메뉴명·별칭 포함? ──(예)──────────────────→ record
   │(아니오)
   ├─ LLM 사용 가능 → agent_judge(판정 에이전트) ─(오류)→ similar_fallback
   └─ LLM 사용 불가 ────────────────────────────────→ similar_fallback(글자 유사도)
 agent_judge / similar_fallback ─(처리 가능)→ record
                                 └(처리 불가)→ guidance(안내 문구) → record
 record: 이력 저장·누적 계산 ─(누적 3 이상)→ lookup(모의 DB 조회 + 조회 에이전트 요약)
```
1. Streamlit 화면에서 VOC 본문과 등록자 ID를 한 건씩 입력한다.
2. 둘 중 하나라도 비었거나 공백뿐이면 경고만 표시하고 판정·저장을 하지 않는다.
3. 본문의 개인정보를 가린다. 이후 저장·LLM 전달에는 가린 본문만 쓴다.
4. 판정 규칙(아래)으로 처리 가능 여부와 메뉴를 정한다.
5. 처리 가능: 매칭 메뉴 각각의 누적을 1 증가시키고, 누적이 3 이상이면 모의 DB에서 등록자 계정·업무 데이터를 조회해 표시하고, 조회 에이전트가 담당자용 요약을 쓴다.
6. 처리 불가: 안내 문구 초안을 생성한다(Claude, 판정 근거 반영. 실패·미설정·10초 초과 시 템플릿). 누적에는 포함하지 않는다.
7. 모든 건(처리 불가 포함)을 VOC 이력으로 저장한다.

## 판정 규칙
- 1차(메뉴명): 본문에 `config/menus.json`의 메뉴명 또는 별칭이 부분 문자열로 포함되면 처리 가능. 공백·영문 대소문자는 무시하고, 겹치면 긴 표현을 우선한다.
- 2차(판정 에이전트, LLM 사용 가능 시): Claude 에이전트가 도구로 등록 메뉴(`list_menus`)와 의미가 비슷한 과거 VOC(`search_similar_vocs`, Titan 임베딩 + Chroma)를 확인한 뒤 구조화 출력(처리 가능 여부, 메뉴, 근거)으로 판정한다.
  - 등록되지 않은 메뉴명은 버리고, 남는 메뉴가 없으면 처리 불가.
  - 에이전트 오류·60초 초과 시 3차 규칙으로 대체한다.
- 3차(글자 유사도, LLM 미사용 또는 에이전트 실패 시): 과거 VOC와 글자 2개 묶음(bigram) 자카드 유사도가 0.5 이상인 건 중 가장 유사한 건(동점이면 최근 건)의 메뉴로 처리 가능.
- 2·3차의 비교 기준은 **메뉴명으로** 처리 가능 판정된 과거 VOC만이다. 유사·에이전트 판정 건과 처리 불가 건은 제외해 판정이 번지는 것을 막는다.
- 2개 이상의 메뉴가 매칭되어도 처리 가능이며, 각 메뉴 누적을 1씩 증가시킨다.
- 누적 횟수는 등록자와 무관하게 메뉴별로 전체 합산하며, 현재 VOC 포함 3 이상이면 자주 들어오는 VOC다.

## 에이전트와 도구
| 구분 | 도구 | 실행 위치 | 사용 에이전트 |
|---|---|---|---|
| MCP (`voc/mcp_server.py`, fastmcp stdio) | `list_menus` | MCP 서버 | 판정 |
| | `get_menu_count` | MCP 서버 | 판정, 조회 |
| | `lookup_account` | MCP 서버 | 조회 |
| | `lookup_business_data` | MCP 서버 | 조회 |
| 로컬 LangChain 도구 | `search_similar_vocs` | 앱 프로세스 | 판정 |

- 판정 에이전트: `create_agent` + `ToolStrategy(JudgeResult)`. 결과 형식을 도구 방식으로 받아야 다른 도구를 먼저 호출할 수 있다.
- 조회 에이전트: 자주 들어오는 VOC일 때 계정·업무 데이터·누적 건수를 조회해 3줄 이내로 요약한다.
- 모든 도구는 읽기 전용이다. 저장은 그래프의 `record` 단계만 한다.
- `search_similar_vocs`는 임베딩·Chroma가 stdio MCP 서버 안에서 응답하지 않는 문제가 있어 로컬 도구로 둔다.

## LLM 설정
- AWS Bedrock: 채팅 `global.anthropic.claude-haiku-4-5-20251001-v1:0`(`VOC_BEDROCK_MODEL`로 변경), 임베딩 `amazon.titan-embed-text-v2:0`.
- 사용 조건: AWS 자격 증명(`AWS_ACCESS_KEY_ID` 등, 프로젝트 루트 `.env` 가능)이 있고 `VOC_USE_LLM`이 0이 아님.
- 조건이 안 되면 1차·3차 규칙과 템플릿 문구만으로 동작한다(테스트 기본 모드).

## 데이터 구조
SQLite 파일 하나(`data/voc.db`)가 원본이고, Chroma(`data/chroma/`)는 검색할 때마다 이력과 동기화되는 검색용 사본이다.

| 테이블 | 컬럼 | 설명 |
|---|---|---|
| voc_history | id, registrant_id, voc_text(개인정보 가림), is_processable, matched_menus, guidance_draft, guidance_source, created_at, match_source, similar_voc_id, similarity, judge_reason | VOC 이력(처리 불가 포함). match_source: `menu` / `agent` / `similar` / 비어 있음(처리 불가) |
| voc_menu_matches | voc_id, menu | 처리 가능 건의 메뉴 매칭 기록 |
| menu_counts (뷰) | menu, count | 메뉴별 누적(매칭 기록에서 계산) |
| users | user_id, name, email, grade | 모의 사용자/계정 |
| business_data | id, user_id, menu, title, status | 모의 업무 데이터 |

메뉴 설정: `config/menus.json` (`menus[].name`, `menus[].aliases`).

## 구성
| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit 화면 |
| `voc/graph.py` | LangGraph 판정 흐름 |
| `voc/service.py` | 단계별 함수(규칙 매칭, 글자 유사도, 저장, 누적, 조회) |
| `voc/agent.py` | 판정·조회 에이전트, MCP 클라이언트, 로컬 검색 도구 |
| `voc/mcp_server.py`, `voc/tools.py` | MCP 서버와 도구 로직 |
| `voc/vectorstore.py` | 과거 VOC 의미 검색(Titan + Chroma) |
| `voc/guidance.py` | 안내 문구 |
| `voc/pii.py` | 개인정보 가리기 |
| `voc/llm.py` | Bedrock 설정, `.env` 로딩 |
| `voc/db.py` | SQLite |
