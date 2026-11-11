# SERVICE

## 목적
VOC 접수 담당자가 VOC가 등록 메뉴로 처리 가능한지 빠르게 판단하고, 처리 불가 건에는 안내 문구 초안을, 자주 들어오는 VOC에는 관련 계정·업무 데이터를 함께 확인하도록 돕는다.

## 기능 흐름
1. Streamlit 화면에서 VOC 본문과 등록자 ID를 한 건씩 입력한다.
2. 둘 중 하나라도 비었거나 공백뿐이면 경고만 표시하고 판정·저장을 하지 않는다.
3. 본문에서 등록 메뉴명·별칭을 찾아 처리 가능 여부를 판정한다. 메뉴명이 없으면 과거 VOC 중 비슷한 건을 찾아 그 메뉴로 판정한다.
4. 처리 가능: 매칭 메뉴 각각의 누적 횟수를 1 증가시키고, 누적이 3 이상이면 '자주 들어오는 VOC'로 보고 모의 DB에서 등록자 계정 정보와 매칭 메뉴의 업무 데이터를 조회해 표시한다.
5. 처리 불가: 안내 문구 초안을 생성(Claude API, 실패·키 없음·10초 초과 시 템플릿)하고 누적에는 포함하지 않는다.
6. 모든 건(처리 불가 포함)을 VOC 이력으로 저장한다.

## 판정 규칙
- 1차(메뉴명): 본문에 `config/menus.json`의 메뉴명 또는 별칭이 부분 문자열로 포함되면 처리 가능.
- 2차(과거 VOC 보완): 메뉴명이 없으면, 과거에 **메뉴명으로** 처리 가능 판정된 VOC와 본문 유사도를 계산해 0.5 이상인 건 중 가장 유사한 건(동점이면 최근 건)의 메뉴로 처리 가능 판정한다. 유사도는 공백 제거 후 글자 2개 묶음(bigram) 집합의 자카드 유사도다.
  - 유사 판정으로 처리된 건은 다음 유사 비교의 기준에서 제외한다(유사의 유사로 번지는 것 방지).
  - 처리 불가 건은 비교 대상이 아니다.
- 둘 다 해당하지 않으면 처리 불가.
- 2개 이상의 메뉴가 매칭되어도 처리 가능이며, 매칭 메뉴를 모두 표시하고 각 메뉴 누적을 1씩 증가시킨다.
- 누적 횟수는 등록자와 무관하게 메뉴별로 전체 합산하며, 현재 VOC 포함 3 이상이면 자주 들어오는 VOC다.
- 처리 불가 건은 이력에만 저장하고 누적에서 제외한다.

## 데이터 구조
하나의 SQLite 파일(`data/voc.db`)에 저장한다.

| 테이블 | 컬럼 | 설명 |
|---|---|---|
| voc_history | id, registrant_id, voc_text, is_processable, matched_menus, guidance_draft, guidance_source, created_at, match_source, similar_voc_id, similarity | VOC 이력(처리 불가 포함). match_source: `menu`(메뉴명) / `similar`(과거 VOC 유사) / 비어 있음(처리 불가) |
| menu_counts | menu, count | 메뉴별 처리 가능 VOC 누적 |
| users | user_id, name, email, grade | 모의 사용자/계정 |
| business_data | id, user_id, menu, title, status | 모의 업무 데이터(주문/신청 등) |

메뉴 설정: `config/menus.json` (`menus[].name`, `menus[].aliases`).

## 구성
`app.py`(화면), `voc/service.py`(판정·누적·조회), `voc/db.py`(SQLite), `voc/guidance.py`(안내 문구).
