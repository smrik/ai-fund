# XBRL Parsing and RAG Chatbot Implementation

This ExecPlan defines the requirements, design, and steps for adding a Streamlit-based Retrieval-Augmented Generation (RAG) chatbot and structured XBRL parsing to Alpha Pod.

## Purpose / Big Picture

The current filing retrieval pipeline relies on regex to divide SEC text into sections, which is brittle when companies use unconventional formatting. Furthermore, the dashboard currently presents static analysis without allowing the Portfolio Manager (PM) to interrogate the filings dynamically.

This plan solves both problems by:

1. **XBRL Parsing:** Upgrading `edgar_client.py` to properly ingest structured XBRL facts (`companyfacts.json`) and tabular data, replacing regex-based financial number guessing with deterministic, SEC-tagged figures.
2. **RAG Chatbot:** Introducing a new "Chat with Filings" tab in the Streamlit dashboard (`dashboard/app.py`). The chatbot will use the existing `sentence-transformers` embedding layer to perform semantic search over the filing corpus and use the main LLM (Anthropic Claude) to answer PMC queries strictly using SEC sources.

## Interfaces and Dependencies

- **RAG Chatbot:** Will require a new agent in `src/stage_03_judgment/chat_agent.py` to handle the LLM prompt formatting (ensuring no hallucinations). It will interface with `src/stage_00_data/filing_retrieval.py` to embed user queries and fetch the top-K chunks via cosine similarity.
- **Streamlit UI:** Will use `st.chat_message` and `st.chat_input` to maintain a session state conversation history within `dashboard/app.py`.
- **XBRL Parsing:** `src/stage_00_data/edgar_client.py` already implements `get_company_facts`. This will be expanded to dump structured, tagged financial tables into a deterministic dataframe, which will be served to the computation layer and the new Chat Agent as structured context.

## Plan of Work

### Milestone 1: RAG Chatbot Backend (Retrieval & Agent)

1.  **Semantic Search Endpoint:** Add a `query_filing_corpus(ticker, query_text, top_k=5)` function to `filing_retrieval.py` that reads the cached SQLite embeddings, embeds the user query, computes cosine similarity, and returns the top matching chunks.
2.  **Chat Agent:** Create `src/stage_03_judgment/chat_agent.py`. This agent accepts a conversation history and a context block (from step 1), and generates an answer strictly grounded in the SEC text, citing the chunk source.
3.  **Tests:** Write unit tests in `tests/test_chat_agent.py` to verify prompt construction and source rejection (refusing to answer out-of-bounds questions).

### Milestone 2: Streamlit RAG Chatbot UI

1.  **State Management:** Update `dashboard/app.py` session state to include `chat_history`.
2.  **Chat Interface:** Add a new tab `st.tabs(["Valuation", ..., "Chat with Filings"])`.
3.  **Integration:** Wire `st.chat_input` so that it triggers the semantic search endpoint, renders the user's message, invokes the Chat Agent, and streams back the response with source footnotes.
4.  **Acceptance:** Launch dashboard, type a question about a company's "capital expenditures," and verify the chatbot surfaces factual SEC paragraphs.

### Milestone 3: Structured XBRL Ingestion

1.  **XBRL Fetcher:** Expand `edgar_client.py` to aggressively map the `companyfacts.json` GAAP schema (US-GAAP taxonomies for Revenue, Net Income, Operating Cash Flow, etc.) into a sanitized Pandas DataFrame.
2.  **Compute Layer Hand-off:** Expose the parsed XBRL DataFrame to the data layer export (`market_data.py` or a new `xbrl_data.py`).
3.  **Tests:** Add tests in `tests/test_xbrl_parsing.py` mocking an SEC XBRL JSON response to ensure correct tabular alignment.

## Concrete Verification Steps

Once complete, the following commands must pass:

```bash
python -m pytest tests/test_chat_agent.py tests/test_xbrl_parsing.py -v
python -m py_compile dashboard/app.py src/stage_03_judgment/chat_agent.py
```

Finally, the manual verification requires running `python -m streamlit run dashboard/app.py` on a given ticker, navigating to the Chat tab, and submitting a query to verify the pipeline returns a RAG-backed response.
