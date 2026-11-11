# VOC 접수 판단·응답 보조

VOC 본문과 등록자 ID를 입력하면 처리 가능 여부와 메뉴를 판정하는 Streamlit 앱입니다. 처리 불가 건에는 안내 문구 초안을 쓰고, 자주 들어오는 VOC는 관련 데이터를 조회해 보여줍니다. 모의(가상) 데이터만 사용합니다.

- 판정 흐름은 **LangGraph**로 구성했습니다.
- 메뉴명이 없는 VOC는 Claude **판정 에이전트**가 **MCP** 도구와 과거 VOC 의미 검색(**Titan 임베딩 + Chroma**)으로 판단합니다.
- 자세한 규칙은 [SERVICE.md](SERVICE.md)를 참고하세요.

## 설치
```bash
pip install -r requirements.txt
```

## Claude(AWS Bedrock) 설정 (선택)
프로젝트 루트에 `.env` 파일을 만들고 AWS 자격 증명을 넣습니다. 수업 실습의 `.env`와 같은 값입니다.
```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```
- `.env`는 `.gitignore`에 포함되어 있어 GitHub에 올라가지 않습니다.
- 기본 모델은 Claude Sonnet 4.5입니다. 다른 모델을 쓰려면 `VOC_BEDROCK_MODEL`을 지정하세요.
- 자격 증명이 없거나 `VOC_USE_LLM=0`이면 **규칙 모드**로 동작합니다. 규칙 모드는 메뉴명, 글자 유사도, 템플릿 문구만 씁니다.
- Bedrock 호출이 실패하거나 하루 사용량 한도에 걸리면, 그 건만 규칙 모드로 자동 대체됩니다.

## 실행
```bash
streamlit run app.py
```
1. VOC 본문과 등록자 ID(예: `u001`~`u006`)를 입력하고 제출합니다.
2. 화면에 다음이 표시됩니다.
   - 판정 결과
   - 판정 방식과 근거, 에이전트가 사용한 도구, 처리 경로
   - 처리 불가 시 안내 문구
   - 누적 3회 이상 시 조회 결과와 조회 에이전트 요약
3. 데이터는 `data/voc.db`(SQLite)에 저장되어 재시작해도 유지됩니다. 초기화하려면 앱을 끄고 `data/voc.db`와 `data/chroma/`를 지우세요.

MCP 서버는 앱이 필요할 때 자동으로 실행합니다. 서버만 따로 실행하려면 `python -m voc.mcp_server`를 쓰세요.

## 테스트
```bash
python -m pytest -q
```
- 테스트는 Bedrock을 호출하지 않습니다. 기본은 규칙 모드이고, 에이전트·모델이 필요한 테스트는 가짜로 대체합니다.
- MCP 서버는 실제로 실행해 연결을 확인합니다.
- 샘플 VOC 10건의 기대값은 `data/sample_vocs_expected.csv`에 있습니다.

## 설정
메뉴명·별칭은 `config/menus.json`에서 정의합니다(화면 편집 기능 없음).
