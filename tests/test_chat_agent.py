from __future__ import annotations

import pytest
from src.stage_00_data.filing_retrieval import FilingChunk, FilingContextBundle
from src.stage_03_judgment.chat_agent import ChatAgent

class MockLLMResponse:
    def __init__(self, content: str):
        class Message:
            def __init__(self, content):
                self.content = content
                self.tool_calls = None
                
        class Choice:
            def __init__(self, content):
                self.message = Message(content)
                self.finish_reason = "stop"
                
        self.choices = [Choice(content)]
        self.usage = None


class MockLLMClient:
    def __init__(self, canned_response: str):
        self.canned_response = canned_response
        self.last_prompt = ""

    def create(self, **kwargs) -> MockLLMResponse:
        messages = kwargs.get("messages", [])
        prompt = ""
        for m in messages:
            if m.get("role") == "user":
                prompt = m.get("content", "")
        self.last_prompt = prompt
        return MockLLMResponse(self.canned_response)


@pytest.fixture
def mock_sdk(monkeypatch):
    client = MockLLMClient("Based on the SEC filings, management expects AI capex to increase by 20% next year.")
    
    def mock_create_with_retry(self, **kwargs):
        return client.create(**kwargs)
        
    monkeypatch.setattr("src.stage_03_judgment.base_agent.BaseAgent._create_with_retry", mock_create_with_retry)
    return client


def test_chat_agent_answers_query_with_context(mock_sdk):
    bundle = FilingContextBundle(
        ticker="IBM",
        profile_name="chat_query",
        corpus_hash="123",
        sources=[],
        selected_chunks=[
            FilingChunk(
                form_type="10-K",
                accession_no="1",
                filing_date="2025-12-31",
                section_key="mda",
                chunk_index=0,
                text="In 2026, we expect AI capital expenditures to increase by 20% to support new cloud initiatives.",
                chunk_hash="abc",
            )
        ],
        rendered_text="[10-K | 2025-12-31 | mda | chunk 0]\nIn 2026, we expect AI capital expenditures to increase by 20% to support new cloud initiatives.",
        retrieval_summary={"used_embeddings": True, "selected_chunk_count": 1},
    )

    agent = ChatAgent()
    response = agent.answer_query("What is the expectation for AI capex?", context_bundle=bundle)

    # Check SDK prompt
    assert "In 2026, we expect AI capital expenditures to increase" in mock_sdk.last_prompt
    assert "What is the expectation for AI capex?" in mock_sdk.last_prompt
    
    # Check agent response
    assert response.ticker == "IBM"
    assert response.query == "What is the expectation for AI capex?"
    assert response.answer == "Based on the SEC filings, management expects AI capex to increase by 20% next year."
    assert "10-K | 2025-12-31 | mda | chunk 0" in response.sources[0]


def test_chat_agent_handles_empty_context(mock_sdk):
    bundle = FilingContextBundle(
        ticker="IBM",
        profile_name="chat_query",
        corpus_hash="123",
        sources=[],
        selected_chunks=[],
        rendered_text="",
        retrieval_summary={"used_embeddings": True, "selected_chunk_count": 0},
    )

    agent = ChatAgent()
    response = agent.answer_query("What is the expectation for AI capex?", context_bundle=bundle)
    
    assert response.error is not None
    assert "No relevant SEC filing text" in response.error
    assert response.answer == ""
