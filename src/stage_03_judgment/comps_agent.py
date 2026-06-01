"""CompsAgent -- judgment-layer observations over deterministic comps evidence."""

from __future__ import annotations

import os

from src.contracts.evidence_packet import EvidencePacket, EvidencePacketObservation
from src.stage_03_judgment.agentic_observations import analyze_evidence_packet_with_agent
from src.stage_03_judgment.base_agent import BaseAgent


DEFAULT_COMPS_MODEL = "gemini-3-flash-preview"


SYSTEM_PROMPT = """You are a buy-side valuation analyst reviewing a deterministic peer comps packet.

Use only the provided peer facts, source refs, and snippets. Do not invent peers or multiples.
Your job is to emit anchored observations for PM review, not to directly edit the valuation model."""


class CompsAgent(BaseAgent):
    def __init__(self):
        super().__init__(model=os.getenv("COMPS_AGENT_MODEL", DEFAULT_COMPS_MODEL))
        self.name = "CompsAgent"
        self.system_prompt = SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}

    def analyze_evidence_packet(
        self,
        packet: EvidencePacket,
        profile_name: str = "comps_analysis",
    ) -> list[EvidencePacketObservation]:
        return analyze_evidence_packet_with_agent(
            agent=self,
            packet=packet,
            profile_name=profile_name,
        )
