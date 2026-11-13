"""유사 VOC 처리 이력용 임베딩 캐시: 한 번 계산한 문장은 Titan을 다시 부르지 않는다.

배경: 라운드3에서 처리 가능 건마다 같은 메뉴 과거 VOC를 전부 다시 임베딩해
규칙 경로 평균 시간이 3.7s → 12.5s로 늘었다.
"""
import pytest

from src.retrieval import vectorstore
from src.shared import llm


class FakeEmbeddings:
    def __init__(self):
        self.queries, self.docs = [], []

    def embed_query(self, text):
        self.queries.append(text)
        return [1.0, float(len(text))]

    def embed_documents(self, texts):
        self.docs.append(list(texts))
        return [[1.0, float(len(t))] for t in texts]


@pytest.fixture
def fake(monkeypatch):
    f = FakeEmbeddings()
    monkeypatch.setattr(llm, "embeddings", lambda: f)
    vectorstore.clear_embedding_cache()
    yield f
    vectorstore.clear_embedding_cache()


def test_second_call_reuses_cached_embeddings(fake):
    first = vectorstore.embedding_scorer("질문", ["과거1", "과거2"])
    again = vectorstore.embedding_scorer("질문", ["과거1", "과거2"])
    assert first == again
    assert fake.queries == ["질문"] and fake.docs == [["과거1", "과거2"]]


def test_only_new_texts_are_embedded(fake):
    vectorstore.embedding_scorer("질문", ["과거1", "과거2"])
    vectorstore.embedding_scorer("새 질문", ["과거1", "과거2", "과거3"])
    assert fake.docs == [["과거1", "과거2"], ["과거3"]]
    assert fake.queries == ["질문", "새 질문"]


def test_cache_is_bounded(fake, monkeypatch):
    monkeypatch.setattr(vectorstore, "EMBED_CACHE_MAX", 3)
    vectorstore.embedding_scorer("q", ["a", "b", "c", "d"])
    assert len(vectorstore._EMBED_CACHE) <= 3
