import sys
from pathlib import Path

# Add project root to path (REQUIRED)
sys.path.append(str(Path(__file__).resolve().parent.parent))

import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

print("=== ENV CHECK ===")
print(f"ANTHROPIC_API_KEY set: {bool(os.getenv('ANTHROPIC_API_KEY'))}")
print(f"GOOGLE_API_KEY set: {bool(os.getenv('GOOGLE_API_KEY'))}")
print(f"GEMINI_API_KEY set: {bool(os.getenv('GEMINI_API_KEY'))}")
print(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")

from config import LLM_MODEL, LLM_BASE_URL  # noqa: E402
print("\n=== CONFIG ===")
print(f"LLM_MODEL: {LLM_MODEL}")
print(f"LLM_BASE_URL: {LLM_BASE_URL}")

from src.stage_03_judgment.base_agent import BaseAgent  # noqa: E402

# Check the model being used
print("\n=== BASE AGENT CHECK ===")
agent = BaseAgent()
print(f"Model: {agent.model}")
print(f"Client base_url: {agent.client.base_url}")
print(f"Client api_key prefix: {agent.client.api_key[:10] if agent.client.api_key else 'NONE'}...")

from src.stage_03_judgment.industry_agent import IndustryAgent  # noqa: E402

agent = IndustryAgent()
print("\n=== INDUSTRY AGENT ===")
print(f"IndustryAgent model: {agent.model}")
print(f"System prompt: {agent.system_prompt[:100]}...")

print("\n=== Testing research() (force_refresh=True) ===")
try:
    # Add debug: check raw LLM output first
    from src.stage_03_judgment.base_agent import BaseAgent  # noqa: E402
    
    # Test LLM directly
    print("\n=== Direct LLM test ===")
    test_agent = BaseAgent()
    print(f"Using model: {test_agent.model}")
    test_prompt = "Return JSON with exactly these fields: {\"sector\": \"Technology\", \"industry\": \"Semiconductors\", \"week_key\": \"2026-19\", \"consensus_growth_near\": 0.05}"
    raw_result = test_agent.run(test_prompt)
    print(f"Raw LLM response:\n{raw_result[:500]}...")
    
    result = agent.research("Technology", "Semiconductors", force_refresh=True)
    print(f"\nResult: {result}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()