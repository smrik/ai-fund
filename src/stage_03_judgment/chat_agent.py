from __future__ import annotations

from dataclasses import dataclass, field

from config import LLM_MODEL_FAST
from src.stage_00_data.filing_retrieval import FilingContextBundle
from src.stage_03_judgment.base_agent import BaseAgent


@dataclass
class ChatResponse:
    ticker: str
    query: str
    answer: str
    sources: list[str] = field(default_factory=list)
    error: str | None = None


class ChatAgent(BaseAgent):
    """
    RAG Chatbot agent: answers PM questions heavily grounded 
    in the semantic search results from the SEC filing corpus.
    """

    def __init__(self, model: str = LLM_MODEL_FAST):
        super().__init__(model=model)
        self.system_prompt = """You are a specialized Hedge Fund compliance and research assistant. 
Your ONLY job is to answer the Portfolio Manager's questions using stringently verified text from the provided SEC filings.

CRITICAL RULES:
1. ONLY use the provided extracts to answer the question.
2. If the answer is NOT present in the extracts, you must explicitly state: "I cannot find the answer to this in the retrieved SEC filings."
3. DO NOT hallucinate external knowledge. DO NOT guess.
4. When you state a fact or number, you MUST cite the exact filing and chunk (e.g. "[10-K | 2025-12-31 | mda | chunk 0]").
5. Be concise and professional.
"""

    def answer_query(self, query: str, context_bundle: FilingContextBundle) -> ChatResponse:
        ticker = context_bundle.ticker

        if not context_bundle.selected_chunks:
            return ChatResponse(
                ticker=ticker,
                query=query,
                answer="",
                error="No relevant SEC filing text found to answer this query.",
            )

        prompt_text = f"""PORTFOLIO MANAGER QUERY:
{query}

=======================================
AVAILABLE SEC FILING CONTEXT:
=======================================
{context_bundle.rendered_text}
"""
        try:
            raw_response = self.run(prompt_text)
            
            # Reconstruct list of unique headers for tracing
            sources = []
            for chunk in context_bundle.selected_chunks:
                header = f"[{chunk.form_type} | {chunk.filing_date or 'unknown'} | {chunk.section_key} | chunk {chunk.chunk_index}]"
                if header not in sources:
                    sources.append(header)

            return ChatResponse(
                ticker=ticker,
                query=query,
                answer=raw_response.strip(),
                sources=sources,
            )

        except Exception as e:
            return ChatResponse(
                ticker=ticker,
                query=query,
                answer="",
                error=f"LLM Generation failed: {str(e)}",
            )
