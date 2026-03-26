#!/usr/bin/env python3
"""
AI Hedge Fund — CLI entry point.
Usage: python main.py AAPL
"""

import sys
from rich.console import Console

console = Console()


def main():
    if len(sys.argv) < 2:
        console.print("[bold red]Usage:[/bold red] python main.py <TICKER>")
        console.print("  Example: python main.py AAPL")
        sys.exit(1)

    ticker = sys.argv[1].upper()

    # Lazy import so env vars load first
    from src.stage_04_pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator()
    memo = orchestrator.run(ticker)

    # Print final IC memo to terminal
    console.print(memo.display_summary())

    # Optionally save JSON
    if "--save" in sys.argv:
        import json
        out = f"{ticker}_ic_memo.json"
        with open(out, "w") as f:
            f.write(memo.model_dump_json(indent=2))
        console.print(f"[dim]Saved to {out}[/dim]")


if __name__ == "__main__":
    main()
