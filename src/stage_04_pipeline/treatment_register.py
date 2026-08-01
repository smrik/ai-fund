from dataclasses import dataclass
from typing import Literal, Mapping


RevalidationStatus = Literal[
    "revalidated",
    "revalidation_required",
    "contradicted",
]


@dataclass(frozen=True)
class TreatmentRevalidationResult:
    decision_id: int
    status: RevalidationStatus
    queue_required: bool
    reason: str


def assess_treatment_revalidation(
    decision: Mapping[str, object],
    *,
    current_evidence_corpus_hash: str,
    contradiction_reason: str | None = None,
) -> TreatmentRevalidationResult:
    decision_id = int(decision["id"])
    prior_hash = str(decision["evidence_corpus_hash"])

    if contradiction_reason:
        return TreatmentRevalidationResult(
            decision_id=decision_id,
            status="contradicted",
            queue_required=True,
            reason=contradiction_reason,
        )
    if prior_hash == current_evidence_corpus_hash:
        return TreatmentRevalidationResult(
            decision_id=decision_id,
            status="revalidated",
            queue_required=False,
            reason="The evidence corpus is unchanged.",
        )
    return TreatmentRevalidationResult(
        decision_id=decision_id,
        status="revalidation_required",
        queue_required=False,
        reason="The evidence corpus changed; rerun judgment before reusing this treatment.",
    )
