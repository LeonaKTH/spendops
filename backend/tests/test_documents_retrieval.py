import asyncio

from app.services.documents import (
    _term_weight,
    _terms,
    search_chunks,
    wants_contracts,
)


def test_chinese_bigrams_and_fillers():
    terms = _terms("火山引擎合同的配额预警线是多少？")

    assert {"火山", "引擎", "合同", "配额", "预警"}.issubset(terms)
    assert "多少" not in terms


def test_ascii_model_names_are_kept_as_tokens():
    terms = _terms("Claude Opus 5.5 与 Kimi K3 的缓存价格")

    assert {"claude", "opus", "5.5", "kimi", "k3"}.issubset(terms)
    assert _term_weight("claude") == 2.0
    assert _term_weight("合同") == 1.0


def test_contract_keywords_route_to_documents():
    assert wants_contracts("火山引擎合同的配额预警线是多少？")
    assert wants_contracts("违约责任怎么约定")
    assert not wants_contracts("2025 年各供应商采购金额是多少？")


class _FakeResult:
    def __init__(self, rows: list[tuple[str, str, int | None, str]]):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[str, str, int | None, str]]):
        self._rows = rows

    async def execute(self, _statement, _params=None):
        return _FakeResult(self._rows)


def test_search_ranks_chunk_with_question_terms_first():
    rows = [
        ("doc-1", "火山引擎合同.docx", 2, "甲方应在配额使用率达到 90% 时启动预警，并通知采购负责人。"),
        ("doc-1", "火山引擎合同.docx", 3, "乙方应在每月 10 日前开具增值税专用发票。"),
        ("doc-2", "OpenAI 合同.pdf", 1, "本合同的付款周期为 30 天。"),
    ]

    hits = asyncio.run(search_chunks(_FakeSession(rows), "配额预警线是多少？"))

    assert hits
    assert hits[0]["page"] == 2
    assert "配额" in str(hits[0]["content"])


def test_search_returns_empty_without_overlap():
    rows = [("doc-1", "合同.docx", 1, "本合同适用中华人民共和国法律。")]
    hits = asyncio.run(search_chunks(_FakeSession(rows), "GPU 算力价格"))
    assert hits == []


def test_search_returns_empty_on_database_error():
    class _BrokenSession:
        async def execute(self, _statement, _params=None):
            raise RuntimeError("documents table missing")

    assert asyncio.run(search_chunks(_BrokenSession(), "配额")) == []
