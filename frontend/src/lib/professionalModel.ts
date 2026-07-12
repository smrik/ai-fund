import type {
  ProfessionalModelApprovalArtifactIdentity,
  ProfessionalModelAuditEvent,
  ProfessionalModelBlockerGroup,
  ProfessionalModelDecisionUsefulContent,
  ProfessionalModelDriverValue,
  ProfessionalModelHashTuple,
  ProfessionalModelReviewItem,
  ProfessionalModelReviewPreview,
  ProfessionalModelSheetCell,
  ProfessionalModelSheetFinding,
  ProfessionalModelSheetPayload,
  ProfessionalModelSummaryPayload,
  ProfessionalModelTransportIdentity,
} from "@/lib/types";

type JsonObject = Record<string, unknown>;

const PROFESSIONAL_MODEL_HASH_FIELDS = [
  "source_sha256",
  "model_input_sha256",
  "result_sha256",
  "manifest_sha256",
  "workbook_sha256",
  "qa_report_sha256",
  "review_evidence_sha256",
] as const satisfies readonly (keyof ProfessionalModelHashTuple)[];

function asObject(value: unknown): JsonObject | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string | null {
  if (value == null) {
    return null;
  }
  const normalized = String(value).trim();
  return normalized || null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function hasOwn(object: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function normalizedHashValue(
  hashes: JsonObject,
  field: (typeof PROFESSIONAL_MODEL_HASH_FIELDS)[number],
): string | null {
  if (!hasOwn(hashes, field)) {
    throw new Error(`Professional-model transport identity is missing ${field}.`);
  }
  const value = hashes[field];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Professional-model transport identity has an invalid ${field}.`);
  }
  return value.trim().toLowerCase();
}

export function getProfessionalModelTransportIdentity(
  raw: JsonObject | ProfessionalModelTransportIdentity,
): ProfessionalModelTransportIdentity {
  const rawObject = raw as unknown as JsonObject;
  const providedIdentity = asObject(rawObject.transport_identity);
  const identitySource = providedIdentity ?? rawObject;
  const modelRunId = asNumber(identitySource.model_run_id);
  if (modelRunId == null || !Number.isInteger(modelRunId) || modelRunId <= 0) {
    throw new Error("Professional-model transport identity is missing a valid model_run_id.");
  }

  const hashes = asObject(identitySource.hashes);
  if (!hashes) {
    throw new Error("Professional-model transport identity is missing its seven-field hash tuple.");
  }

  return {
    model_run_id: modelRunId,
    hashes: {
      source_sha256: normalizedHashValue(hashes, "source_sha256"),
      model_input_sha256: normalizedHashValue(hashes, "model_input_sha256"),
      result_sha256: normalizedHashValue(hashes, "result_sha256"),
      manifest_sha256: normalizedHashValue(hashes, "manifest_sha256"),
      workbook_sha256: normalizedHashValue(hashes, "workbook_sha256"),
      qa_report_sha256: normalizedHashValue(hashes, "qa_report_sha256"),
      review_evidence_sha256: normalizedHashValue(hashes, "review_evidence_sha256"),
    },
  };
}

export function professionalModelIdentityMismatch(
  left: ProfessionalModelTransportIdentity | JsonObject,
  right: ProfessionalModelTransportIdentity | JsonObject,
): string | null {
  const leftIdentity = getProfessionalModelTransportIdentity(left);
  const rightIdentity = getProfessionalModelTransportIdentity(right);
  if (leftIdentity.model_run_id !== rightIdentity.model_run_id) {
    return "model_run_id";
  }
  for (const field of PROFESSIONAL_MODEL_HASH_FIELDS) {
    if (leftIdentity.hashes[field] !== rightIdentity.hashes[field]) {
      return field;
    }
  }
  return null;
}

export function professionalModelTransportIdentitiesEqual(
  left: ProfessionalModelTransportIdentity | JsonObject,
  right: ProfessionalModelTransportIdentity | JsonObject,
): boolean {
  return professionalModelIdentityMismatch(left, right) === null;
}


function titleize(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function evidenceSummary(value: unknown): string | null {
  if (value == null) {
    return null;
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return "No blocking evidence reported.";
    }
    const entries = value.map((item) => {
      const object = asObject(item);
      if (object) {
        const requirement = asString(object.requirement);
        const status = asString(object.status);
        return requirement && status ? `${titleize(requirement)}: ${status}` : JSON.stringify(object);
      }
      return String(item);
    });
    const visible = entries.slice(0, 6);
    return entries.length > visible.length
      ? `${visible.join("; ")}; and ${entries.length - visible.length} more.`
      : visible.join("; ");
  }
  const object = asObject(value);
  if (object) {
    const required = asNumber(object.required);
    const approved = asNumber(object.approved);
    const openKeys = asArray(object.open_keys);
    if (required != null || approved != null || openKeys.length) {
      return `${approved ?? 0} of ${required ?? openKeys.length} required approvals complete; ${openKeys.length} open.`;
    }
    return JSON.stringify(object);
  }
  return String(value);
}

function normalizeFindings(value: unknown): ProfessionalModelSheetFinding[] {
  return asArray(value)
    .map((entry, index) => {
      const item = asObject(entry);
      if (!item) {
        return null;
      }
      return {
        finding_id: asString(item.finding_id) ?? `sheet-finding-${index + 1}`,
        reason_code:
          asString(item.reason_code) ??
          asString(item.check_id) ??
          asString(item.code) ??
          "sheet_audit_finding",
        status: asString(item.status),
        severity: asString(item.severity),
        sheet: asString(item.sheet) ?? asString(item.sheet_name),
        cell: asString(item.cell) ?? asString(item.coordinate),
        message: asString(item.message) ?? asString(item.detail),
        remediation: asString(item.remediation),
      };
    })
    .filter((item) => item !== null) as ProfessionalModelSheetFinding[];
}

function normalizeBlockerGroups(raw: JsonObject): ProfessionalModelBlockerGroup[] {
  const blockers = asObject(raw.blockers);
  const groups = asObject(blockers?.groups);
  const counts = asObject(blockers?.counts);
  if (!groups) {
    return [];
  }
  return Object.entries(groups).map(([category, value]) => {
    const reasonCodes = asArray(value).map((reason) => String(reason));
    return {
      category,
      label: titleize(category),
      count: asNumber(counts?.[category]) ?? reasonCodes.length,
      blockers: reasonCodes.map((reasonCode) => ({
        reason_code: reasonCode,
        message: null,
        owner: null,
        remediation: null,
      })),
    };
  });
}

function stringArray(value: unknown): string[] {
  return asArray(value)
    .map((item) => asString(item))
    .filter((item): item is string => item !== null);
}

function normalizePeriodAxis(value: unknown): string[] {
  if (!Array.isArray(value) || value.length !== 5) {
    return [];
  }
  const periods = value.map((item) => asString(item));
  if (
    periods.some((period) => period === null) ||
    new Set(periods).size !== periods.length
  ) {
    return [];
  }
  return periods as string[];
}

function numericPath(value: unknown): Array<number | null> | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value.map((item) => asNumber(item));
}

function normalizedApprovalArtifactIdentity(
  value: unknown,
): ProfessionalModelApprovalArtifactIdentity | null {
  const identity = asObject(value);
  if (!identity) {
    return null;
  }
  return {
    model_run_id: asNumber(identity.model_run_id),
    source_sha256: asString(identity.source_sha256 ?? identity.source_hash),
    model_input_sha256: asString(
      identity.model_input_sha256 ?? identity.model_input_hash ?? identity.input_hash,
    ),
    result_sha256: asString(identity.result_sha256 ?? identity.result_hash),
    workbook_sha256: asString(identity.workbook_sha256 ?? identity.workbook_hash),
  };
}

function normalizeReviews(
  reviewRaw: JsonObject | null,
  summaryActions: JsonObject | null,
): ProfessionalModelReviewItem[] {
  const globalActions = asObject(reviewRaw?.permitted_actions) ?? summaryActions ?? {};
  const reviewContract = asObject(reviewRaw?.review_contract);
  const globalContractIssues = stringArray(reviewContract?.issues);
  if (reviewContract?.compatible !== true) {
    globalContractIssues.push("review_contract_incompatible");
  }
  if (reviewContract?.regeneration_required === true) {
    globalContractIssues.push("review_contract_regeneration_required");
  }

  return asArray(reviewRaw?.requirements).map((entry, index) => {
    const objectItem = asObject(entry);
    const item = objectItem ?? {};
    const latestEvent = asObject(item.latest_event);
    const approvalKey = asString(item.approval_key);
    const scenario = asString(item.scenario);
    const driver = asString(item.driver ?? item.driver_key);
    const driverLabel = asString(item.driver_label ?? item.display_label ?? item.label);
    const unit = asString(item.unit);
    const requiredShape = asObject(item.required_value_shape);
    const forecastPeriods = normalizePeriodAxis(
      item.forecast_periods ?? requiredShape?.periods,
    );
    const staleReasons = [
      ...stringArray(item.stale_reasons),
      ...stringArray(latestEvent?.stale_reasons),
    ];
    const staleReason = asString(item.stale_reason);
    if (staleReason) {
      staleReasons.push(staleReason);
    }
    const contractIssues = [
      ...globalContractIssues,
      ...stringArray(item.contract_issues),
    ];

    if (!objectItem) {
      contractIssues.push("review_row_not_object");
    }
    if (!approvalKey) {
      contractIssues.push("approval_key_missing");
    }
    if (!scenario) {
      contractIssues.push("scenario_missing");
    }
    if (!driver) {
      contractIssues.push("driver_missing");
    }
    if (!unit) {
      contractIssues.push("unit_missing");
    }
    if (
      forecastPeriods.length !== 5 ||
      new Set(forecastPeriods).size !== forecastPeriods.length
    ) {
      contractIssues.push("forecast_period_axis_invalid");
    }

    const requirementArtifactIdentity = normalizedApprovalArtifactIdentity(
      item.approval_artifact_identity ?? item.artifact_identity,
    );
    if (!requirementArtifactIdentity) {
      contractIssues.push("artifact_identity_missing");
    }

    const uniqueContractIssues = [...new Set(contractIssues)].sort();
    const contractValid =
      reviewContract?.compatible === true &&
      item.approvable === true &&
      uniqueContractIssues.length === 0;
    const status = asString(item.status) ?? "unknown";
    const normalizedStatus = status.toLowerCase();
    const currentEventId =
      asNumber(item.current_event_id) ??
      asNumber(item.preview_id) ??
      asNumber(latestEvent?.event_id);
    const rowActions = asObject(item.permitted_actions) ?? globalActions;
    const previewPermitted =
      rowActions.preview === true || rowActions.review_preview === true;
    const approvePermitted =
      rowActions.approve === true || rowActions.review_approve === true;
    const rejectPermitted =
      rowActions.reject === true || rowActions.review_reject === true;
    const reviewedValues = asArray(item.reviewed_values);
    const reviewId = approvalKey ?? `invalid-review-row-${index + 1}`;
    const sourceRef = asString(item.source_ref);
    const reviewer = asString(item.reviewer ?? item.actor ?? latestEvent?.reviewer ?? latestEvent?.actor);
    const timestamp = asString(
      item.timestamp ?? item.reviewed_at ?? latestEvent?.timestamp ?? latestEvent?.created_at,
    );
    const rationale = asString(item.rationale ?? latestEvent?.rationale);
    const currentPath = numericPath(
      item.current_path ?? item.artifact_current_path,
    );
    const proposedPath = numericPath(item.proposed_path);
    const approvedPath = numericPath(item.approved_path);
    const appliedPath = numericPath(item.applied_path);

    return {
      review_id: reviewId,
      scenario: scenario ?? "Unlabeled review requirement",
      driver_key: driver,
      driver_label: driverLabel,
      driver_definition: asString(
        item.driver_definition ?? item.definition ?? item.description,
      ),
      module: asString(item.module),
      unit,
      forecast_periods: forecastPeriods,
      method: asString(item.method),
      source_ref: sourceRef,
      value_source: asString(item.value_source),
      as_of: asString(item.as_of),
      artifact_current_path: currentPath,
      current_path: currentPath,
      artifact_current_path_status: asString(item.artifact_current_path_status),
      proposed_path: proposedPath,
      proposed_path_status: asString(item.proposed_path_status),
      approved_path: approvedPath,
      approved_path_status: asString(item.approved_path_status),
      applied_path: appliedPath,
      applied_path_status: asString(item.applied_path_status),
      requirement_hash: asString(item.requirement_hash),
      approval_identity_fingerprint: asString(
        item.approval_identity_fingerprint,
      ),
      approval_artifact_identity: requirementArtifactIdentity,
      actor: reviewer,
      reviewer,
      reviewed_at: timestamp,
      timestamp,
      rationale,
      latest_event: latestEvent,
      latest_event_type: asString(item.latest_event_type ?? latestEvent?.event_type),
      stale_reason: staleReason ?? stringArray(staleReasons)[0] ?? null,
      stale_reasons: [...new Set(staleReasons)].sort(),
      review_context: asObject(item.review_context),
      materiality: item.materiality ?? null,
      impact: item.impact ?? null,
      evidence_locator: item.evidence_locator ?? null,
      downstream_dependencies: stringArray(item.downstream_dependencies),
      contract_valid: contractValid,
      contract_issues: uniqueContractIssues,
      status,
      stale:
        item.stale === true ||
        normalizedStatus === "stale" ||
        staleReasons.length > 0,
      fingerprint: asString(
        item.reviewed_value_fingerprint ?? item.fingerprint,
      ),
      preview_id:
        normalizedStatus === "previewed" ? currentEventId : null,
      explanation: asString(item.explanation ?? item.description),
      driver_values: reviewedValues.map((value, valueIndex) => ({
        driver_key: driver ?? undefined,
        driver_id: approvalKey ?? undefined,
        scenario,
        approval_state: status,
        label: driverLabel,
        value,
        unit,
        period: forecastPeriods[valueIndex] ?? null,
        source_ref: sourceRef,
      })),
      permitted_actions: {
        preview: contractValid && previewPermitted,
        approve:
          contractValid &&
          approvePermitted &&
          normalizedStatus === "previewed" &&
          currentEventId != null,
        reject: contractValid && rejectPermitted,
      },
    };
  });
}


function decisionStructuredValue(
  value: unknown,
): Record<string, unknown> | string | null {
  if (typeof value === "string") {
    return value;
  }
  return asObject(value);
}

function normalizeDecisionUseful(
  value: unknown,
): ProfessionalModelDecisionUsefulContent | null {
  const decision = asObject(value);
  if (!decision) {
    return null;
  }

  const scenarioValuations = asArray(decision.scenario_valuations)
    .map((entry) => {
      const item = asObject(entry);
      const scenario = asString(item?.scenario);
      if (!item || !scenario) {
        return null;
      }
      return {
        ...item,
        scenario,
        state: asString(item.state),
        value_per_share: asNumber(item.value_per_share),
        current_price: asNumber(item.current_price),
        upside_pct: asNumber(item.upside_pct),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  const forecastPath = asArray(decision.forecast_path)
    .map((entry) => {
      const item = asObject(entry);
      const period =
        typeof item?.period === "number"
          ? item.period
          : asString(item?.period);
      if (!item || period == null) {
        return null;
      }
      return {
        ...item,
        period,
        period_type: asString(item.period_type),
        revenue: asNumber(item.revenue),
        ebit_margin: asNumber(item.ebit_margin),
        eps: asNumber(item.eps),
        fcff: asNumber(item.fcff),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  return {
    current_price: asNumber(decision.current_price),
    current_price_source: asString(decision.current_price_source),
    current_price_as_of: asString(decision.current_price_as_of),
    scenario_valuations: scenarioValuations,
    forecast_path: forecastPath,
    what_price_implies: decisionStructuredValue(decision.what_price_implies),
    variant_estimate_gap: decisionStructuredValue(decision.variant_estimate_gap),
    downside_mechanism: decisionStructuredValue(decision.downside_mechanism),
  };
}

function normalizeReviewCounts(value: unknown): Record<string, number> {
  const counts = asObject(value);
  if (!counts) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(counts)
      .map(([key, count]) => [key, asNumber(count)] as const)
      .filter((entry): entry is readonly [string, number] => entry[1] !== null),
  );
}

function normalizeAuditEvents(value: unknown): ProfessionalModelAuditEvent[] {
  return asArray(value)
    .map((entry) => {
      const item = asObject(entry);
      if (!item) {
        return null;
      }
      return {
        ...item,
        event_id: asNumber(item.event_id),
        model_run_id: asNumber(item.model_run_id),
        approval_key: asString(item.approval_key),
        approval_scope: asString(item.approval_scope),
        event_type: asString(item.event_type),
        state: asString(item.state),
        reviewed_values: Array.isArray(item.reviewed_values)
          ? item.reviewed_values
          : null,
        reviewed_value_fingerprint: asString(item.reviewed_value_fingerprint),
        actor: asString(item.actor),
        rationale: asString(item.rationale),
        created_at: asString(item.created_at),
        stale: item.stale === true,
        stale_reasons: stringArray(item.stale_reasons),
        superseded: item.superseded === true,
        workbook_hash: asString(item.workbook_hash),
        source_hash: asString(item.source_hash),
        input_hash: asString(item.input_hash),
        result_hash: asString(item.result_hash),
      };
    })
    .filter((item) => item !== null) as ProfessionalModelAuditEvent[];
}

export function isNormalizedProfessionalModelSummary(
  raw: JsonObject,
): raw is JsonObject & ProfessionalModelSummaryPayload {
  return (
    "state" in raw &&
    Array.isArray(raw.reviews) &&
    asObject(raw.transport_identity) !== null
  );
}

export function normalizeProfessionalModelSummary(
  raw: JsonObject,
  reviewRaw: JsonObject | null,
): ProfessionalModelSummaryPayload {
  if (isNormalizedProfessionalModelSummary(raw)) {
    const transportIdentity = getProfessionalModelTransportIdentity(raw);
    return {
      ...(raw as unknown as ProfessionalModelSummaryPayload),
      transport_identity: transportIdentity,
    };
  }

  const transportIdentity = getProfessionalModelTransportIdentity(raw);
  const state = asString(raw.normalized_state);
  const hashes = transportIdentity.hashes;
  const artifactIdentity = asObject(raw.artifact_identity);
  const calculation = asObject(raw.calculation_verification);
  const recalculation = asObject(calculation?.recalculation_state);
  const actions = asObject(raw.permitted_actions);
  const sheetAudit = asObject(raw.sheet_audit);
  const modelRunId = transportIdentity.model_run_id;
  const workbookHash = hashes.workbook_sha256;
  const sourceHash = hashes.source_sha256;
  const decisionReady =
    typeof raw.decision_readiness === "boolean" ? raw.decision_readiness : null;

  const requirements = asArray(raw.full_state_requirements)
    .map((entry) => {
      const item = asObject(entry);
      const requirementId = asString(item?.requirement);
      if (!item || !requirementId) {
        return null;
      }
      return {
        requirement_id: requirementId,
        label: titleize(requirementId),
        status: asString(item.status),
        owner: asString(item.owner),
        explanation: evidenceSummary(item.evidence),
        remediation: asString(item.remediation),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  const sheetFindings = normalizeFindings(sheetAudit?.findings);
  const sheets = asArray(raw.sheets)
    .map((entry) => {
      const item = asObject(entry);
      const name = asString(item?.name);
      if (!item || !name) {
        return null;
      }
      return {
        name,
        order: (asNumber(item.index) ?? 0) + 1,
        status: asString(item.visibility),
        finding_count: sheetFindings.filter((finding) => finding.sheet === name).length,
        formula_count: asNumber(item.formula_count),
        cell_count: asNumber(item.nonempty_cell_count),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  const summaryReview = asObject(raw.review);
  const reviewMetadata = reviewRaw ?? summaryReview;
  const signoffRaw = asObject(reviewMetadata?.signoff);
  const auditPageRaw = asObject(reviewRaw?.audit_event_page);
  const reviewContract =
    asObject(reviewRaw?.review_contract) ??
    asObject(raw.review_contract) ??
    asObject(summaryReview?.contract);
  const decisionSemanticQa =
    asObject(raw.decision_semantic_qa_verification) ??
    asObject(reviewRaw?.decision_semantic_qa_verification);
  const supplementalReviewMetadata = {
    review_contract: reviewContract,
    decision_semantic_qa_verification: decisionSemanticQa,
  };

  return {
    ticker: asString(raw.ticker) ?? "",
    state,
    decision_ready: decisionReady,
    decision_readiness:
      asString(raw.decision_readiness_message) ??
      (decisionReady === true
        ? "Backend reports this artifact is decision-ready."
        : decisionReady === false
          ? "Backend reports this artifact is not decision-ready."
          : "Backend did not report decision readiness."),
    transport_identity: transportIdentity,
    artifact: {
      filename: asString(artifactIdentity?.workbook_filename),
      artifact_hash: workbookHash,
      workbook_hash: workbookHash,
      manifest_hash: hashes.manifest_sha256,
      model_input_hash: hashes.model_input_sha256,
      result_hash: hashes.result_sha256,
      source_hash: sourceHash,
      source_run_id:
        asNumber(artifactIdentity?.source_run_id ?? raw.source_run_id) ??
        modelRunId,
      build_run_id:
        asNumber(artifactIdentity?.build_run_id ?? raw.build_run_id) ??
        modelRunId,
      built_at: asString(artifactIdentity?.built_at ?? raw.built_at),
      verified_at: asString(
        artifactIdentity?.verified_at ?? calculation?.verified_at,
      ),
      size_bytes: asNumber(artifactIdentity?.workbook_bytes),
    },
    calculation_verification: {
      state: asString(calculation?.state),
      status: asString(calculation?.status),
      verified:
        typeof calculation?.verified === "boolean" ? calculation.verified : null,
      engine: asString(calculation?.cache_engine ?? calculation?.engine),
      message: asString(recalculation?.message ?? calculation?.message),
      verified_at: asString(calculation?.verified_at),
    },
    requirements,
    blocker_groups: normalizeBlockerGroups(raw),
    warnings: asArray(raw.warnings).map((warning) => String(warning)),
    checks: asArray(raw.checks)
      .map((entry) => asObject(entry))
      .filter((entry): entry is JsonObject => entry !== null)
      .map((entry, index) => ({
        ...entry,
        check_id: asString(entry.check_id) ?? `check-${index + 1}`,
        status: asString(entry.status),
        difference_or_count:
          typeof entry.difference_or_count === "number" ||
          typeof entry.difference_or_count === "string"
            ? entry.difference_or_count
            : null,
        tolerance_or_expected:
          typeof entry.tolerance_or_expected === "number" ||
          typeof entry.tolerance_or_expected === "string"
            ? entry.tolerance_or_expected
            : null,
      })),
    integrity: asObject(raw.integrity),
    valuation_diagnostics: asObject(raw.valuation_diagnostics),
    bridge: asObject(raw.ev_to_equity_bridge),
    decision_useful: normalizeDecisionUseful(raw.decision_useful),
    sheets,
    sheet_audit_findings: sheetFindings,
    reviews: normalizeReviews(reviewRaw, actions),
    review_progress: reviewMetadata
      ? {
          required_count: asNumber(reviewMetadata.required_count),
          approved_count: asNumber(reviewMetadata.approved_count),
          counts: normalizeReviewCounts(reviewMetadata.counts),
        }
      : null,
    signoff: signoffRaw
      ? {
          status: asString(signoffRaw.status),
          current: signoffRaw.current === true,
          event_id: asNumber(signoffRaw.event_id),
          actor: asString(signoffRaw.actor),
          signed_at: asString(signoffRaw.signed_at),
          workbook_hash: asString(
            signoffRaw.workbook_hash ?? signoffRaw.workbook_sha256,
          ),
          stale_reasons: stringArray(signoffRaw.stale_reasons),
        }
      : null,
    audit_events: normalizeAuditEvents(reviewRaw?.audit_events),
    audit_event_page: auditPageRaw
      ? {
          total: asNumber(auditPageRaw.total),
          returned: asNumber(auditPageRaw.returned),
          truncated: auditPageRaw.truncated === true,
        }
      : null,
    download_request_pinned: raw.download_request_pinned === true,
    permitted_actions: {
      download: actions?.download === true,
      rebuild: actions?.rebuild === true,
      signoff: actions?.signoff === true,
    },
    ...supplementalReviewMetadata,
  };
}


function periodTypeFromClassification(
  classification: string | null,
  lineage: ProfessionalModelSheetCell["lineage"],
): string | null {
  const periodKeys = Array.isArray(lineage)
    ? lineage
        .map((item) => asString(item.period_key))
        .filter((value): value is string => value !== null)
    : [];
  if (periodKeys.some((period) => /E$|estimate|forecast/i.test(period))) {
    return "forecast";
  }
  if (periodKeys.some((period) => /^(FY\d{2,4}|LTM|TTM)$|A$/i.test(period))) {
    return "historical";
  }
  const normalized = classification?.toLowerCase() ?? "";
  if (/historical|actual/.test(normalized)) {
    return "historical";
  }
  if (/forecast|estimate|projected/.test(normalized)) {
    return "forecast";
  }
  return null;
}

export function normalizeProfessionalModelSheet(
  raw: JsonObject,
  page: number,
  rowLimit: number,
  expectedWorkbookHash: string,
  expectedModelRunId?: string | number | null,
): ProfessionalModelSheetPayload {
  const normalizedExpectedWorkbookHash = expectedWorkbookHash.trim().toLowerCase();
  if (!normalizedExpectedWorkbookHash) {
    throw new Error("Selected-sheet validation requires the expected workbook hash.");
  }

  const normalizedWorkbookHash = asString(raw.workbook_hash);
  const liveWorkbookHash = asString(raw.workbook_sha256);
  if (
    normalizedWorkbookHash &&
    liveWorkbookHash &&
    normalizedWorkbookHash.toLowerCase() !== liveWorkbookHash.toLowerCase()
  ) {
    throw new Error("Selected-sheet response contains conflicting workbook hashes.");
  }
  const workbookHash = normalizedWorkbookHash ?? liveWorkbookHash;
  if (!workbookHash) {
    throw new Error("Selected-sheet response did not include its workbook hash.");
  }
  if (workbookHash.toLowerCase() !== normalizedExpectedWorkbookHash) {
    throw new Error("Selected-sheet response belongs to a different workbook artifact.");
  }

  const modelRunId = asNumber(raw.model_run_id);
  const normalizedExpectedModelRunId = asNumber(expectedModelRunId);
  if (
    normalizedExpectedModelRunId == null ||
    !Number.isInteger(normalizedExpectedModelRunId) ||
    normalizedExpectedModelRunId <= 0
  ) {
    throw new Error("Selected-sheet validation requires a valid expected model run ID.");
  }
  if (modelRunId == null) {
    throw new Error("Selected-sheet response did not include its model run ID.");
  }
  if (modelRunId !== normalizedExpectedModelRunId) {
    throw new Error("Selected-sheet response belongs to a different model run.");
  }


  if ("sheet" in raw && ("total_pages" in raw || "page" in raw)) {
    return {
      ...(raw as unknown as ProfessionalModelSheetPayload),
      model_run_id: modelRunId,
      workbook_hash: workbookHash,
    };
  }

  const dimensions = asObject(raw.dimensions);
  const pagination = asObject(raw.pagination);
  const maxRow = asNumber(dimensions?.max_row) ?? 0;
  const maxColumn = asNumber(dimensions?.max_column) ?? 0;
  const sheetName = asString(raw.sheet_name) ?? "";
  const findingsContainer = asObject(raw.sheet_audit);
  const findings = normalizeFindings(findingsContainer?.findings).filter(
    (finding) => !finding.sheet || finding.sheet === sheetName,
  );

  const cells = asArray(raw.cells)
    .map((entry) => {
      const item = asObject(entry);
      const address = asString(item?.coordinate);
      if (!item || !address) {
        return null;
      }
      const classificationObject = asObject(item.classification);
      const classification =
        asString(classificationObject?.kind) ?? asString(item.classification);
      const commentObject = asObject(item.comment);
      const commentText = asString(commentObject?.text);
      const commentAuthor = asString(commentObject?.author);
      const lineage: ProfessionalModelSheetCell["lineage"] = Array.isArray(item.lineage)
        ? item.lineage
            .map((line) => asObject(line))
            .filter((line): line is JsonObject => line !== null)
        : typeof item.lineage === "string"
          ? item.lineage
          : asObject(item.lineage);
      return {
        address,
        period_type: periodTypeFromClassification(classification, lineage),
        classification,
        formula: asString(item.formula),
        cached_value: item.cached_value,
        number_format: asString(item.number_format),
        lineage,
        comment: commentText
          ? commentAuthor
            ? `${commentAuthor}: ${commentText}`
            : commentText
          : null,
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  return {
    ticker: asString(raw.ticker) ?? "",
    model_run_id: modelRunId,
    sheet: sheetName,
    page,
    page_size: rowLimit,
    total_cells: maxRow * maxColumn,
    total_pages: Math.max(1, Math.ceil(maxRow / Math.max(1, rowLimit))),
    cells,
    findings,
    workbook_hash: workbookHash,
    returned_cells: asNumber(pagination?.returned_cells),
  };
}


export function normalizeProfessionalModelPreview(
  raw: JsonObject,
  review?: ProfessionalModelReviewItem | null,
): ProfessionalModelReviewPreview {
  const transportIdentity = getProfessionalModelTransportIdentity(raw);
  const responseApprovalKey = asString(raw.review_id ?? raw.approval_key);
  if (review && responseApprovalKey && responseApprovalKey !== review.review_id) {
    throw new Error("Professional-model preview belongs to a different approval row.");
  }
  const approvalKey = responseApprovalKey ?? review?.review_id ?? "";
  const responseScenario = asString(raw.scenario);
  if (review && responseScenario && responseScenario !== review.scenario) {
    throw new Error("Professional-model preview scenario differs from its review requirement.");
  }
  const scenario = responseScenario ?? review?.scenario ?? "Unlabeled review preview";
  const driver =
    asString(raw.driver ?? raw.driver_key) ?? review?.driver_key ?? null;
  const sourceRef =
    asString(raw.source_ref) ?? review?.source_ref ?? null;
  const unit = asString(raw.unit) ?? review?.unit ?? null;
  const requiredShape = asObject(raw.required_value_shape);
  const rawResponsePeriods = raw.forecast_periods ?? requiredShape?.periods;
  const responsePeriods = normalizePeriodAxis(rawResponsePeriods);
  if (rawResponsePeriods != null && responsePeriods.length === 0) {
    throw new Error("Professional-model preview returned an invalid forecast-period axis.");
  }
  const reviewPeriods = normalizePeriodAxis(review?.forecast_periods);
  const rawDriverValues = asArray(raw.driver_values);
  const driverPeriods = normalizePeriodAxis(
    rawDriverValues.map((entry) => asObject(entry)?.period),
  );
  const periods =
    responsePeriods.length > 0
      ? responsePeriods
      : reviewPeriods.length > 0
        ? reviewPeriods
        : driverPeriods;
  const periodAxisValid =
    periods.length === 5 && new Set(periods).size === periods.length;

  if (
    responsePeriods.length > 0 &&
    reviewPeriods.length > 0 &&
    (responsePeriods.length !== reviewPeriods.length ||
      responsePeriods.some((period, index) => period !== reviewPeriods[index]))
  ) {
    throw new Error("Professional-model preview period axis differs from its review requirement.");
  }

  const values = asArray(raw.reviewed_values);
  const driverValues: ProfessionalModelDriverValue[] =
    rawDriverValues.length > 0
      ? rawDriverValues.map((entry, index) => {
          const item = asObject(entry) ?? {};
          return {
            driver_key: asString(item.driver_key) ?? driver ?? undefined,
            driver_id: asString(item.driver_id) ?? (approvalKey || undefined),
            scenario: asString(item.scenario) ?? scenario,
            approval_state: asString(item.approval_state ?? raw.state),
            label:
              asString(item.label) ??
              review?.driver_label ??
              null,
            value: hasOwn(item, "value") ? item.value : null,
            unit: asString(item.unit) ?? unit,
            period: asString(item.period) ?? periods[index] ?? null,
            source_ref: asString(item.source_ref) ?? sourceRef,
          };
        })
      : values.map((value, index) => ({
          driver_key: driver ?? undefined,
          driver_id: approvalKey || undefined,
          scenario,
          approval_state: asString(raw.state),
          label: review?.driver_label ?? null,
          value,
          unit,
          period: periods[index] ?? null,
          source_ref: sourceRef,
        }));
  const actions = asObject(raw.permitted_actions);
  const fingerprint = asString(
    raw.fingerprint ??
      raw.reviewed_value_fingerprint ??
      raw.preview_fingerprint,
  );

  return {
    ticker: asString(raw.ticker) ?? "",
    review_id: approvalKey,
    scenario,
    preview_id: asNumber(raw.preview_id),
    fingerprint: fingerprint ?? undefined,
    preview_fingerprint:
      asString(raw.preview_fingerprint ?? raw.reviewed_value_fingerprint) ??
      undefined,
    artifact_hash: transportIdentity.hashes.workbook_sha256,
    transport_identity: transportIdentity,
    previewed_at: asString(raw.previewed_at),
    warnings: stringArray(raw.warnings),
    stale: raw.stale === true,
    status: asString(raw.status ?? raw.state),
    message: asString(raw.message),
    driver_values: driverValues,
    permitted_actions: {
      preview:
        actions?.preview === true ||
        review?.permitted_actions?.preview === true,
      approve:
        periodAxisValid &&
        review?.contract_valid !== false &&
        (actions?.approve === true || raw.approval_allowed === true),
      reject:
        actions?.reject === true ||
        review?.permitted_actions?.reject === true,
    },
  };
}


