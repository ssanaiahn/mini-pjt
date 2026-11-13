"""체크리스트 3번: 과거 VOC 하이브리드 검색(의미 유사도 + 글자 유사도로 리랭킹)."""
import types

import pytest

from src.retrieval import vectorstore
from src.shared.db import connect, init_db
from src.records.repository import save_voc

MENUS = [{"name": "비밀유지계약", "aliases": ["서약서"]}, {"name": "보안 신고", "aliases": []}]
QUERY = "서약서 제출 현황 알려주세요"


class FakeStore:
    """Chroma 대역: 거리(1-코사인)를 정해 두고, 요청한 k만큼 의미 순으로 돌려준다."""

    def __init__(self, distances):
        self.distances, self.docs, self.asked_k = distances, {}, None

    def get(self, include=None):
        return {"ids": list(self.docs), "metadatas": [self.docs[i] for i in self.docs]}

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)

    def add_texts(self, texts, metadatas, ids):
        self.docs.update(dict(zip(ids, metadatas)))

    def similarity_search_with_score(self, query, k):
        self.asked_k = k
        hits = sorted(self.docs.values(), key=lambda m: self.distances[m["voc_text"]])[:k]
        return [(types.SimpleNamespace(metadata=m), self.distances[m["voc_text"]]) for m in hits]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "v.db")
    init_db(c, reset=True, menus=MENUS)
    for text, menus in [("비밀유지계약 체결 대상 부서 추가", ["비밀유지계약"]),
                        ("서약서 제출 현황 알려주세요 부탁", ["비밀유지계약"]),
                        ("보안 신고 피싱 메일", ["보안 신고"])]:
        save_voc(c, "u001", text, menus, None, None, "menu")
    yield c
    c.close()


def test_hybrid_rerank_lifts_lexical_match(conn, monkeypatch):
    store = FakeStore({"비밀유지계약 체결 대상 부서 추가": 0.20,   # 의미 0.80, 글자 거의 없음
                       "서약서 제출 현황 알려주세요 부탁": 0.25,   # 의미 0.75, 글자 거의 같음
                       "보안 신고 피싱 메일": 0.70})
    monkeypatch.setattr(vectorstore, "_store", lambda path=None: store)
    out = vectorstore.search(conn, QUERY, k=1)
    assert store.asked_k == 2  # 후보를 k의 2배 가져와 다시 정렬
    assert [r["voc_text"] for r in out] == ["서약서 제출 현황 알려주세요 부탁"]
    top = out[0]
    assert top["semantic"] == 0.75 and top["lexical"] > 0.8
    assert top["similarity"] == round(0.7 * 0.75 + 0.3 * top["lexical"], 2)
    assert set(top) == {"id", "voc_text", "menus", "similarity", "semantic", "lexical"}


def test_hybrid_weights_are_documented():
    assert (vectorstore.SEMANTIC_WEIGHT, vectorstore.LEXICAL_WEIGHT) == (0.7, 0.3)
