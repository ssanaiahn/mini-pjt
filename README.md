# VOC 접수 판단·응답 보조

VOC 본문과 등록자 ID를 입력하면 등록 메뉴명·별칭 기준으로 처리 가능 여부를 규칙 기반으로 판정하는 Streamlit 앱입니다. 모의(가상) 데이터만 사용합니다.

## 설치
```bash
pip install streamlit anthropic pytest
```

## 실행
```bash
streamlit run app.py
```
VOC 본문과 등록자 ID(예: `u001`~`u006`)를 입력하고 제출하면 판정, 안내 문구(처리 불가 시), 모의 DB 조회 결과(누적 3회 이상 시)가 표시됩니다. 데이터는 `data/voc.db`(SQLite)에 저장되어 재시작해도 유지됩니다.

## API 키 설정 (선택)
처리 불가 건의 안내 문구 초안은 Claude API로 생성합니다. 환경변수 `ANTHROPIC_API_KEY`를 설정하세요.

- Windows PowerShell: `$env:ANTHROPIC_API_KEY = "sk-ant-..."`
- macOS/Linux: `export ANTHROPIC_API_KEY=sk-ant-...`

키가 없거나 API 오류, 10초 초과 시 템플릿 문구로 자동 대체됩니다.

## 테스트
```bash
python -m pytest -q
```
테스트는 API 키 없이 템플릿 경로로 실행되며, 임시 SQLite DB를 초기화해 사용합니다. 샘플 VOC 10건의 기대값은 `data/sample_vocs_expected.csv`에 있습니다.

## 설정
메뉴명·별칭은 `config/menus.json`에서 정의합니다(화면 편집 기능 없음).

자세한 판정 규칙과 데이터 구조는 [SERVICE.md](SERVICE.md)를 참고하세요.
