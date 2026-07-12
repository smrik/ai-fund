import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ProfessionalModelSheetReview } from "@/components/professional-model/ProfessionalModelSheetReview";
import {
  approveProfessionalModelReview,
  getProfessionalModel,
  getProfessionalModelDownloadUrl,
  getRunStatus,
  previewProfessionalModelReview,
  rebuildProfessionalModel,
  rejectProfessionalModelReview,
  signOffProfessionalModel,
} from "@/lib/api";
import { formatCurrency, formatDateLabel } from "@/lib/format";
import { professionalModelTransportIdentitiesEqual } from "@/lib/professionalModel";
import type {
  ProfessionalModelAuditEvent,
  ProfessionalModelBlocker,
  ProfessionalModelBlockerGroup,
  ProfessionalModelCalculationVerification,
  ProfessionalModelDriverValue,
  ProfessionalModelKnownState,
  ProfessionalModelRequirement,
  ProfessionalModelReviewItem,
  ProfessionalModelReviewPreview,
  ProfessionalModelSignoff,
  ProfessionalModelSummaryPayload,
  ProfessionalModelTransportIdentity,
  ProfessionalModelWarning,
  RunPayload,
} from "@/lib/types";

type ProfessionalModelPanelProps = {
  ticker: string;
};

const KNOWN_STATES = new Set<ProfessionalModelKnownState>([
  "UNVERIFIED",
  "BLOCKED",
  "NEEDS_PM_REVIEW",
  "PARTIAL",
  "FULL",
]);

function asKnownState(value: string | null | undefined): ProfessionalModelKnownState | null {
  return value && KNOWN_STATES.has(value as ProfessionalModelKnownState)
    ? (value as ProfessionalModelKnownState)
    : null;
}

function titleize(value: string | null | undefined): string {
  if (!value?.trim()) {
    return "Not supplied";
  }
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function displayValue(value: unknown): string {
  if (value == null || value === "") {
    return "Not supplied";
  }
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  return String(value);
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value?.trim()) {
    return "Not supplied";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(parsed);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown professional-model request failure.";
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
    : [];
}

function reviewContractEvidence(summary: ProfessionalModelSummaryPayload) {
  const raw = summary.review_contract;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      raw: null,
      status: null,
      issues: ["Review contract metadata was not supplied by the backend."],
      valid: false,
    };
  }
  const record = raw as Record<string, unknown>;
  const issues = [
    ...stringArray(record.contract_issues),
    ...stringArray(record.issues),
    ...stringArray(record.reasons),
  ].filter((item, index, values) => values.indexOf(item) === index);
  const explicitlyInvalid =
    record.compatible === false ||
    record.approvable === false ||
    record.regeneration_required === true;
  return {
    raw: record,
    status: typeof record.status === "string" ? record.status : null,
    issues,
    valid: !explicitlyInvalid,
  };
}

function readinessContractIssues(
  summary: ProfessionalModelSummaryPayload,
  knownState: ProfessionalModelKnownState | null,
): string[] {
  const issues: string[] = [];
  if (!knownState) {
    issues.push(
      summary.state?.trim()
        ? `Unknown readiness state: ${summary.state}.`
        : "Readiness state is missing.",
    );
  }
  if (typeof summary.decision_ready !== "boolean") {
    issues.push("decision_ready is missing or is not a boolean.");
  } else if (knownState === "FULL" && summary.decision_ready !== true) {
    issues.push("Contradictory readiness: FULL requires decision_ready=true.");
  } else if (knownState && knownState !== "FULL" && summary.decision_ready !== false) {
    issues.push(`${knownState} requires decision_ready=false.`);
  }
  if (!summary.transport_identity) {
    issues.push("The atomic model_run_id and seven-field hash identity is unavailable.");
  }
  return issues.filter((item, index, values) => values.indexOf(item) === index);
}

function reviewActionContractIssues(summary: ProfessionalModelSummaryPayload): string[] {
  const reviewContract = reviewContractEvidence(summary);
  if (reviewContract.valid) {
    return [];
  }
  return reviewContract.issues.length
    ? reviewContract.issues
    : ["The backend review contract is incompatible or requires regeneration."];
}
function calculationStatus(
  verification: ProfessionalModelCalculationVerification | string | null | undefined,
): string {
  if (typeof verification === "string") {
    return verification || "Not supplied";
  }
  if (!verification) {
    return "Not supplied";
  }
  if (verification.state?.trim()) {
    return verification.state;
  }
  if (verification.status?.trim()) {
    return verification.status;
  }
  if (verification.verified === true) {
    return "VERIFIED";
  }
  if (verification.verified === false) {
    return "NOT_VERIFIED";
  }
  return "Not supplied";
}

function normalizeBlocker(value: ProfessionalModelBlocker | string): ProfessionalModelBlocker {
  return typeof value === "string" ? { reason_code: value } : value;
}

function blockerGroups(summary: ProfessionalModelSummaryPayload): ProfessionalModelBlockerGroup[] {
  const supplied = summary.blocker_groups;
  if (Array.isArray(supplied)) {
    return supplied;
  }
  if (supplied && typeof supplied === "object") {
    return Object.entries(supplied).map(([category, blockers]) => ({
      category,
      blockers: blockers.map(normalizeBlocker),
      count: blockers.length,
    }));
  }
  if (summary.blockers?.length) {
    return [
      {
        category: "other",
        label: "Other",
        blockers: summary.blockers.map(normalizeBlocker),
        count: summary.blockers.length,
      },
    ];
  }
  return [];
}

function StructuredValue({ value }: { value: unknown }) {
  if (value == null || value === "") {
    return <span className="table-note">Not supplied by the backend.</span>;
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return <span className="table-note">No entries supplied by the backend.</span>;
    }
    return (
      <ul className="clean-list professional-model-structured-list">
        {value.map((item, index) => (
          <li key={index}>
            <StructuredValue value={item} />
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) {
      return <span className="table-note">No fields supplied by the backend.</span>;
    }
    return (
      <dl className="professional-model-key-values">
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{titleize(key)}</dt>
            <dd>
              <StructuredValue value={item} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{displayValue(value)}</span>;
}

function StatusText({ value }: { value: string | null | undefined }) {
  return <span className="professional-model-status-text">{titleize(value)}</span>;
}

function HashValue({ value }: { value: string | number | null | undefined }) {
  return <code className="professional-model-hash">{displayValue(value)}</code>;
}

function ReadinessHeader({
  summary,
  knownState,
  groups,
  contractIssues,
}: {
  summary: ProfessionalModelSummaryPayload;
  knownState: ProfessionalModelKnownState | null;
  groups: ProfessionalModelBlockerGroup[];
  contractIssues: string[];
}) {
  const artifact = summary.artifact;
  const blockerCount = groups.reduce(
    (total, group) => total + (group.count ?? group.blockers.length),
    0,
  );
  const calculation = summary.calculation_verification;
  const calculationState = calculationStatus(calculation);
  const calculationMessage =
    typeof calculation === "object" && calculation ? calculation.message : null;
  const calculationEngine =
    typeof calculation === "object" && calculation ? calculation.engine : null;
  const verifiedAt =
    artifact?.verified_at ??
    (typeof calculation === "object" && calculation ? calculation.verified_at : null);

  return (
    <section className="panel professional-model-readiness" aria-labelledby="professional-model-readiness-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Backend readiness truth</p>
          <h2 id="professional-model-readiness-title">Professional Model Readiness</h2>
          <p>{summary.decision_readiness || "Decision-readiness language was not supplied by the backend."}</p>
        </div>
        <div className="professional-model-readiness-state">
          <strong
            className={`professional-model-state${knownState ? ` is-${knownState.toLowerCase().split("_").join("-")}` : " is-unknown"}`}
            data-testid="professional-model-state"
            data-value={String(summary.state ?? "")}
          >
            {summary.state || "MISSING STATE"}
          </strong>
          <span
            data-testid="professional-model-decision-ready"
            data-value={String(summary.decision_ready ?? "")}
          >
            {summary.decision_ready === true
              ? "Decision ready"
              : summary.decision_ready === false
                ? "Not decision ready"
                : "Decision readiness missing"}
          </span>
        </div>
      </div>

      {contractIssues.length ? (
        <div className="run-status error" role="alert" data-testid="professional-model-contract-error">
          <strong>Readiness contract is invalid. All professional-model actions are disabled.</strong>
          <ul className="clean-list">
            {contractIssues.map((issue) => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      ) : null}
      <div className="professional-model-identity-grid">
        <article className="mini-card">
          <strong>Model run ID</strong>
          <p
            data-testid="professional-model-source-run-id"
            data-value={String(summary.transport_identity?.model_run_id ?? "")}
          >
            <HashValue value={summary.transport_identity?.model_run_id} />
          </p>
        </article>
        <article className="mini-card">
          <strong>Source hash</strong>
          <p
            data-testid="professional-model-source-hash"
            data-value={String(artifact?.source_hash ?? "")}
          >
            <HashValue value={artifact?.source_hash} />
          </p>
        </article>
        <article className="mini-card">
          <strong>Workbook hash</strong>
          <p
            data-testid="professional-model-workbook-hash"
            data-value={String(artifact?.workbook_hash ?? "")}
          >
            <HashValue value={artifact?.workbook_hash} />
          </p>
        </article>
        <article className="mini-card">
          <strong>Calculation verification</strong>
          <p
            data-testid="professional-model-calculation-status"
            data-value={calculationState}
          >
            {calculationState}
          </p>
          {calculationEngine ? <span>Engine: {calculationEngine}</span> : null}
          {calculationMessage ? <span>{calculationMessage}</span> : null}
        </article>
        <article className="mini-card">
          <strong>Active blockers</strong>
          <p
            data-testid="professional-model-blocker-count"
            data-value={String(blockerCount)}
          >
            {blockerCount}
          </p>
        </article>
        <article className="mini-card">
          <strong>Last build</strong>
          <p>{formatTimestamp(artifact?.built_at)}</p>
          {artifact?.build_run_id != null ? <span>Run {artifact.build_run_id}</span> : null}
        </article>
        <article className="mini-card">
          <strong>Last verification</strong>
          <p>{formatTimestamp(verifiedAt)}</p>
        </article>
        <article className="mini-card">
          <strong>Artifact filename</strong>
          <p>{artifact?.filename || "Not supplied"}</p>
          {artifact?.size_bytes != null ? <span>{artifact.size_bytes.toLocaleString()} bytes</span> : null}
        </article>
      </div>
    </section>
  );
}

function hasBackendValue(value: unknown): boolean {
  if (value == null || value === "") {
    return false;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 0;
  }
  return true;
}

function DecisionUnavailable({ label }: { label: string }) {
  return (
    <div className="professional-model-empty" data-testid={"decision-unavailable-" + label.toLowerCase().replace(/s+/g, "-")}>
      <strong>{label} unavailable.</strong>
      <span>The backend did not provide this field in decision_useful; the frontend does not derive it.</span>
    </div>
  );
}

function DecisionSnapshot({ summary }: { summary: ProfessionalModelSummaryPayload }) {
  const decision = summary.decision_useful;
  const scenarios = decision?.scenario_valuations ?? [];
  const forecast = decision?.forecast_path ?? [];
  const priceAvailable = decision?.current_price != null;

  return (
    <section className="panel professional-model-decision" aria-labelledby="professional-model-decision-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Decision-useful backend output only</p>
          <h2 id="professional-model-decision-title">Model Decision Snapshot</h2>
          <p>Every value in this section comes only from decision_useful. Missing fields stay explicitly unavailable.</p>
        </div>
        <div className="professional-model-spot-price" aria-label="Backend current price">
          <strong>{priceAvailable ? formatCurrency(decision?.current_price) : "Current price unavailable"}</strong>
          <span>{priceAvailable ? decision?.current_price_source || "Price source unavailable" : "Price not supplied"}</span>
          <span>
            {priceAvailable && decision?.current_price_as_of
              ? formatDateLabel(decision.current_price_as_of)
              : "Price as-of unavailable"}
          </span>
        </div>
      </div>

      {!decision ? (
        <div className="run-status error" role="status">
          <strong>decision_useful was not supplied.</strong>
          <span>All six decision sections below remain unavailable; no other payload fields are substituted.</span>
        </div>
      ) : null}

      {!priceAvailable ? <DecisionUnavailable label="Current price" /> : null}

      <section aria-labelledby="professional-model-scenarios-title">
        <h3 id="professional-model-scenarios-title">Scenario valuations</h3>
        {scenarios.length ? (
          <div className="grid-cards professional-model-scenarios">
            {scenarios.map((scenario, index) => (
              <article key={scenario.scenario + "-" + index} className="mini-card">
                <strong>{scenario.scenario || "Unlabeled scenario"}</strong>
                <p>{displayValue(scenario.value_per_share)}</p>
                <span>State: {titleize(scenario.state)}</span>
                <span>Current price: {displayValue(scenario.current_price)}</span>
                <span>Upside: {displayValue(scenario.upside_pct)}</span>
              </article>
            ))}
          </div>
        ) : (
          <DecisionUnavailable label="Scenario valuations" />
        )}
      </section>

      <section aria-labelledby="professional-model-forecast-title">
        <h3 id="professional-model-forecast-title">Forecast path</h3>
        {forecast.length ? (
          <div
            className="table-shell professional-model-forecast-table"
            role="region"
            aria-label="Revenue, margin, EPS, and FCFF forecast path"
            tabIndex={0}
          >
            <table className="data-table">
              <caption className="sr-only">Backend-supplied model forecast path</caption>
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col">Type</th>
                  <th scope="col">Revenue</th>
                  <th scope="col">EBIT margin</th>
                  <th scope="col">EPS</th>
                  <th scope="col">FCFF</th>
                </tr>
              </thead>
              <tbody>
                {forecast.map((point, index) => (
                  <tr key={String(point.period) + "-" + index}>
                    <th scope="row">{displayValue(point.period)}</th>
                    <td>{titleize(point.period_type)}</td>
                    <td>{displayValue(point.revenue)}</td>
                    <td>{displayValue(point.ebit_margin)}</td>
                    <td>{displayValue(point.eps)}</td>
                    <td>{displayValue(point.fcff)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <DecisionUnavailable label="Forecast path" />
        )}
      </section>

      <div className="grid-cards professional-model-decision-cards">
        <article className="mini-card">
          <strong>What price implies</strong>
          {hasBackendValue(decision?.what_price_implies) ? (
            <StructuredValue value={decision?.what_price_implies} />
          ) : (
            <DecisionUnavailable label="What price implies" />
          )}
        </article>
        <article className="mini-card">
          <strong>Variant estimate gap</strong>
          {hasBackendValue(decision?.variant_estimate_gap) ? (
            <StructuredValue value={decision?.variant_estimate_gap} />
          ) : (
            <DecisionUnavailable label="Variant estimate gap" />
          )}
        </article>
        <article className="mini-card">
          <strong>Downside mechanism</strong>
          {hasBackendValue(decision?.downside_mechanism) ? (
            <StructuredValue value={decision?.downside_mechanism} />
          ) : (
            <DecisionUnavailable label="Downside mechanism" />
          )}
        </article>
      </div>
    </section>
  );
}

function BackendEvidence({ summary }: { summary: ProfessionalModelSummaryPayload }) {
  const semanticQa = (
    summary as ProfessionalModelSummaryPayload & {
      decision_semantic_qa_verification?: unknown;
    }
  ).decision_semantic_qa_verification;
  const reviewContract = reviewContractEvidence(summary);

  return (
    <section className="panel professional-model-evidence" aria-labelledby="professional-model-evidence-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Supporting backend evidence</p>
          <h2 id="professional-model-evidence-title">Backend Evidence and Controls</h2>
          <p>Diagnostics and controls are evidence; they are not substituted into the Decision Snapshot.</p>
        </div>
      </div>

      <div className="grid-cards professional-model-diagnostics">
        <article className="mini-card">
          <strong>Valuation diagnostics</strong>
          <StructuredValue value={summary.valuation_diagnostics} />
        </article>
        <article className="mini-card">
          <strong>Valuation bridge</strong>
          <StructuredValue value={summary.bridge} />
        </article>
        <article className="mini-card">
          <strong>Accounting and integrity</strong>
          <StructuredValue value={summary.integrity} />
        </article>
        <article className="mini-card">
          <strong>Decision semantic QA</strong>
          <StructuredValue value={semanticQa} />
        </article>
        <article className="mini-card">
          <strong>Review contract</strong>
          <p>Status: {titleize(reviewContract.status)}</p>
          {reviewContract.issues.length ? (
            <ul className="clean-list">
              {reviewContract.issues.map((issue) => <li key={issue}>{issue}</li>)}
            </ul>
          ) : null}
          <StructuredValue value={reviewContract.raw} />
        </article>
      </div>

      <section className="professional-model-checks" aria-labelledby="professional-model-checks-title">
        <h3 id="professional-model-checks-title">Backend checks</h3>
        {summary.checks?.length ? (
          <div className="table-shell" role="region" aria-label="Professional model checks" tabIndex={0}>
            <table className="data-table">
              <caption className="sr-only">Backend professional-model checks and tolerances</caption>
              <thead>
                <tr>
                  <th scope="col">Check</th>
                  <th scope="col">Status</th>
                  <th scope="col">Difference / count</th>
                  <th scope="col">Tolerance / expected</th>
                  <th scope="col">Message</th>
                </tr>
              </thead>
              <tbody>
                {summary.checks.map((check) => (
                  <tr key={check.check_id}>
                    <th scope="row"><code>{check.check_id}</code></th>
                    <td><StatusText value={check.status} /></td>
                    <td>{displayValue(check.difference_or_count)}</td>
                    <td>{displayValue(check.tolerance_or_expected)}</td>
                    <td>{check.message || "Not supplied"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="table-note">No check rows supplied by the backend.</p>
        )}
      </section>
    </section>
  );
}
function RequirementChecklist({
  requirements,
  onOpenSheet,
}: {
  requirements: ProfessionalModelRequirement[];
  onOpenSheet: (sheet: string) => void;
}) {
  return (
    <section className="panel professional-model-requirements" aria-labelledby="professional-model-requirements-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Every readiness gate</p>
          <h2 id="professional-model-requirements-title">Full-State Checklist</h2>
          <p>Each backend requirement remains visible regardless of its current status.</p>
        </div>
        <strong>{requirements.length} requirements</strong>
      </div>

      {requirements.length ? (
        <ol className="professional-model-requirement-list">
          {requirements.map((requirement) => (
            <li key={requirement.requirement_id}>
              <article className="mini-card">
                <div className="professional-model-requirement-heading">
                  <div>
                    <code>{requirement.requirement_id}</code>
                    <h3>{requirement.label}</h3>
                  </div>
                  <StatusText value={requirement.status} />
                </div>
                <dl className="professional-model-key-values">
                  <div>
                    <dt>Owner</dt>
                    <dd>{requirement.owner || "Not supplied"}</dd>
                  </div>
                  <div>
                    <dt>Explanation</dt>
                    <dd>{requirement.explanation || "Not supplied"}</dd>
                  </div>
                  <div>
                    <dt>Remediation</dt>
                    <dd>{requirement.remediation || "Not supplied"}</dd>
                  </div>
                </dl>
                {requirement.sheet ? (
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => onOpenSheet(requirement.sheet as string)}
                  >
                    {requirement.action_label || `Open ${requirement.sheet}`}
                  </button>
                ) : requirement.action_href ? (
                  <a className="ghost-button" href={requirement.action_href}>
                    {requirement.action_label || "Open remediation"}
                  </a>
                ) : null}
              </article>
            </li>
          ))}
        </ol>
      ) : (
        <div className="professional-model-empty">
          <strong>No requirements supplied by the backend.</strong>
          <span>Full-state readiness cannot be independently reconstructed in the frontend.</span>
        </div>
      )}
    </section>
  );
}

function warningParts(value: ProfessionalModelWarning | string) {
  return typeof value === "string"
    ? { code: value, message: null, severity: null }
    : value;
}

function BlockerWorkbench({
  groups,
  warnings,
  blockerDataSupplied,
}: {
  groups: ProfessionalModelBlockerGroup[];
  warnings: Array<ProfessionalModelWarning | string>;
  blockerDataSupplied: boolean;
}) {
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set());
  return (
    <section className="panel professional-model-blockers" aria-labelledby="professional-model-blockers-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Collapsed by backend group</p>
          <h2 id="professional-model-blockers-title">Blocker Workbench</h2>
          <p>Expand a group to review exact reason codes, owners, and remediation.</p>
        </div>
      </div>

      {groups.length ? (
        <div className="professional-model-blocker-groups">
          {groups.map((group, groupIndex) => (
            <div key={`${group.category}-${groupIndex}`}>
              <button
                type="button"
                className="professional-model-blocker-summary"
                aria-expanded={openGroups.has(`${group.category}-${groupIndex}`)}
                onClick={() =>
                  setOpenGroups((current) => {
                    const next = new Set(current);
                    const key = `${group.category}-${groupIndex}`;
                    next.has(key) ? next.delete(key) : next.add(key);
                    return next;
                  })
                }
              >
                <span>{group.label || titleize(group.category)}</span>
                <strong>{group.count ?? group.blockers.length}</strong>
              </button>
              {openGroups.has(`${group.category}-${groupIndex}`) && group.blockers.length ? (
                <ul className="professional-model-blocker-list">
                  {group.blockers.map((blocker, index) => (
                    <li key={`${blocker.reason_code}-${index}`}>
                      <div>
                        <code>{blocker.reason_code}</code>
                        <StatusText value={blocker.severity} />
                        {blocker.sheet ? <span>{blocker.sheet}{blocker.cell ? `!${blocker.cell}` : ""}</span> : null}
                      </div>
                      <p>{blocker.message || "No blocker explanation supplied."}</p>
                      <small>Owner: {blocker.owner || "Not supplied"}</small>
                      <small>Remediation: {blocker.remediation || "Not supplied"}</small>
                    </li>
                  ))}
                </ul>
              ) : openGroups.has(`${group.category}-${groupIndex}`) ? (
                <p className="table-note">The backend reported this group count without blocker details.</p>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="table-note">
          {blockerDataSupplied ? "The backend returned no active blocker groups." : "No blocker data was supplied by the backend."}
        </p>
      )}

      <section className="professional-model-warnings" aria-labelledby="professional-model-warnings-title">
        <h3 id="professional-model-warnings-title">Warnings</h3>
        {warnings.length ? (
          <ul className="clean-list">
            {warnings.map((warning, index) => {
              const parts = warningParts(warning);
              return (
                <li key={`${parts.code}-${index}`}>
                  <code>{parts.code}</code>
                  {parts.severity ? ` · ${titleize(parts.severity)}` : ""}
                  {parts.message ? ` · ${parts.message}` : ""}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="table-note">No warnings supplied by the backend.</p>
        )}
      </section>
    </section>
  );
}

function DriverTable({ drivers, caption }: { drivers: ProfessionalModelDriverValue[]; caption: string }) {
  if (!drivers.length) {
    return <p className="table-note">No driver values supplied by the backend.</p>;
  }
  return (
    <div className="table-shell" role="region" aria-label={caption} tabIndex={0}>
      <table className="data-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Driver</th>
            <th scope="col">Value</th>
            <th scope="col">Unit</th>
            <th scope="col">Forecast period</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        <tbody>
          {drivers.map((driver, index) => (
            <tr key={(driver.driver_key || "driver") + "-" + (driver.period || "unlabeled") + "-" + index}>
              <th scope="row">{driver.label || driver.driver_key || "Driver label unavailable"}</th>
              <td>{displayValue(driver.value)}</td>
              <td>{driver.unit || "Unit unavailable"}</td>
              <td>{driver.period || "Period label unavailable"}</td>
              <td><HashValue value={driver.source_ref} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function reviewRowIssues(review: ProfessionalModelReviewItem): string[] {
  const issues = [...(review.contract_issues ?? [])];
  const periods = review.forecast_periods ?? [];
  if (review.contract_valid !== true) {
    issues.push("The backend did not affirm contract_valid=true for this approval row.");
  }
  if (!review.review_id?.trim()) {
    issues.push("Approval key is missing.");
  }
  if (!review.scenario?.trim() || /^unknown/i.test(review.scenario.trim())) {
    issues.push("Scenario label is missing or unknown.");
  }
  if (!review.driver_key?.trim()) {
    issues.push("Driver key is missing.");
  }
  if (
    periods.length !== 5 ||
    periods.some((period) => !period?.trim()) ||
    new Set(periods.map((period) => period.trim())).size !== periods.length
  ) {
    issues.push("Exactly five unique backend forecast-period labels are required.");
  }
  return issues.filter((item, index, values) => values.indexOf(item) === index);
}

function numericPathValue(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "Unavailable" : String(value);
}

function ReviewPathEditor({
  review,
  draftValues,
  disabled,
  onReviewedValue,
}: {
  review: ProfessionalModelReviewItem;
  draftValues: string[];
  disabled: boolean;
  onReviewedValue: (reviewId: string, index: number, value: string) => void;
}) {
  const periods = review.forecast_periods ?? [];
  if (periods.length !== 5 || periods.some((period) => !period?.trim())) {
    return (
      <div className="run-status error" role="alert">
        <strong>Forecast labels unavailable or invalid.</strong>
        <span>This row is visible for audit, but values cannot be edited or previewed without five exact backend labels.</span>
      </div>
    );
  }

  return (
    <fieldset className="professional-model-driver-path">
      <legend>Backend-labeled current, proposed, and edited path</legend>
      <div className="table-shell" role="region" aria-label={review.scenario + " path comparison"} tabIndex={0}>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Forecast period</th>
              <th scope="col">Current artifact</th>
              <th scope="col">Backend proposal</th>
              <th scope="col">Approved event</th>
              <th scope="col">Applied workbook</th>
              <th scope="col">Edited value</th>
              <th scope="col">Edited minus current</th>
            </tr>
          </thead>
          <tbody>
            {periods.map((period, index) => {
              const current = review.artifact_current_path?.[index];
              const proposed = review.proposed_path?.[index];
              const approved = review.approved_path?.[index];
              const applied = review.applied_path?.[index];
              const editedText = draftValues[index] ?? "";
              const edited = editedText.trim() ? Number(editedText) : Number.NaN;
              const delta =
                current != null && Number.isFinite(current) && Number.isFinite(edited)
                  ? edited - current
                  : null;
              return (
                <tr key={period}>
                  <th scope="row">{period}</th>
                  <td>{numericPathValue(current)}</td>
                  <td>{numericPathValue(proposed)}</td>
                  <td>{numericPathValue(approved)}</td>
                  <td>{numericPathValue(applied)}</td>
                  <td>
                    <label className="sr-only" htmlFor={"professional-model-value-" + review.review_id + "-" + index}>
                      {review.scenario + " " + period + " reviewed value"}
                    </label>
                    <input
                      id={"professional-model-value-" + review.review_id + "-" + index}
                      type="number"
                      step="any"
                      value={editedText}
                      onChange={(event) => onReviewedValue(review.review_id, index, event.target.value)}
                      aria-label={review.scenario + " " + period + " reviewed value"}
                      disabled={disabled}
                    />
                  </td>
                  <td>{delta == null ? "Unavailable" : String(delta)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </fieldset>
  );
}

function AuditHistory({
  events,
  total,
  returned,
  truncated,
}: {
  events: ProfessionalModelAuditEvent[];
  total?: number | null;
  returned?: number | null;
  truncated?: boolean;
}) {
  return (
    <section className="professional-model-history" aria-labelledby="professional-model-history-title">
      <div className="professional-model-section-heading">
        <div>
          <h3 id="professional-model-history-title">Approval event history</h3>
          <p>Backend events preserve rationale, identity, time, stale state, and supersession.</p>
        </div>
        <span className="table-note">
          {total == null ? "Total unavailable" : String(total) + " total"} ? {returned == null ? events.length : returned} returned
          {truncated ? " ? truncated by backend" : ""}
        </span>
      </div>
      {events.length ? (
        <ol className="professional-model-requirement-list">
          {events.map((event, index) => (
            <li key={event.event_id == null ? "event-" + index : String(event.event_id)}>
              <article className="mini-card">
                <div className="professional-model-review-heading">
                  <div>
                    <strong>{titleize(event.event_type)} ? {titleize(event.state)}</strong>
                    <code>{event.approval_key || "Approval key unavailable"}</code>
                  </div>
                  <div>
                    {event.stale ? <span className="professional-model-stale">Stale</span> : null}
                    {event.superseded ? <span className="professional-model-stale">Superseded</span> : null}
                  </div>
                </div>
                <dl className="professional-model-key-values">
                  <div><dt>Event ID</dt><dd>{displayValue(event.event_id)}</dd></div>
                  <div><dt>Model run ID</dt><dd>{displayValue(event.model_run_id)}</dd></div>
                  <div><dt>Scope</dt><dd>{displayValue(event.approval_scope)}</dd></div>
                  <div><dt>Actor</dt><dd>{event.actor || "Actor unavailable"}</dd></div>
                  <div><dt>Time</dt><dd>{formatTimestamp(event.created_at)}</dd></div>
                  <div><dt>Rationale</dt><dd>{event.rationale || "Rationale unavailable"}</dd></div>
                  <div><dt>Reviewed-value fingerprint</dt><dd><HashValue value={event.reviewed_value_fingerprint} /></dd></div>
                  <div><dt>Source hash</dt><dd><HashValue value={event.source_hash} /></dd></div>
                  <div><dt>Input hash</dt><dd><HashValue value={event.input_hash} /></dd></div>
                  <div><dt>Result hash</dt><dd><HashValue value={event.result_hash} /></dd></div>
                  <div><dt>Workbook hash</dt><dd><HashValue value={event.workbook_hash} /></dd></div>
                </dl>
                {event.reviewed_values?.length ? (
                  <p>Reviewed values: {event.reviewed_values.map(displayValue).join(", ")}</p>
                ) : null}
                {event.stale_reasons?.length ? (
                  <div className="run-status error">
                    <strong>Stale reasons</strong>
                    <ul className="clean-list">
                      {event.stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  </div>
                ) : null}
              </article>
            </li>
          ))}
        </ol>
      ) : (
        <div className="professional-model-empty">
          <strong>No audit events supplied.</strong>
          <span>Actor, rationale, time, and identity history are unavailable.</span>
        </div>
      )}
    </section>
  );
}

function SignoffEvidence({ signoff }: { signoff: ProfessionalModelSignoff | null | undefined }) {
  const extraIdentity =
    signoff && typeof signoff === "object"
      ? (signoff as unknown as Record<string, unknown>).approval_artifact_identity
      : null;
  return (
    <section className="professional-model-signoff-evidence" aria-labelledby="professional-model-signoff-evidence-title">
      <h3 id="professional-model-signoff-evidence-title">Current sign-off evidence</h3>
      {signoff ? (
        <article className="mini-card">
          <dl className="professional-model-key-values">
            <div><dt>Status</dt><dd>{titleize(signoff.status)}</dd></div>
            <div><dt>Current</dt><dd>{displayValue(signoff.current)}</dd></div>
            <div><dt>Event ID</dt><dd>{displayValue(signoff.event_id)}</dd></div>
            <div><dt>Actor</dt><dd>{signoff.actor || "Actor unavailable"}</dd></div>
            <div><dt>Signed at</dt><dd>{formatTimestamp(signoff.signed_at)}</dd></div>
            <div><dt>Workbook hash</dt><dd><HashValue value={signoff.workbook_hash} /></dd></div>
          </dl>
          <div>
            <strong>Sign-off artifact identity</strong>
            <StructuredValue value={extraIdentity} />
          </div>
          {signoff.stale_reasons?.length ? (
            <div className="run-status error">
              <strong>Stale sign-off</strong>
              <ul className="clean-list">
                {signoff.stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            </div>
          ) : null}
        </article>
      ) : (
        <p className="table-note">No sign-off identity was supplied by the backend.</p>
      )}
    </section>
  );
}
type ApprovalWorkbenchProps = {
  summary: ProfessionalModelSummaryPayload;
  contractValid: boolean;
  artifactHash: string;
  reviewer: string;
  activePreview: ProfessionalModelReviewPreview | null;
  confirmed: boolean;
  reviewedValues: Record<string, string[]>;
  reviewRationales: Record<string, string>;
  rejectReasons: Record<string, string>;
  signoffRationale: string;
  previewPendingId: string | null;
  approvePendingId: string | null;
  rejectPendingId: string | null;
  signoffPermitted: boolean;
  signoffPending: boolean;
  onReviewer: (value: string) => void;
  onPreview: (review: ProfessionalModelReviewItem, values: number[]) => void;
  onReviewedValue: (reviewId: string, index: number, value: string) => void;
  onReviewRationale: (reviewId: string, rationale: string) => void;
  onConfirm: (confirmed: boolean) => void;
  onApprove: (review: ProfessionalModelReviewItem) => void;
  onRejectReason: (reviewId: string, reason: string) => void;
  onReject: (review: ProfessionalModelReviewItem) => void;
  onSignoffRationale: (value: string) => void;
  onSignoff: () => void;
};

function ApprovalWorkbench({
  summary,
  contractValid,
  artifactHash,
  reviewer,
  activePreview,
  confirmed,
  reviewedValues,
  reviewRationales,
  rejectReasons,
  signoffRationale,
  previewPendingId,
  approvePendingId,
  rejectPendingId,
  signoffPermitted,
  signoffPending,
  onReviewer,
  onPreview,
  onReviewedValue,
  onReviewRationale,
  onConfirm,
  onApprove,
  onRejectReason,
  onReject,
  onSignoffRationale,
  onSignoff,
}: ApprovalWorkbenchProps) {
  const reviews = summary.reviews ?? [];
  const [reviewSearch, setReviewSearch] = useState("");
  const [reviewPage, setReviewPage] = useState(1);
  const filteredReviews = useMemo(() => {
    const query = reviewSearch.trim().toLowerCase();
    if (!query) {
      return reviews;
    }
    return reviews.filter((review) =>
      [review.review_id, review.scenario, review.status, review.driver_key, review.driver_label, review.module]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [reviewSearch, reviews]);
  const reviewPageCount = Math.max(1, Math.ceil(filteredReviews.length / 12));
  const visibleReviewPage = Math.min(reviewPage, reviewPageCount);
  const visibleReviews = filteredReviews.slice((visibleReviewPage - 1) * 12, visibleReviewPage * 12);
  const progress = summary.review_progress;

  useEffect(() => {
    setReviewPage(1);
  }, [artifactHash, reviewSearch]);

  useEffect(() => {
    setReviewPage((current) => Math.min(current, reviewPageCount));
  }, [reviewPageCount]);

  return (
    <section className="panel professional-model-approvals" aria-labelledby="professional-model-approvals-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Identity- and fingerprint-bound PM action</p>
          <h2 id="professional-model-approvals-title">PM Approval Workflow</h2>
          <p>Approval requires exact backend periods, a full-identity preview, named reviewer, rationale, and deliberate confirmation.</p>
        </div>
      </div>

      <div className="grid-cards professional-model-review-progress" aria-label="Review progress">
        <article className="mini-card">
          <strong>Required approvals</strong>
          <p>{progress?.required_count == null ? "Unavailable" : progress.required_count}</p>
        </article>
        <article className="mini-card">
          <strong>Approved</strong>
          <p>{progress?.approved_count == null ? "Unavailable" : progress.approved_count}</p>
        </article>
        <article className="mini-card">
          <strong>Progress by state</strong>
          <StructuredValue value={progress?.counts} />
        </article>
      </div>

      <label className="form-label" htmlFor="professional-model-reviewer">Reviewer identity</label>
      <input
        id="professional-model-reviewer"
        className="search-input"
        type="text"
        autoComplete="name"
        value={reviewer}
        onChange={(event) => onReviewer(event.target.value)}
        placeholder="Enter the accountable reviewer name or ID"
        required
      />
      {!reviewer.trim() ? (
        <p className="table-note">A real reviewer identity is required for preview, approve, reject, sign-off, and rebuild.</p>
      ) : null}

      {reviews.length ? (
        <>
          <div className="panel-toolbar professional-model-review-filter">
            <label className="form-label" htmlFor="professional-model-review-search">Search approval queue</label>
            <input
              id="professional-model-review-search"
              className="search-input"
              type="search"
              value={reviewSearch}
              onChange={(event) => setReviewSearch(event.target.value)}
              placeholder="Find a scenario, driver, module, or approval key"
            />
            <span className="table-note">
              {filteredReviews.length
                ? "Showing " + String((visibleReviewPage - 1) * 12 + 1) + "-" +
                  String(Math.min(visibleReviewPage * 12, filteredReviews.length)) + " of " +
                  String(filteredReviews.length)
                : "No matching approvals"}
            </span>
          </div>

          {visibleReviews.length ? (
            <div className="stacked-cards">
              {visibleReviews.map((review) => {
                const preview = activePreview?.review_id === review.review_id ? activePreview : null;
                const periods = review.forecast_periods ?? [];
                const draftValues = reviewedValues[review.review_id] ?? [];
                const rationale = reviewRationales[review.review_id] ?? "";
                const issues = reviewRowIssues(review);
                const rowValid = issues.length === 0;
                const parsedValues =
                  periods.length === 5 &&
                  draftValues.length === 5 &&
                  draftValues.every((value) => value.trim() && Number.isFinite(Number(value)))
                    ? draftValues.map(Number)
                    : null;
                const previewIdentityMatches =
                  Boolean(preview?.transport_identity && summary.transport_identity) &&
                  professionalModelTransportIdentitiesEqual(
                    preview?.transport_identity as ProfessionalModelTransportIdentity,
                    summary.transport_identity as ProfessionalModelTransportIdentity,
                  );
                const previewAllowed =
                  contractValid && rowValid && Boolean(artifactHash) && Boolean(reviewer.trim()) &&
                  Boolean(rationale.trim()) && review.permitted_actions?.preview === true &&
                  parsedValues !== null;
                const approvalAllowed =
                  contractValid && rowValid && Boolean(artifactHash) && Boolean(reviewer.trim()) &&
                  Boolean(rationale.trim()) && review.stale !== true && previewIdentityMatches &&
                  preview?.preview_id != null && preview.permitted_actions?.approve === true &&
                  preview.stale !== true && Boolean(preview.fingerprint) && confirmed;
                const rejectReason = rejectReasons[review.review_id] ?? "";
                const rejectAllowed =
                  contractValid && rowValid && Boolean(artifactHash) && Boolean(reviewer.trim()) &&
                  review.permitted_actions?.reject === true && Boolean(rejectReason.trim());

                return (
                  <article key={review.review_id} className="mini-card professional-model-review-card">
                    <div className="professional-model-review-heading">
                      <div>
                        <strong>{review.scenario || "Scenario unavailable"}</strong>
                        <code>{review.review_id || "Approval key unavailable"}</code>
                      </div>
                      <div>
                        <StatusText value={review.status} />
                        {review.stale ? <span className="professional-model-stale">Stale approval</span> : null}
                      </div>
                    </div>

                    {!rowValid ? (
                      <div className="run-status error" role="alert">
                        <strong>Invalid approval contract. This row is audit-only.</strong>
                        <ul className="clean-list">
                          {issues.map((issue) => <li key={issue}>{issue}</li>)}
                        </ul>
                      </div>
                    ) : null}

                    <dl className="professional-model-key-values">
                      <div><dt>Driver key</dt><dd><code>{review.driver_key || "Unavailable"}</code></dd></div>
                      <div><dt>Driver label</dt><dd>{review.driver_label || "Unavailable"}</dd></div>
                      <div><dt>Definition</dt><dd>{review.driver_definition || "Unavailable"}</dd></div>
                      <div><dt>Module</dt><dd>{review.module || "Unavailable"}</dd></div>
                      <div><dt>Unit</dt><dd>{review.unit || "Unavailable"}</dd></div>
                      <div><dt>Method</dt><dd>{review.method || "Unavailable"}</dd></div>
                      <div><dt>Source</dt><dd>{review.source_ref || "Unavailable"}</dd></div>
                      <div><dt>Value source</dt><dd>{review.value_source || "Unavailable"}</dd></div>
                      <div><dt>As of</dt><dd>{review.as_of || "Unavailable"}</dd></div>
                      <div><dt>Current path status</dt><dd>{titleize(review.artifact_current_path_status)}</dd></div>
                      <div><dt>Proposed path status</dt><dd>{titleize(review.proposed_path_status)}</dd></div>
                      <div><dt>Approved path status</dt><dd>{titleize(review.approved_path_status)}</dd></div>
                      <div><dt>Applied path status</dt><dd>{titleize(review.applied_path_status)}</dd></div>
                      <div><dt>Requirement fingerprint</dt><dd><HashValue value={review.requirement_hash} /></dd></div>
                      <div><dt>Recorded value fingerprint</dt><dd><HashValue value={review.fingerprint} /></dd></div>
                      <div><dt>Approval identity fingerprint</dt><dd><HashValue value={review.approval_identity_fingerprint} /></dd></div>
                      <div><dt>Latest event type</dt><dd>{titleize(review.latest_event_type)}</dd></div>
                      <div><dt>Last reviewer</dt><dd>{review.reviewer || review.actor || "Unavailable"}</dd></div>
                      <div><dt>Last rationale</dt><dd>{review.rationale || "Unavailable"}</dd></div>
                      <div><dt>Last reviewed</dt><dd>{formatTimestamp(review.timestamp ?? review.reviewed_at)}</dd></div>
                      <div><dt>Stale reason</dt><dd>{review.stale_reason || "None supplied"}</dd></div>
                    </dl>

                    <div>
                      <strong>Approval artifact identity</strong>
                      <StructuredValue value={review.approval_artifact_identity} />
                    </div>
                    <div className="grid-cards">
                      <article className="mini-card"><strong>Latest event</strong><StructuredValue value={review.latest_event} /></article>
                      <article className="mini-card"><strong>Review context</strong><StructuredValue value={review.review_context} /></article>
                      <article className="mini-card"><strong>Materiality</strong><StructuredValue value={review.materiality} /></article>
                      <article className="mini-card"><strong>Impact</strong><StructuredValue value={review.impact} /></article>
                      <article className="mini-card"><strong>Evidence locator</strong><StructuredValue value={review.evidence_locator} /></article>
                      <article className="mini-card"><strong>Downstream dependencies</strong><StructuredValue value={review.downstream_dependencies} /></article>
                    </div>
                    {review.stale_reasons?.length ? (
                      <div className="run-status error">
                        <strong>Stale reasons</strong>
                        <ul className="clean-list">
                          {review.stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}
                        </ul>
                      </div>
                    ) : null}

                    <ReviewPathEditor
                      review={review}
                      draftValues={draftValues}
                      disabled={!contractValid || !rowValid || review.permitted_actions?.preview !== true}
                      onReviewedValue={onReviewedValue}
                    />

                    <label className="form-label" htmlFor={"professional-model-rationale-" + review.review_id}>
                      Review rationale
                    </label>
                    <textarea
                      id={"professional-model-rationale-" + review.review_id}
                      className="watchlist-textarea"
                      value={rationale}
                      onChange={(event) => onReviewRationale(review.review_id, event.target.value)}
                      placeholder="State the evidence and judgment supporting these exact values."
                      disabled={!contractValid || !rowValid}
                      required
                    />

                    <div className="action-row">
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => parsedValues && onPreview(review, parsedValues)}
                        disabled={!previewAllowed || previewPendingId === review.review_id}
                      >
                        {previewPendingId === review.review_id
                          ? "Previewing " + review.scenario + "..."
                          : "Preview exact labeled values for " + review.scenario}
                      </button>
                    </div>

                    {preview ? (
                      <section className="professional-model-review-preview" aria-label={review.scenario + " review preview"}>
                        <h3>Identity-bound approval preview</h3>
                        <p>Fingerprint: <HashValue value={preview.fingerprint} /></p>
                        <p>Previewed: {formatTimestamp(preview.previewed_at)}</p>
                        {preview.message ? <p>{preview.message}</p> : null}
                        <div>
                          <strong>Preview transport identity</strong>
                          <StructuredValue value={preview.transport_identity} />
                        </div>
                        {!previewIdentityMatches || preview.stale ? (
                          <div className="run-status error" role="alert">
                            <strong>Stale or mismatched approval preview</strong>
                            <span>The preview cannot be approved because its full model-run/hash identity does not match the open model.</span>
                          </div>
                        ) : null}
                        <DriverTable drivers={preview.driver_values} caption={review.scenario + " exact approval drivers"} />
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={confirmed}
                            onChange={(event) => onConfirm(event.target.checked)}
                            disabled={
                              !previewIdentityMatches ||
                              preview.stale === true ||
                              preview.permitted_actions?.approve !== true
                            }
                          />
                          I confirm these exact labeled values, rationale, fingerprint, and artifact identity.
                        </label>
                      </section>
                    ) : null}

                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => onApprove(review)}
                      disabled={!approvalAllowed || approvePendingId === review.review_id}
                    >
                      {approvePendingId === review.review_id ? "Approving " + review.scenario + "..." : "Approve " + review.scenario}
                    </button>

                    <div className="professional-model-reject-controls">
                      <label className="form-label" htmlFor={"professional-model-reject-" + review.review_id}>
                        Rejection reason
                      </label>
                      <textarea
                        id={"professional-model-reject-" + review.review_id}
                        className="watchlist-textarea"
                        value={rejectReason}
                        onChange={(event) => onRejectReason(review.review_id, event.target.value)}
                        placeholder="Explain why this exact backend-labeled path is rejected."
                        disabled={review.permitted_actions?.reject !== true || !contractValid || !rowValid}
                        required
                      />
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => onReject(review)}
                        disabled={!rejectAllowed || rejectPendingId === review.review_id}
                      >
                        {rejectPendingId === review.review_id ? "Rejecting..." : "Reject " + review.scenario}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="professional-model-empty">
              <strong>No approval rows match this search.</strong>
              <span>Clear the search to return to the complete backend review queue.</span>
            </div>
          )}

          {reviewPageCount > 1 ? (
            <div className="professional-model-pagination" aria-label="Approval queue pagination">
              <button
                type="button"
                className="ghost-button"
                onClick={() => setReviewPage((current) => Math.max(1, current - 1))}
                disabled={visibleReviewPage <= 1}
              >
                Previous approvals
              </button>
              <span>Page {visibleReviewPage} of {reviewPageCount}</span>
              <button
                type="button"
                className="ghost-button"
                onClick={() => setReviewPage((current) => Math.min(reviewPageCount, current + 1))}
                disabled={visibleReviewPage >= reviewPageCount}
              >
                Next approvals
              </button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="professional-model-empty">
          <strong>No PM review actions supplied.</strong>
          <span>The frontend does not infer approval rows from scenarios or requirements.</span>
        </div>
      )}

      <SignoffEvidence signoff={summary.signoff} />

      <div className="professional-model-signoff">
        <label className="form-label" htmlFor="professional-model-signoff-rationale">Final sign-off rationale</label>
        <textarea
          id="professional-model-signoff-rationale"
          className="watchlist-textarea"
          value={signoffRationale}
          onChange={(event) => onSignoffRationale(event.target.value)}
          placeholder="Explain the PM basis for signing off this workbook identity."
          disabled={!contractValid || !signoffPermitted}
          required
        />
        <button
          type="button"
          className="primary-button"
          onClick={onSignoff}
          disabled={
            !contractValid || !artifactHash || !reviewer.trim() || !signoffPermitted ||
            !signoffRationale.trim() || signoffPending
          }
        >
          {signoffPending ? "Signing off..." : "Final PM Sign-Off"}
        </button>
        {!signoffPermitted ? (
          <p className="table-note">Final sign-off is disabled by the backend until all prior requirements pass.</p>
        ) : null}
      </div>

      <AuditHistory
        events={summary.audit_events ?? []}
        total={summary.audit_event_page?.total}
        returned={summary.audit_event_page?.returned}
        truncated={summary.audit_event_page?.truncated}
      />
    </section>
  );
}
function ArtifactActions({
  ticker,
  summary,
  contractValid,
  artifactHash,
  reviewer,
  rebuildRationale,
  rebuildPending,
  rebuildRun,
  rebuildRequestError,
  onRebuildRationale,
  onRebuild,
  onRetry,
  onDismiss,
}: {
  ticker: string;
  summary: ProfessionalModelSummaryPayload;
  contractValid: boolean;
  artifactHash: string;
  reviewer: string;
  rebuildRationale: string;
  rebuildPending: boolean;
  rebuildRun: RunPayload | null;
  rebuildRequestError: unknown;
  onRebuildRationale: (value: string) => void;
  onRebuild: () => void;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const modelRunId = summary.transport_identity?.model_run_id;
  const canDownload =
    contractValid && Boolean(artifactHash) && summary.permitted_actions?.download === true;
  const canRebuild =
    contractValid &&
    Boolean(artifactHash) &&
    modelRunId != null &&
    Boolean(reviewer.trim()) &&
    Boolean(rebuildRationale.trim()) &&
    summary.permitted_actions?.rebuild === true;
  const status = rebuildRun?.status ?? null;
  const failed =
    Boolean(rebuildRequestError) ||
    Boolean(rebuildRun?.error) ||
    status?.toLowerCase() === "failed";
  const progress =
    typeof rebuildRun?.progress === "number" && Number.isFinite(rebuildRun.progress)
      ? Math.max(0, Math.min(100, rebuildRun.progress <= 1 ? rebuildRun.progress * 100 : rebuildRun.progress))
      : null;
  const requestPinned = summary.download_request_pinned === true;

  return (
    <section className="panel professional-model-artifact-actions" aria-labelledby="professional-model-artifact-title">
      <div className="professional-model-section-heading">
        <div>
          <p className="panel-caption">Backend workbook artifact</p>
          <h2 id="professional-model-artifact-title">Workbook Artifact</h2>
          <p>Rebuild creates a new artifact identity. It does not approve drivers or sign off the model.</p>
        </div>
      </div>

      <dl className="professional-model-key-values">
        <div><dt>Filename</dt><dd>{summary.artifact?.filename || "Not supplied"}</dd></div>
        <div><dt>Model run ID</dt><dd><HashValue value={modelRunId} /></dd></div>
        <div><dt>Artifact hash</dt><dd><HashValue value={artifactHash} /></dd></div>
        <div><dt>Manifest hash</dt><dd><HashValue value={summary.artifact?.manifest_hash} /></dd></div>
        <div><dt>Model input hash</dt><dd><HashValue value={summary.artifact?.model_input_hash} /></dd></div>
        <div><dt>Result hash</dt><dd><HashValue value={summary.artifact?.result_hash} /></dd></div>
      </dl>

      <label className="form-label" htmlFor="professional-model-rebuild-rationale">Rebuild rationale</label>
      <textarea
        id="professional-model-rebuild-rationale"
        className="watchlist-textarea"
        value={rebuildRationale}
        onChange={(event) => onRebuildRationale(event.target.value)}
        placeholder="Explain why this model run should be rebuilt."
        disabled={!contractValid || summary.permitted_actions?.rebuild !== true}
        required
      />

      <div className="action-row">
        {canDownload ? (
          <a
            className="primary-button"
            href={getProfessionalModelDownloadUrl(ticker)}
            download={summary.artifact?.filename || true}
          >
            {requestPinned ? "Download hash-bound workbook" : "Download current workbook snapshot"}
          </a>
        ) : (
          <button type="button" className="primary-button" disabled>Download unavailable</button>
        )}
        <button
          type="button"
          className="ghost-button"
          onClick={onRebuild}
          disabled={!canRebuild || rebuildPending}
        >
          {rebuildPending ? "Queueing rebuild..." : "Rebuild professional model"}
        </button>
      </div>

      {!requestPinned ? (
        <div className="run-status" role="note">
          <strong>Download request is not pinned to the open model identity.</strong>
          <span>The endpoint does not yet accept the expected workbook hash and model run in the request. Treat the response as the current server snapshot, not an exact copy of the artifact currently displayed.</span>
        </div>
      ) : null}

      {rebuildRun || rebuildRequestError ? (
        <div className={"run-status" + (failed ? " error" : "")} aria-live="polite">
          <strong>{status ? titleize(status) : failed ? "Rebuild request failed" : "Rebuild update"}</strong>
          <dl className="professional-model-key-values">
            <div><dt>Run ID</dt><dd>{displayValue(rebuildRun?.run_id)}</dd></div>
            <div><dt>Status</dt><dd>{displayValue(status)}</dd></div>
            <div><dt>Progress</dt><dd>{rebuildRun?.progress == null ? "Unavailable" : displayValue(rebuildRun.progress)}</dd></div>
            <div><dt>Message</dt><dd>{rebuildRun?.message || "Unavailable"}</dd></div>
            <div><dt>Error</dt><dd>{rebuildRun?.error || (rebuildRequestError ? errorMessage(rebuildRequestError) : "None supplied")}</dd></div>
          </dl>
          {progress != null ? (
            <progress max={100} value={progress} aria-label="Professional-model rebuild progress">{progress}</progress>
          ) : null}
          <div>
            <strong>Result</strong>
            <StructuredValue value={rebuildRun?.result} />
          </div>
          <div className="action-row">
            {failed ? (
              <button type="button" className="ghost-button" onClick={onRetry} disabled={!canRebuild || rebuildPending}>
                Retry rebuild
              </button>
            ) : null}
            <button type="button" className="ghost-button" onClick={onDismiss}>
              Dismiss rebuild status
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
export function ProfessionalModelPanel({ ticker }: ProfessionalModelPanelProps) {
  const queryClient = useQueryClient();
  const [selectedSheet, setSelectedSheet] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [activePreview, setActivePreview] = useState<ProfessionalModelReviewPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [reviewedValues, setReviewedValues] = useState<Record<string, string[]>>({});
  const [reviewRationales, setReviewRationales] = useState<Record<string, string>>({});
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>({});
  const [signoffRationale, setSignoffRationale] = useState("");
  const [rebuildRationale, setRebuildRationale] = useState("");
  const [rebuildRunId, setRebuildRunId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const identityRef = useRef<ProfessionalModelTransportIdentity | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["professional-model", ticker],
    queryFn: () => getProfessionalModel(ticker),
    enabled: Boolean(ticker),
  });

  const summary = summaryQuery.data;
  const knownState = asKnownState(summary?.state);
  const contractIssues = summary ? readinessContractIssues(summary, knownState) : [];
  const reviewContractIssues = summary ? reviewActionContractIssues(summary) : [];
  const summaryContractValid = Boolean(summary && contractIssues.length === 0);
  const reviewActionsValid = summaryContractValid && reviewContractIssues.length === 0;
  const artifactHash =
    summary?.transport_identity?.hashes.workbook_sha256 ??
    summary?.artifact?.artifact_hash ??
    summary?.artifact?.workbook_hash ??
    "";
  const modelRunId = summary?.transport_identity?.model_run_id ?? null;
  const identityKey = summary?.transport_identity
    ? JSON.stringify(summary.transport_identity)
    : "";
  const sheets = summary?.sheets ?? [];
  const groups = useMemo(() => (summary ? blockerGroups(summary) : []), [summary]);
  identityRef.current = summary?.transport_identity ?? null;

  useEffect(() => {
    if (!sheets.length) {
      setSelectedSheet("");
      return;
    }
    if (!sheets.some((sheet) => sheet.name === selectedSheet)) {
      setSelectedSheet(sheets[0].name);
    }
  }, [selectedSheet, sheets]);

  useEffect(() => {
    setActivePreview(null);
    setConfirmed(false);
    setReviewedValues({});
    setReviewRationales({});
    setRejectReasons({});
    setSignoffRationale("");
    setRebuildRationale("");
  }, [identityKey]);

  useEffect(() => {
    setReviewer("");
    setRebuildRunId(null);
    setNotice(null);
  }, [ticker]);

  useEffect(() => {
    const reviews = summary?.reviews ?? [];
    setReviewedValues((current) => {
      const next: Record<string, string[]> = {};
      for (const review of reviews) {
        const periodsValid = review.forecast_periods?.length === 5;
        const proposed = review.proposed_path?.length === 5 ? review.proposed_path : null;
        const currentPath =
          review.artifact_current_path?.length === 5 ? review.artifact_current_path : null;
        const recorded =
          periodsValid && review.driver_values?.length === 5
            ? review.driver_values.map((driver) => driver.value)
            : null;
        const seed = proposed ?? currentPath ?? recorded;
        next[review.review_id] =
          current[review.review_id] ??
          (periodsValid
            ? (seed ?? ["", "", "", "", ""]).map((value) =>
                value == null ? "" : String(value),
              )
            : []);
      }
      return next;
    });
  }, [identityKey, summary?.reviews]);

  const refreshModel = () => {
    void queryClient.invalidateQueries({ queryKey: ["professional-model", ticker] });
    void queryClient.invalidateQueries({ queryKey: ["professional-model-sheet", ticker] });
  };

  const previewMutation = useMutation({
    mutationFn: ({
      review,
      values,
      actor,
      rationale,
    }: {
      review: ProfessionalModelReviewItem;
      values: number[];
      identityAtRequest: ProfessionalModelTransportIdentity;
      actor: string;
      rationale: string;
    }) => previewProfessionalModelReview(ticker, review, values, actor, rationale),
    onMutate: () => {
      setNotice(null);
      setActivePreview(null);
      setConfirmed(false);
    },
    onSuccess: (payload, variables) => {
      const currentIdentity = identityRef.current;
      if (
        !currentIdentity ||
        !payload.transport_identity ||
        payload.review_id !== variables.review.review_id ||
        !professionalModelTransportIdentitiesEqual(currentIdentity, variables.identityAtRequest) ||
        !professionalModelTransportIdentitiesEqual(payload.transport_identity, variables.identityAtRequest)
      ) {
        setActivePreview(null);
        setConfirmed(false);
        setNotice("Discarded a stale preview because its full model-run/hash identity did not match the open model.");
        refreshModel();
        return;
      }
      setActivePreview(payload);
      setConfirmed(false);
      setNotice(payload.message ?? "Identity-bound approval preview loaded.");
    },
    onError: () => {
      setActivePreview(null);
      setConfirmed(false);
    },
  });

  const approveMutation = useMutation({
    mutationFn: ({
      previewId,
      fingerprint,
      actor,
      rationale,
    }: {
      review: ProfessionalModelReviewItem;
      previewId: number;
      fingerprint: string;
      actor: string;
      rationale: string;
    }) => approveProfessionalModelReview(ticker, previewId, fingerprint, actor, rationale),
    onMutate: () => {
      setNotice(null);
      setActivePreview(null);
      setConfirmed(false);
    },
    onSuccess: (payload) => {
      setNotice(payload.message ?? "PM approval recorded by the backend.");
      refreshModel();
    },
    onError: () => {
      setActivePreview(null);
      setConfirmed(false);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({
      review,
      actor,
      reason,
    }: {
      review: ProfessionalModelReviewItem;
      actor: string;
      reason: string;
    }) => rejectProfessionalModelReview(ticker, review.review_id, actor, reason),
    onMutate: () => {
      setNotice(null);
      setActivePreview(null);
      setConfirmed(false);
    },
    onSuccess: (payload, variables) => {
      setRejectReasons((current) => ({ ...current, [variables.review.review_id]: "" }));
      setNotice(payload.message ?? "PM rejection recorded by the backend.");
      refreshModel();
    },
    onError: () => {
      setActivePreview(null);
      setConfirmed(false);
    },
  });

  const signoffMutation = useMutation({
    mutationFn: ({ actor, rationale }: { actor: string; rationale: string }) =>
      signOffProfessionalModel(ticker, artifactHash, actor, rationale),
    onMutate: () => {
      setNotice(null);
      setActivePreview(null);
      setConfirmed(false);
    },
    onSuccess: (payload) => {
      setNotice(payload.message ?? "Final PM sign-off recorded by the backend.");
      refreshModel();
    },
  });

  const rebuildMutation = useMutation({
    mutationFn: ({ actor, rationale }: { actor: string; rationale: string }) =>
      rebuildProfessionalModel(ticker, modelRunId, actor, rationale),
    onMutate: () => {
      setNotice(null);
      setActivePreview(null);
      setConfirmed(false);
    },
    onSuccess: (payload) => {
      setRebuildRunId(payload.run_id);
      setNotice(payload.message ?? "Professional-model rebuild queued. Rebuild is not approval.");
    },
  });

  const rebuildRunQuery = useQuery({
    queryKey: ["professional-model-rebuild", rebuildRunId],
    queryFn: () => getRunStatus(rebuildRunId ?? ""),
    enabled: Boolean(rebuildRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status?.toLowerCase();
      return status === "completed" || status === "failed" || status === "canceled" || status === "cancelled"
        ? false
        : 1000;
    },
  });

  const rebuildRun = rebuildRunQuery.data ?? rebuildMutation.data ?? null;

  useEffect(() => {
    const status = rebuildRunQuery.data?.status?.toLowerCase();
    if (status === "completed") {
      setNotice("Professional-model rebuild completed. Refreshing artifact identity; approval remains independent.");
      refreshModel();
    }
  }, [rebuildRunQuery.data?.status]);

  const actionMutationError =
    previewMutation.error ??
    approveMutation.error ??
    rejectMutation.error ??
    signoffMutation.error;

  const dismissActionError = () => {
    previewMutation.reset();
    approveMutation.reset();
    rejectMutation.reset();
    signoffMutation.reset();
    setActivePreview(null);
    setConfirmed(false);
  };

  const queueRebuild = () => {
    rebuildMutation.mutate({
      actor: reviewer.trim(),
      rationale: rebuildRationale.trim(),
    });
  };

  const dismissRebuild = () => {
    const runId = rebuildRunId;
    setRebuildRunId(null);
    rebuildMutation.reset();
    if (runId) {
      queryClient.removeQueries({ queryKey: ["professional-model-rebuild", runId] });
    }
  };

  const retryRebuild = () => {
    dismissRebuild();
    queueRebuild();
  };

  const openSheet = (sheet: string) => {
    setSelectedSheet(sheet);
    requestAnimationFrame(() => {
      document.getElementById("professional-model-sheet-review")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  };

  if (summaryQuery.isPending && !summary) {
    return (
      <section className="panel professional-model-loading" aria-busy="true" aria-live="polite">
        <h2>Loading Professional Model</h2>
        <p>Loading backend readiness, workbook identity, checks, and review actions.</p>
        <div className="skeleton-line skeleton" />
        <div className="skeleton-line skeleton" />
        <div className="skeleton-line skeleton" />
      </section>
    );
  }

  if (summaryQuery.isError || !summary) {
    return (
      <section className="panel error" role="alert">
        <h2>Professional model data is unavailable</h2>
        <p>{summaryQuery.isError ? errorMessage(summaryQuery.error) : "The backend returned no professional-model payload."}</p>
      </section>
    );
  }

  return (
    <section className="page-stack professional-model-panel">
      <ReadinessHeader
        summary={summary}
        knownState={knownState}
        groups={groups}
        contractIssues={contractIssues}
      />

      {reviewContractIssues.length ? (
        <div className="run-status error" role="alert" data-testid="professional-model-review-contract-error">
          <strong>Approval and sign-off actions are disabled by the backend review contract.</strong>
          <span>Rebuild remains available when permitted so the contract can be regenerated.</span>
          <ul className="clean-list">{reviewContractIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
        </div>
      ) : null}

      {actionMutationError ? (
        <div className="run-status error" role="alert">
          <strong>Professional-model action failed.</strong>
          <span>{errorMessage(actionMutationError)}</span>
          <button type="button" className="ghost-button" onClick={dismissActionError}>
            Dismiss action error
          </button>
        </div>
      ) : notice ? (
        <div className="run-status" aria-live="polite">
          <strong>Professional model update</strong>
          <span>{notice}</span>
        </div>
      ) : null}

      <DecisionSnapshot summary={summary} />
      <BackendEvidence summary={summary} />
      <RequirementChecklist requirements={summary.requirements ?? []} onOpenSheet={openSheet} />
      <BlockerWorkbench
        groups={groups}
        warnings={summary.warnings ?? []}
        blockerDataSupplied={summary.blocker_groups !== undefined || summary.blockers !== undefined}
      />
      <ProfessionalModelSheetReview
        ticker={ticker}
        artifactHash={artifactHash}
        modelRunId={modelRunId}
        sheets={sheets}
        selectedSheet={selectedSheet}
        onSelectSheet={setSelectedSheet}
        summaryFindings={summary.sheet_audit_findings ?? []}
      />
      <ApprovalWorkbench
        summary={summary}
        contractValid={reviewActionsValid}
        artifactHash={artifactHash}
        reviewer={reviewer}
        activePreview={activePreview}
        confirmed={confirmed}
        reviewedValues={reviewedValues}
        reviewRationales={reviewRationales}
        rejectReasons={rejectReasons}
        signoffRationale={signoffRationale}
        previewPendingId={
          previewMutation.isPending
            ? previewMutation.variables?.review.review_id ?? null
            : null
        }
        approvePendingId={approveMutation.isPending ? approveMutation.variables?.review.review_id ?? null : null}
        rejectPendingId={rejectMutation.isPending ? rejectMutation.variables?.review.review_id ?? null : null}
        signoffPermitted={summary.permitted_actions?.signoff === true}
        signoffPending={signoffMutation.isPending}
        onReviewer={setReviewer}
        onPreview={(review, values) => {
          if (!summary.transport_identity) {
            return;
          }
          previewMutation.mutate({
            review,
            values,
            identityAtRequest: summary.transport_identity,
            actor: reviewer.trim(),
            rationale: reviewRationales[review.review_id]?.trim() ?? "",
          });
        }}
        onReviewedValue={(reviewId, index, value) => {
          setReviewedValues((current) => {
            const nextValues = [...(current[reviewId] ?? [])];
            nextValues[index] = value;
            return { ...current, [reviewId]: nextValues };
          });
          setActivePreview((current) => (current?.review_id === reviewId ? null : current));
          setConfirmed(false);
        }}
        onReviewRationale={(reviewId, rationale) => {
          setReviewRationales((current) => ({ ...current, [reviewId]: rationale }));
          setActivePreview((current) => (current?.review_id === reviewId ? null : current));
          setConfirmed(false);
        }}
        onConfirm={setConfirmed}
        onApprove={(review) => {
          const fingerprint = activePreview?.fingerprint ?? activePreview?.preview_fingerprint;
          if (
            activePreview?.review_id === review.review_id &&
            activePreview.preview_id != null &&
            fingerprint
          ) {
            approveMutation.mutate({
              review,
              previewId: activePreview.preview_id,
              fingerprint,
              actor: reviewer.trim(),
              rationale: reviewRationales[review.review_id]?.trim() ?? "",
            });
          }
        }}
        onRejectReason={(reviewId, reason) =>
          setRejectReasons((current) => ({ ...current, [reviewId]: reason }))
        }
        onReject={(review) =>
          rejectMutation.mutate({
            review,
            actor: reviewer.trim(),
            reason: rejectReasons[review.review_id]?.trim() ?? "",
          })
        }
        onSignoffRationale={setSignoffRationale}
        onSignoff={() =>
          signoffMutation.mutate({
            actor: reviewer.trim(),
            rationale: signoffRationale.trim(),
          })
        }
      />
      <ArtifactActions
        ticker={ticker}
        summary={summary}
        contractValid={summaryContractValid}
        artifactHash={artifactHash}
        reviewer={reviewer}
        rebuildRationale={rebuildRationale}
        rebuildPending={rebuildMutation.isPending}
        rebuildRun={rebuildRun}
        rebuildRequestError={rebuildMutation.error ?? rebuildRunQuery.error}
        onRebuildRationale={setRebuildRationale}
        onRebuild={queueRebuild}
        onRetry={retryRebuild}
        onDismiss={dismissRebuild}
      />
    </section>
  );
}