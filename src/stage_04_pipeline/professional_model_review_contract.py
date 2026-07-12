"""Deterministic contracts for professional-model PM review workflows.

The helpers in this module shape and validate review metadata only.  They do
not calculate, transform, or infer valuation inputs.  In particular, a queue
requirement never manufactures an artifact-current driver path: the absence of
that path is represented explicitly and a PM must supply an exact five-value
path through the preview workflow.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
import re
from typing import Any
from urllib.parse import quote, urlencode, urlsplit


HashCallback = Callable[[Any], str]

SEMANTIC_QA_CHECK_IDS: tuple[str, ...] = (
    "wacc_methodology",
    "wacc_parity",
    "share_basis",
    "as_of_alignment",
)

_SCENARIOS = {"base": "Base", "upside": "Upside", "downside": "Downside"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_DRIVER_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_CHECK_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
_CELL_RE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

_REQUIRED_ARTIFACT_HASHES: tuple[str, ...] = (
    "source_sha256",
    "model_input_sha256",
    "result_sha256",
    "workbook_sha256",
)
_OPTIONAL_ARTIFACT_HASHES: tuple[str, ...] = (
    "manifest_sha256",
    "qa_report_sha256",
    "review_evidence_sha256",
)
_ARTIFACT_HASH_ALIASES: Mapping[str, tuple[str, ...]] = {
    "source_sha256": ("source_sha256", "source_hash"),
    "model_input_sha256": (
        "model_input_sha256",
        "model_input_hash",
        "input_hash",
    ),
    "result_sha256": ("result_sha256", "result_hash"),
    "workbook_sha256": ("workbook_sha256", "workbook_hash"),
    "manifest_sha256": ("manifest_sha256", "manifest_hash"),
    "qa_report_sha256": ("qa_report_sha256", "qa_hash"),
    "review_evidence_sha256": (
        "review_evidence_sha256",
        "review_evidence_hash",
    ),
}

_REVIEW_CONTEXT_FIELDS = frozenset(
    {
        "source_ref",
        "method",
        "as_of",
        "evidence_locator",
        "materiality",
        "impact",
        "downstream_dependencies",
    }
)
_EVIDENCE_LOCATOR_FIELDS = frozenset({"url", "sheet", "coordinate"})
_SEMANTIC_EVIDENCE_FIELDS = frozenset(
    {"schema", "source", "method", "as_of", "details", "evidence_hash"}
)

MAX_REVIEW_CONTEXT_BYTES = 16_384
MAX_CONTEXT_STRING = 2_000
MAX_CONTEXT_ITEMS = 50
MAX_CONTEXT_DEPTH = 5
MAX_SEMANTIC_EVIDENCE_BYTES = 16_384


class ProfessionalModelReviewContractError(ValueError):
    """Raised when caller-supplied review metadata violates the contract."""


def canonical_json(value: Any) -> str:
    """Return the canonical JSON representation used by review evidence."""

    def _default(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"cannot serialize {type(item)!r}")

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    )


def canonical_hash(value: Any) -> str:
    """Return SHA-256 over :func:`canonical_json` UTF-8 bytes."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _compute_hash(value: Any, callback: HashCallback | None) -> str:
    digest = str((callback or canonical_hash)(value))
    if not _SHA256_RE.fullmatch(digest):
        raise ProfessionalModelReviewContractError(
            "canonical_hash callback must return a lowercase SHA-256 digest"
        )
    return digest


def _driver_metadata() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Return the stable presentation module/dependency positive list."""

    metadata: dict[str, tuple[str, tuple[str, ...]]] = {}

    def add(
        keys: Iterable[str], module: str, dependencies: Sequence[str]
    ) -> None:
        normalized_dependencies = tuple(sorted(set(dependencies)))
        for key in keys:
            metadata[key] = (module, normalized_dependencies)

    add(
        ("revenue_growth",),
        "revenue",
        (
            "balance_sheet.working_capital",
            "cash_flow.operating_cash_flow",
            "dcf.fcff",
            "income_statement.revenue",
            "valuation.enterprise_value",
        ),
    )
    add(
        (
            "gross_margin",
            "sga_percent_revenue",
            "rd_percent_revenue",
            "other_opex_percent_revenue",
            "other_nonoperating_percent_revenue",
        ),
        "income_statement",
        (
            "cash_flow.operating_cash_flow",
            "dcf.fcff",
            "income_statement.operating_income",
            "valuation.enterprise_value",
        ),
    )
    add(
        (
            "da_percent_revenue",
            "intangible_amortization_percent_revenue",
            "stock_comp_percent_revenue",
        ),
        "noncash_charges",
        (
            "cash_flow.operating_cash_flow",
            "dcf.fcff",
            "income_statement.operating_income",
            "ppe_intangibles.roll_forward",
        ),
    )
    add(
        ("effective_tax_rate", "cash_tax_rate", "nopat_tax_rate"),
        "taxes",
        (
            "cash_flow.cash_taxes",
            "dcf.nopat",
            "income_statement.income_tax",
            "valuation.enterprise_value",
        ),
    )
    add(
        (
            "dso",
            "dio",
            "dpo",
            "deferred_revenue_percent_revenue",
            "prepaids_percent_revenue",
            "other_current_assets_percent_revenue",
            "accrued_expenses_percent_revenue",
            "other_current_liabilities_percent_revenue",
        ),
        "working_capital",
        (
            "balance_sheet.working_capital",
            "cash_flow.change_in_working_capital",
            "dcf.fcff",
            "working_capital.schedule",
        ),
    )
    add(
        (
            "capex_percent_revenue",
            "acquisition_spend",
            "asset_sale_proceeds",
            "asset_cost_disposals",
            "asset_disposal_accumulated_depreciation",
        ),
        "capital_investment",
        (
            "balance_sheet.long_lived_assets",
            "cash_flow.investing_cash_flow",
            "dcf.fcff",
            "ppe_intangibles.roll_forward",
        ),
    )
    add(
        (
            "minimum_cash",
            "scheduled_debt_issuance",
            "scheduled_debt_repayment",
            "cost_of_debt",
            "cash_yield",
        ),
        "debt_cash_interest",
        (
            "balance_sheet.cash_and_debt",
            "cash_flow.financing_cash_flow",
            "debt_cash_interest.schedule",
            "income_statement.net_interest",
            "valuation.net_debt",
        ),
    )
    add(
        (
            "dividend_payout",
            "buyback_amount",
            "common_stock_issuance",
            "average_share_price",
            "incremental_diluted_shares",
            "preferred_dividends",
            "minority_earnings_percent",
        ),
        "capital_allocation",
        (
            "capital_allocation.schedule",
            "cash_flow.financing_cash_flow",
            "shares_eps.diluted_shares",
            "valuation.equity_value",
        ),
    )
    add(
        ("net_investment_purchases",),
        "investments",
        (
            "balance_sheet.investments",
            "cash_flow.investing_cash_flow",
            "valuation.net_debt",
        ),
    )
    add(
        (
            "deferred_tax_assets_percent_revenue",
            "deferred_tax_liabilities_percent_revenue",
        ),
        "deferred_taxes",
        (
            "balance_sheet.deferred_taxes",
            "cash_flow.operating_cash_flow",
            "taxes.schedule",
        ),
    )
    add(
        ("other_operating_cash_flow",),
        "cash_flow",
        (
            "balance_sheet.cash",
            "cash_flow.operating_cash_flow",
            "dcf.fcff",
        ),
    )
    add(
        ("other_investing_cash_flow",),
        "cash_flow",
        ("balance_sheet.cash", "cash_flow.investing_cash_flow"),
    )
    add(
        ("other_financing_cash_flow",),
        "cash_flow",
        ("balance_sheet.cash", "cash_flow.financing_cash_flow"),
    )
    add(
        ("fx_cash_adjustment", "misc_cash_adjustment"),
        "cash_flow",
        ("balance_sheet.cash", "cash_flow.cash_roll_forward"),
    )
    return metadata


_DRIVER_METADATA = _driver_metadata()


def _normalize_artifact_identity(
    artifact_hashes: Mapping[str, Any] | Any,
) -> tuple[dict[str, str | None], list[str]]:
    issues: list[str] = []
    identity: dict[str, str | None] = {}
    if not isinstance(artifact_hashes, Mapping):
        artifact_hashes = {}
        issues.append("artifact_hashes_not_object")

    for output_key in (*_REQUIRED_ARTIFACT_HASHES, *_OPTIONAL_ARTIFACT_HASHES):
        supplied: list[str] = []
        for alias in _ARTIFACT_HASH_ALIASES[output_key]:
            if alias in artifact_hashes and artifact_hashes[alias] is not None:
                supplied.append(str(artifact_hashes[alias]).strip().lower())
        if len(set(supplied)) > 1:
            issues.append(f"artifact_hash_conflict:{output_key}")
        candidate = supplied[0] if supplied else None
        if candidate is not None and not _SHA256_RE.fullmatch(candidate):
            issues.append(f"artifact_hash_invalid:{output_key}")
            candidate = None
        if output_key in _REQUIRED_ARTIFACT_HASHES and candidate is None:
            issues.append(f"artifact_hash_missing:{output_key}")
        identity[output_key] = candidate
    return identity, issues


def _normalize_period_axis(value: Any) -> tuple[list[str], list[str]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return [], ["forecast_period_axis_invalid"]
    periods: list[str] = []
    invalid = False
    for item in value:
        text = str(item or "").strip()
        if not text or len(text) > 40:
            invalid = True
        periods.append(text)
    if len(periods) != 5 or len(set(periods)) != 5:
        invalid = True
    return periods, (["forecast_period_axis_invalid"] if invalid else [])


def _column_number(column_letters: str) -> int:
    result = 0
    for char in column_letters:
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _normalize_blocker_row(
    blocker_row: Mapping[str, Any] | int | str | Any,
    *,
    expected_code: str,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    sheet = "PM_Review_Queue"
    row_number: int | None = None
    coordinate: str | None = None
    code = expected_code

    if isinstance(blocker_row, bool):
        issues.append("blocker_row_invalid")
    elif isinstance(blocker_row, int):
        row_number = blocker_row
    elif isinstance(blocker_row, str):
        text = blocker_row.strip()
        if text.isdigit():
            row_number = int(text)
        elif text:
            code = text
        else:
            issues.append("blocker_row_invalid")
    elif isinstance(blocker_row, Mapping):
        raw_sheet = blocker_row.get("sheet", blocker_row.get("sheet_name", sheet))
        sheet = str(raw_sheet or "").strip()
        raw_row = blocker_row.get("row", blocker_row.get("row_number"))
        if raw_row is not None:
            try:
                if isinstance(raw_row, bool):
                    raise ValueError
                row_number = int(raw_row)
            except (TypeError, ValueError):
                issues.append("blocker_row_invalid")
        raw_coordinate = blocker_row.get("coordinate", blocker_row.get("cell"))
        if raw_coordinate is not None:
            coordinate = str(raw_coordinate).strip().upper()
        raw_code = blocker_row.get("code", blocker_row.get("blocker"))
        if raw_code is not None:
            code = str(raw_code).strip()
    else:
        issues.append("blocker_row_invalid")

    if sheet != "PM_Review_Queue":
        issues.append("blocker_row_sheet_invalid")
    if row_number is not None and not 1 <= row_number <= 1_048_576:
        issues.append("blocker_row_invalid")
        row_number = None
    if coordinate is None and row_number is not None:
        coordinate = f"C{row_number}"
    coordinate_match = _CELL_RE.fullmatch(coordinate or "")
    if coordinate_match is None:
        issues.append("blocker_row_coordinate_unavailable")
        coordinate = None
    else:
        coordinate_row = int(coordinate_match.group(2))
        if row_number is None:
            row_number = coordinate_row
        elif row_number != coordinate_row:
            issues.append("blocker_row_coordinate_mismatch")
        if coordinate_match.group(1) != "C":
            issues.append("blocker_row_code_column_mismatch")
    if code != expected_code:
        issues.append("blocker_code_mismatch")

    return (
        {
            "sheet": sheet or None,
            "row": row_number,
            "coordinate": coordinate,
            "code": code or None,
        },
        issues,
    )


def enrich_pm_driver_requirement(
    *,
    ticker: str,
    model_run_id: int,
    artifact_hashes: Mapping[str, Any],
    forecast_periods: Sequence[Any],
    blocker_row: Mapping[str, Any] | int | str,
    scenario: str,
    driver: str,
    approval_key: str,
    scope: str,
    canonical_hash_fn: HashCallback | None = None,
) -> dict[str, Any]:
    """Build one immutable, fail-closed PM driver requirement payload.

    ``blocker_row`` may be a row number or a mapping with ``row``, ``sheet``,
    ``coordinate`` and ``code``/``blocker`` fields.  The queue's code column is
    C, so a numeric row deterministically resolves to ``PM_Review_Queue!C{row}``.
    """

    issues: list[str] = []
    normalized_ticker = str(ticker or "").strip().upper()
    if not _TICKER_RE.fullmatch(normalized_ticker) or ".." in normalized_ticker:
        issues.append("ticker_invalid")

    try:
        if isinstance(model_run_id, bool):
            raise ValueError
        normalized_run_id = int(model_run_id)
    except (TypeError, ValueError):
        normalized_run_id = 0
    if normalized_run_id <= 0:
        issues.append("model_run_id_invalid")

    normalized_scenario = _SCENARIOS.get(str(scenario or "").strip().lower())
    if normalized_scenario is None:
        normalized_scenario = str(scenario or "").strip()
        issues.append("scenario_invalid")
    normalized_driver = str(driver or "").strip()
    if not _DRIVER_RE.fullmatch(normalized_driver):
        issues.append("driver_invalid")

    normalized_key = str(approval_key or "").strip()
    normalized_scope = str(scope or "").strip()
    expected_key = f"pmq:{normalized_scenario}:{normalized_driver}"
    expected_scope = f"scenario_driver:{normalized_scenario}:{normalized_driver}"
    expected_blocker = (
        f"pm_approval_required:{normalized_scenario}:"
        f"{normalized_driver}:{expected_key}"
    )
    if normalized_key != expected_key:
        issues.append("approval_key_mismatch")
    if normalized_scope != expected_scope:
        issues.append("approval_scope_mismatch")

    identity, identity_issues = _normalize_artifact_identity(artifact_hashes)
    periods, period_issues = _normalize_period_axis(forecast_periods)
    normalized_blocker_row, blocker_issues = _normalize_blocker_row(
        blocker_row,
        expected_code=expected_blocker,
    )
    issues.extend(identity_issues)
    issues.extend(period_issues)
    issues.extend(blocker_issues)

    try:
        from src.stage_02_valuation.integrated_financial_forecast import DRIVER_SPECS

        runtime_spec = DRIVER_SPECS.get(normalized_driver)
    except Exception:
        runtime_spec = None
        issues.append("runtime_driver_registry_unavailable")
    if runtime_spec is None:
        unit: str | None = None
        issues.append("unknown_runtime_driver")
    else:
        unit = str(runtime_spec.unit)

    metadata = _DRIVER_METADATA.get(normalized_driver)
    if metadata is None:
        module: str | None = None
        downstream_dependencies: list[str] = []
        issues.append("driver_review_metadata_unavailable")
    else:
        module, dependency_tuple = metadata
        downstream_dependencies = list(dependency_tuple)

    coordinate = normalized_blocker_row["coordinate"]
    evidence_url: str | None = None
    if coordinate and normalized_ticker and normalized_blocker_row["sheet"]:
        match = _CELL_RE.fullmatch(coordinate)
        assert match is not None
        query = urlencode(
            (
                ("start_row", int(match.group(2))),
                ("start_column", _column_number(match.group(1))),
                ("row_limit", 1),
                ("column_limit", 1),
            )
        )
        evidence_url = (
            f"/api/tickers/{quote(normalized_ticker, safe='')}/professional-model/"
            f"sheets/{quote(str(normalized_blocker_row['sheet']), safe='')}?{query}"
        )

    contract_issues = sorted(set(issues))
    payload: dict[str, Any] = {
        "ticker": normalized_ticker,
        "model_run_id": normalized_run_id,
        "artifact_identity": identity,
        "approval_key": normalized_key,
        "scope": normalized_scope,
        "scenario": normalized_scenario,
        "driver": normalized_driver,
        "unit": unit,
        "module": module,
        "forecast_periods": periods,
        "required_value_shape": {
            "type": "number_array",
            "length": 5,
            "periods": periods,
        },
        "artifact_current_path": None,
        "artifact_current_path_status": "unavailable",
        "proposed_path": None,
        "proposed_path_status": "not_provided",
        "source_ref": None,
        "method": None,
        "as_of": None,
        "materiality": None,
        "impact": {"status": "not_provided"},
        "downstream_dependencies": downstream_dependencies,
        "blocker": normalized_blocker_row["code"],
        "blocker_row": normalized_blocker_row,
        "evidence_locator": {
            "url": evidence_url,
            "sheet": normalized_blocker_row["sheet"],
            "coordinate": coordinate,
        },
        "approvable": not contract_issues,
        "contract_issues": contract_issues,
    }
    payload["requirement_hash"] = _compute_hash(payload, canonical_hash_fn)
    return payload


def _contains_local_filesystem_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if re.search(r"(?i)\bfile://", text):
        return True
    without_web_urls = re.sub(r"(?i)https?://[^\s<>'\"]+", "", text)
    if text.startswith("/api/"):
        return False
    if without_web_urls.startswith("/") or "\\" in without_web_urls:
        return True
    return bool(
        re.search(r"(?i)(?:^|[\s('" + '"' + r"=])(?:[A-Z]:[\\/]|\\\\)", without_web_urls)
        or re.search(r"(?:^|[\s('" + '"' + r"=])(?:\.\.?[\\/]|~[\\/])", without_web_urls)
        or re.search(
            r"(?<![:/A-Za-z0-9_])/(?:Users|home|mnt|tmp|var|etc|opt|srv|root|workspace)(?:/|\b)",
            without_web_urls,
            re.IGNORECASE,
        )
        or re.search(
            r"(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:csv|json|parquet|pdf|xls|xlsx|xlsm|txt|yaml|yml)(?:\b|$)",
            without_web_urls,
            re.IGNORECASE,
        )
    )
def _normalize_context_value(value: Any, *, field: str, depth: int = 0) -> Any:
    if depth > MAX_CONTEXT_DEPTH:
        raise ProfessionalModelReviewContractError(
            f"review_context {field} exceeds maximum nesting depth"
        )
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProfessionalModelReviewContractError(
                f"review_context {field} must contain only finite numbers"
            )
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if len(text) > MAX_CONTEXT_STRING:
            raise ProfessionalModelReviewContractError(
                f"review_context {field} string is oversized"
            )
        if _contains_local_filesystem_path(text):
            raise ProfessionalModelReviewContractError(
                f"review_context {field} must not contain local filesystem paths"
            )
        return text
    if isinstance(value, Mapping):
        if len(value) > MAX_CONTEXT_ITEMS:
            raise ProfessionalModelReviewContractError(
                f"review_context {field} contains too many keys"
            )
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
            if not isinstance(raw_key, str):
                raise ProfessionalModelReviewContractError(
                    f"review_context {field} keys must be strings"
                )
            key = raw_key.strip()
            if not key or len(key) > 100:
                raise ProfessionalModelReviewContractError(
                    f"review_context {field} key is invalid"
                )
            normalized[key] = _normalize_context_value(
                raw_value,
                field=f"{field}.{key}",
                depth=depth + 1,
            )
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) > MAX_CONTEXT_ITEMS:
            raise ProfessionalModelReviewContractError(
                f"review_context {field} contains too many items"
            )
        return [
            _normalize_context_value(
                item,
                field=f"{field}[{index}]",
                depth=depth + 1,
            )
            for index, item in enumerate(value)
        ]
    raise ProfessionalModelReviewContractError(
        f"review_context {field} contains an unsupported value"
    )


def _normalize_optional_text(value: Any, *, field: str, limit: int = 1_000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfessionalModelReviewContractError(
            f"review_context {field} must be a string"
        )
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise ProfessionalModelReviewContractError(
            f"review_context {field} is oversized"
        )
    if _contains_local_filesystem_path(text):
        raise ProfessionalModelReviewContractError(
            f"review_context {field} must not contain local filesystem paths"
        )
    return text


def _normalize_as_of(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed_datetime = value
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 64 or _contains_local_filesystem_path(text):
            raise ProfessionalModelReviewContractError(
                f"{field} must be an ISO date or timezone-aware datetime"
            )
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError as exc:
                raise ProfessionalModelReviewContractError(
                    f"{field} must be an ISO date or timezone-aware datetime"
                ) from exc
        try:
            parsed_datetime = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProfessionalModelReviewContractError(
                f"{field} must be an ISO date or timezone-aware datetime"
            ) from exc
    else:
        raise ProfessionalModelReviewContractError(
            f"{field} must be an ISO date or timezone-aware datetime"
        )
    if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
        raise ProfessionalModelReviewContractError(
            f"{field} datetime must include a timezone"
        )
    return (
        parsed_datetime.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_evidence_locator(value: Any) -> dict[str, str | None] | None:
    if value is None:
        return None
    if isinstance(value, str):
        locator: Mapping[str, Any] = {"url": value}
    elif isinstance(value, Mapping):
        locator = value
    else:
        raise ProfessionalModelReviewContractError(
            "review_context evidence_locator must be a string or object"
        )
    unknown = sorted(set(locator) - _EVIDENCE_LOCATOR_FIELDS)
    if unknown:
        raise ProfessionalModelReviewContractError(
            "review_context evidence_locator contains unknown keys: "
            + ", ".join(str(item) for item in unknown)
        )
    url = _normalize_optional_text(locator.get("url"), field="evidence_locator.url", limit=2_048)
    sheet = _normalize_optional_text(locator.get("sheet"), field="evidence_locator.sheet", limit=100)
    coordinate = _normalize_optional_text(
        locator.get("coordinate"), field="evidence_locator.coordinate", limit=20
    )
    if url is not None:
        parsed = urlsplit(url)
        is_public_web = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        is_api_route = not parsed.scheme and not parsed.netloc and parsed.path.startswith("/api/")
        if not (is_public_web or is_api_route):
            raise ProfessionalModelReviewContractError(
                "review_context evidence_locator.url must be HTTP(S) or an /api/ route"
            )
    if coordinate is not None:
        coordinate = coordinate.upper()
        if not _CELL_RE.fullmatch(coordinate):
            raise ProfessionalModelReviewContractError(
                "review_context evidence_locator.coordinate must be an A1 coordinate"
            )
    if url is None and (sheet is None or coordinate is None):
        raise ProfessionalModelReviewContractError(
            "review_context evidence_locator requires a URL or sheet and coordinate"
        )
    return {"url": url, "sheet": sheet, "coordinate": coordinate}


def normalize_preview_review_context(
    review_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate and canonicalize optional PM preview evidence metadata."""

    if review_context is None:
        review_context = {}
    if not isinstance(review_context, Mapping):
        raise ProfessionalModelReviewContractError(
            "review_context must be an object"
        )
    unknown = sorted(set(review_context) - _REVIEW_CONTEXT_FIELDS)
    if unknown:
        raise ProfessionalModelReviewContractError(
            "review_context contains unknown keys: "
            + ", ".join(str(item) for item in unknown)
        )

    raw_dependencies = review_context.get("downstream_dependencies")
    if raw_dependencies is None:
        dependencies: list[str] = []
    elif isinstance(raw_dependencies, (str, bytes)) or not isinstance(
        raw_dependencies, Sequence
    ):
        raise ProfessionalModelReviewContractError(
            "review_context downstream_dependencies must be an array"
        )
    else:
        if len(raw_dependencies) > MAX_CONTEXT_ITEMS:
            raise ProfessionalModelReviewContractError(
                "review_context downstream_dependencies contains too many items"
            )
        dependencies = []
        for item in raw_dependencies:
            dependency = _normalize_optional_text(
                item,
                field="downstream_dependencies",
                limit=200,
            )
            if dependency is None:
                raise ProfessionalModelReviewContractError(
                    "review_context downstream_dependencies contains a blank item"
                )
            dependencies.append(dependency)

    normalized = {
        "source_ref": _normalize_optional_text(
            review_context.get("source_ref"), field="source_ref"
        ),
        "method": _normalize_optional_text(
            review_context.get("method"), field="method"
        ),
        "as_of": _normalize_as_of(
            review_context.get("as_of"), field="review_context as_of"
        ),
        "evidence_locator": _normalize_evidence_locator(
            review_context.get("evidence_locator")
        ),
        "materiality": _normalize_context_value(
            review_context.get("materiality"), field="materiality"
        ),
        "impact": _normalize_context_value(
            review_context.get("impact"), field="impact"
        ),
        "downstream_dependencies": sorted(set(dependencies)),
    }
    if len(canonical_json(normalized).encode("utf-8")) > MAX_REVIEW_CONTEXT_BYTES:
        raise ProfessionalModelReviewContractError(
            "review_context exceeds the maximum canonical size"
        )
    return normalized


def _normalize_required_check_ids(
    required_core_ids: Iterable[str] | Any,
) -> tuple[set[str], list[str]]:
    reasons: list[str] = []
    if isinstance(required_core_ids, (str, bytes)):
        raw_ids: list[Any] = []
        reasons.append("required_core_check_ids_invalid")
    else:
        try:
            raw_ids = list(required_core_ids)
        except TypeError:
            raw_ids = []
            reasons.append("required_core_check_ids_invalid")
    seen: set[str] = set()
    for index, raw_id in enumerate(raw_ids):
        check_id = str(raw_id or "").strip()
        if not _CHECK_ID_RE.fullmatch(check_id):
            reasons.append(f"required_core_check_id_invalid:{index}")
            continue
        if check_id in seen:
            reasons.append(f"required_check_id_duplicate:{check_id}")
        seen.add(check_id)
    for semantic_id in SEMANTIC_QA_CHECK_IDS:
        if semantic_id in seen:
            reasons.append(f"required_check_id_duplicate:{semantic_id}")
        seen.add(semantic_id)
    return seen, reasons


def _semantic_evidence_is_valid(
    check_id: str,
    raw_evidence: Any,
    *,
    canonical_hash_fn: HashCallback | None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(raw_evidence, Mapping):
        return [f"semantic_evidence_missing:{check_id}"]
    if set(raw_evidence) != _SEMANTIC_EVIDENCE_FIELDS:
        reasons.append(f"semantic_evidence_keys_invalid:{check_id}")

    normalized: dict[str, Any] = {}
    schema = raw_evidence.get("schema")
    schema = str(schema or "").strip()
    if not _SCHEMA_RE.fullmatch(schema):
        reasons.append(f"semantic_evidence_field_invalid:{check_id}:schema")
    normalized["schema"] = schema

    for field in ("source", "method"):
        try:
            normalized[field] = _normalize_optional_text(
                raw_evidence.get(field),
                field=f"semantic_evidence.{field}",
            )
        except ProfessionalModelReviewContractError:
            normalized[field] = None
            reasons.append(f"semantic_evidence_field_invalid:{check_id}:{field}")
        if normalized[field] is None:
            reasons.append(f"semantic_evidence_field_invalid:{check_id}:{field}")

    try:
        normalized["as_of"] = _normalize_as_of(
            raw_evidence.get("as_of"), field="semantic_evidence as_of"
        )
    except ProfessionalModelReviewContractError:
        normalized["as_of"] = None
        reasons.append(f"semantic_evidence_field_invalid:{check_id}:as_of")
    if normalized["as_of"] is None:
        reasons.append(f"semantic_evidence_field_invalid:{check_id}:as_of")

    details = raw_evidence.get("details")
    if not isinstance(details, Mapping) or not details:
        normalized["details"] = {}
        reasons.append(f"semantic_evidence_details_invalid:{check_id}")
    else:
        try:
            normalized["details"] = _normalize_context_value(
                details,
                field="semantic_evidence.details",
            )
        except ProfessionalModelReviewContractError:
            normalized["details"] = {}
            reasons.append(f"semantic_evidence_details_invalid:{check_id}")

    try:
        evidence_size = len(canonical_json(normalized).encode("utf-8"))
    except (TypeError, ValueError):
        evidence_size = MAX_SEMANTIC_EVIDENCE_BYTES + 1
    if evidence_size > MAX_SEMANTIC_EVIDENCE_BYTES:
        reasons.append(f"semantic_evidence_oversized:{check_id}")

    observed_hash = str(raw_evidence.get("evidence_hash") or "").strip()
    if not _SHA256_RE.fullmatch(observed_hash):
        reasons.append(f"semantic_evidence_hash_invalid:{check_id}")
    else:
        expected_hash = _compute_hash(normalized, canonical_hash_fn)
        if observed_hash != expected_hash:
            reasons.append(f"semantic_evidence_hash_mismatch:{check_id}")
    return sorted(set(reasons))


def build_decision_semantic_qa_verification(
    qa_checks: Sequence[Mapping[str, Any]] | Any,
    *,
    required_core_ids: Iterable[str],
    canonical_hash_fn: HashCallback | None = None,
) -> dict[str, Any]:
    """Verify the exact positive-list QA contract required for sign-off.

    The observed check-ID set must exactly equal ``required_core_ids`` plus the
    four semantic IDs in :data:`SEMANTIC_QA_CHECK_IDS`.  Each ID must occur once
    with the literal status ``PASS``.  Semantic checks additionally require a
    self-contained evidence object whose canonical hash recomputes.
    """

    required, reasons = _normalize_required_check_ids(required_core_ids)
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(qa_checks, (str, bytes)) or not isinstance(qa_checks, Sequence):
        reasons.append("qa_checks_missing")
        qa_checks = []
    for index, raw_check in enumerate(qa_checks):
        if not isinstance(raw_check, Mapping):
            reasons.append(f"qa_check_not_object:{index}")
            continue
        check_id = str(raw_check.get("check_id") or "").strip()
        if not _CHECK_ID_RE.fullmatch(check_id):
            reasons.append(f"qa_check_id_invalid:{index}")
            continue
        by_id.setdefault(check_id, []).append(raw_check)

    observed = set(by_id)
    for check_id in sorted(required - observed):
        reasons.append(f"qa_check_set_missing:{check_id}")
    for check_id in sorted(observed - required):
        reasons.append(f"qa_check_set_unknown:{check_id}")

    failed: set[str] = set(required - observed)
    for check_id, entries in sorted(by_id.items()):
        if len(entries) != 1:
            reasons.append(f"qa_check_id_duplicate:{check_id}")
            if check_id in required:
                failed.add(check_id)
        for raw_check in entries:
            status = str(raw_check.get("status") or "").strip()
            if status != "PASS":
                reasons.append(
                    f"qa_check_status_not_pass:{check_id}:{status or 'blank'}"
                )
                if check_id in required:
                    failed.add(check_id)

        if check_id in SEMANTIC_QA_CHECK_IDS and len(entries) == 1:
            evidence_reasons = _semantic_evidence_is_valid(
                check_id,
                entries[0].get("semantic_evidence"),
                canonical_hash_fn=canonical_hash_fn,
            )
            reasons.extend(evidence_reasons)
            if evidence_reasons:
                failed.add(check_id)

    normalized_reasons = sorted(set(reasons))
    return {
        "verified": not normalized_reasons,
        "reasons": normalized_reasons,
        "required": sorted(required),
        "observed": sorted(observed),
        "failed": sorted(failed),
    }


__all__ = (
    "MAX_REVIEW_CONTEXT_BYTES",
    "SEMANTIC_QA_CHECK_IDS",
    "ProfessionalModelReviewContractError",
    "build_decision_semantic_qa_verification",
    "canonical_hash",
    "canonical_json",
    "enrich_pm_driver_requirement",
    "normalize_preview_review_context",
)
