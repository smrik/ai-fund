from __future__ import annotations

from pydantic import BaseModel, Field


class DossierProfile(BaseModel):
    ticker: str
    company_name: str | None = None
    dossier_root_path: str
    notes_root_path: str
    model_root_path: str
    exports_root_path: str
    status: str = "active"
    current_model_version: str | None = None
    current_thesis_version: str | None = None
    current_publishable_memo_version: str | None = None


class DossierSection(BaseModel):
    ticker: str
    note_slug: str
    note_title: str
    relative_path: str
    section_kind: str
    is_private: int = 0
    content_hash: str | None = None
    metadata_json: str | None = None


class DossierSource(BaseModel):
    ticker: str
    source_id: str
    title: str
    source_type: str


class DossierArtifact(BaseModel):
    ticker: str
    artifact_key: str
    artifact_type: str
    title: str
    path_mode: str
    path_value: str


class ModelCheckpoint(BaseModel):
    ticker: str
    model_version: str
    valuation_json: dict = Field(default_factory=dict)


class ThesisPillar(BaseModel):
    pillar_id: str
    title: str
    description: str
    falsifier: str = ""
    evidence_basis: str = ""


class TrackedCatalyst(BaseModel):
    catalyst_key: str
    title: str
    description: str = ""
    expected_window: str = ""
    importance: str = "medium"


class DecisionLogEntry(BaseModel):
    ticker: str
    decision_title: str
    action: str
    beliefs_text: str


class ReviewLogEntry(BaseModel):
    ticker: str
    review_title: str
    period_type: str
    expectations_vs_outcomes_text: str


class PublishableMemoState(BaseModel):
    ticker: str
    title: str = ""
    summary: str = ""
