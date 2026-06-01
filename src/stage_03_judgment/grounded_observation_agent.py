"""Single grounded observation runner for the Agentic Handoff MVP."""

from __future__ import annotations

import os

from src.contracts.evidence_packet import EvidencePacket, EvidencePacketObservation
from src.stage_03_judgment.agentic_observations import (
    analyze_evidence_packet_with_agent,
    build_agentic_system_prompt,
)
from src.stage_03_judgment.base_agent import BaseAgent


DEFAULT_GROUNDED_OBSERVATION_MODEL = "gemini-3-flash-preview"


class GroundedObservationAgent(BaseAgent):
    """Profile-agnostic runner over deterministic evidence packets."""

    def __init__(self, profile_name: str, model: str | None = None):
        env_model = os.getenv(
            "GROUNDED_OBSERVATION_AGENT_MODEL",
            DEFAULT_GROUNDED_OBSERVATION_MODEL,
        )
        super().__init__(
            model=model or env_model
        )
        self.name = "GroundedObservationAgent"
        self.profile_name = profile_name
        self.system_prompt = build_agentic_system_prompt(profile_name, self.name)
        self.tools = []
        self.tool_handlers = {}

    def analyze_evidence_packet(
        self,
        packet: EvidencePacket,
        profile_name: str | None = None,
    ) -> list[EvidencePacketObservation]:
        effective_profile_name = profile_name or self.profile_name
        if effective_profile_name != self.profile_name:
            self.profile_name = effective_profile_name
            self.system_prompt = build_agentic_system_prompt(effective_profile_name, self.name)
        return analyze_evidence_packet_with_agent(
            agent=self,
            packet=packet,
            profile_name=effective_profile_name,
        )
