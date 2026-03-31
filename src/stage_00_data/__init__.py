"""Stage 00: Deterministic data acquisition and adapters.

Keep the package import lazy.

FastAPI loads helpers in worker threads, and eager submodule imports here can
deadlock or leave the package in a partially initialized state on newer Python
runtimes. Callers should import the specific submodule they need.
"""

__all__ = [
    "ciq_adapter",
    "company_descriptions",
    "edgar_client",
    "estimate_tracker",
    "factor_data",
    "filing_retrieval",
    "fred_client",
    "market_data",
    "peer_similarity",
    "sec_filing_metrics",
]
