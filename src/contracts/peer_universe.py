from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

PEER_UNIVERSE_CONTRACT_VERSION = "1.0"

W_BIZ = 0.35       # business description similarity
W_METRIC = 0.35    # metric similarity
W_SECTOR = 0.15    # sector/industry match
W_SIZE = 0.15      # size similarity

CORE_THRESHOLD = 0.75
PERIPHERAL_THRESHOLD = 0.55


class InclusionState(str, Enum):
    core = "core"
    peripheral = "peripheral"
    excluded = "excluded"


class ContractModel(BaseModel):
    model_config = {"extra": "ignore", "populate_by_name": True}


class PeerCandidate(ContractModel):
    contract_version: str = PEER_UNIVERSE_CONTRACT_VERSION
    target_ticker: str
    peer_ticker: str
    sources: list[str] = Field(default_factory=list)

    sector_match: bool = False
    industry_match: bool = False

    business_description_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    metric_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    size_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    growth_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    margin_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    capital_intensity_similarity: float = Field(ge=0.0, le=1.0, default=0.0)

    pm_override_state: Literal["included", "excluded", None] = None
    pm_override_reason: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def composite_score(self) -> float:
        sector_score = (
            1.0 if (self.sector_match and self.industry_match)
            else 0.6 if self.sector_match
            else 0.0
        )
        return (
            W_BIZ * self.business_description_similarity
            + W_METRIC * self.metric_similarity
            + W_SECTOR * sector_score
            + W_SIZE * self.size_similarity
        )

    @computed_field  # type: ignore[misc]
    @property
    def inclusion_state(self) -> InclusionState:
        if self.composite_score >= CORE_THRESHOLD:
            return InclusionState.core
        if self.composite_score >= PERIPHERAL_THRESHOLD:
            return InclusionState.peripheral
        return InclusionState.excluded

    @computed_field  # type: ignore[misc]
    @property
    def effective_inclusion(self) -> InclusionState:
        if self.pm_override_state == "included":
            return InclusionState.core
        if self.pm_override_state == "excluded":
            return InclusionState.excluded
        return self.inclusion_state

    @model_validator(mode="after")
    def _uppercase_tickers(self) -> "PeerCandidate":
        object.__setattr__(self, "target_ticker", self.target_ticker.upper().strip())
        object.__setattr__(self, "peer_ticker", self.peer_ticker.upper().strip())
        return self


class PeerUniverse(ContractModel):
    contract_version: str = PEER_UNIVERSE_CONTRACT_VERSION
    target_ticker: str
    candidates: list[PeerCandidate] = Field(default_factory=list)
    build_source: str = "system"
    notes: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def core_peers(self) -> list[str]:
        return [c.peer_ticker for c in self.candidates
                if c.effective_inclusion == InclusionState.core]

    @computed_field  # type: ignore[misc]
    @property
    def peripheral_peers(self) -> list[str]:
        return [c.peer_ticker for c in self.candidates
                if c.effective_inclusion == InclusionState.peripheral]

    @model_validator(mode="after")
    def _uppercase_ticker(self) -> "PeerUniverse":
        object.__setattr__(self, "target_ticker", self.target_ticker.upper().strip())
        return self
