from collections import defaultdict
from typing import Any, List, Literal

from pydantic import TypeAdapter, ValidationError

from app.schemas import PipelineResult, PortfolioSummary, PortfolioTrendPoint, ScanFinding, ScanResult

_SCAN_HISTORY: list[ScanResult] = []
_MAX_SCAN_HISTORY = 500
_SCAN_RESULT_LIST_ADAPTER = TypeAdapter(List[ScanResult])
_SCAN_RESULT_ADAPTER = TypeAdapter(ScanResult)


def _risk_level(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "low"
    return "minimal"


def build_scan_result(result: PipelineResult) -> ScanResult:
    severity_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    findings: list[ScanFinding] = []

    for finding in result.text_findings:
        severity_counts[str(finding.severity)] += 1
        category_counts[finding.category] += 1
        findings.append(ScanFinding(severity=finding.severity, category=finding.category))

    scan_id = result.report.scan_id if result.report else result.normalized.target
    timestamp = result.report.timestamp if result.report else result.normalized.metadata.get("timestamp")
    if timestamp is None and result.report is None:
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc)

    return ScanResult(
        scan_id=scan_id,
        target=result.normalized.target,
        risk_score=round(result.combined_score, 2),
        max_severity_found=result.report.max_severity_found if result.report else max(
            (f.severity for f in result.text_findings),
            default=0,
        ),
        timestamp=timestamp,
        finding_count=len(result.text_findings),
        severity_counts=dict(severity_counts),
        category_counts=dict(category_counts),
        findings=findings,
    )


def record_scan_result(scan: ScanResult) -> None:
    _SCAN_HISTORY.append(scan)
    if len(_SCAN_HISTORY) > _MAX_SCAN_HISTORY:
        del _SCAN_HISTORY[0 : len(_SCAN_HISTORY) - _MAX_SCAN_HISTORY]


def list_scan_results() -> List[ScanResult]:
    return list(_SCAN_HISTORY)


def clear_scan_history() -> None:
    _SCAN_HISTORY.clear()


def parse_scan_list_payload(payload: Any) -> List[ScanResult]:
    """Ingest scan lists from raw JSON or common tool-output wrapper shapes."""
    candidates: list[Any] = []

    if isinstance(payload, list):
        candidates.append(payload)

    if isinstance(payload, dict):
        if "scan_id" in payload and "risk_score" in payload:
            candidates.append([payload])

        for key in ("scans", "results", "items", "records"):
            if isinstance(payload.get(key), list):
                candidates.append(payload[key])

        for wrapper_key in ("output", "result", "data", "tool_output", "payload"):
            wrapped = payload.get(wrapper_key)
            if isinstance(wrapped, list):
                candidates.append(wrapped)
                continue

            if isinstance(wrapped, dict):
                for key in ("scans", "results", "items", "records"):
                    if isinstance(wrapped.get(key), list):
                        candidates.append(wrapped[key])

    for candidate in candidates:
        try:
            return _SCAN_RESULT_LIST_ADAPTER.validate_python(candidate)
        except ValidationError:
            continue

    raise ValueError(
        "Invalid portfolio JSON payload. Provide a scan list, a scan object, or a wrapper containing scans."
    )


def _finding_severity_to_int(severity: int | str) -> int:
    if isinstance(severity, int):
        return max(severity, 0)

    normalized = str(severity).strip().lower()
    if normalized.isdigit():
        return max(int(normalized), 0)

    mapping = {
        "critical": 5,
        "high": 4,
        "medium": 3,
        "low": 2,
        "minimal": 1,
    }
    return mapping.get(normalized, 2)


def _derive_scan_counts(findings: list[ScanFinding]) -> tuple[dict[str, int], dict[str, int], int]:
    severity_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    max_severity = 0

    for finding in findings:
        severity_value = _finding_severity_to_int(finding.severity)
        severity_counts[str(severity_value)] += 1
        category_counts[finding.category] += 1
        max_severity = max(max_severity, severity_value)

    return dict(severity_counts), dict(category_counts), max_severity


def _coerce_count_map(raw_value: Any, field_name: str) -> dict[str, int] | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be an object map")

    converted: dict[str, int] = {}
    for key, value in raw_value.items():
        try:
            converted[str(key)] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} has non-numeric value for key '{key}'") from exc
    return converted


def _extract_scan_findings(raw_value: Any) -> list[ScanFinding]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError("findings must be a list")

    findings: list[ScanFinding] = []
    for index, finding in enumerate(raw_value):
        if not isinstance(finding, dict):
            raise ValueError(f"findings[{index}] must be an object")
        if "severity" not in finding or "category" not in finding:
            raise ValueError(f"findings[{index}] must include severity and category")
        findings.append(
            ScanFinding.model_validate(
                {
                    "severity": finding["severity"],
                    "category": finding["category"],
                }
            )
        )
    return findings


def _normalize_report_like_payload(report_payload: dict[str, Any], target_override: str | None = None) -> ScanResult:
    scan_id = report_payload.get("scan_id")
    risk_score = report_payload.get("risk_score")
    if scan_id is None or risk_score is None:
        raise ValueError("scan object must contain scan_id and risk_score")

    findings = _extract_scan_findings(report_payload.get("findings"))
    derived_severity_counts, derived_category_counts, derived_max_severity = _derive_scan_counts(findings)

    severity_counts = _coerce_count_map(report_payload.get("severity_counts"), "severity_counts")
    category_counts = _coerce_count_map(report_payload.get("category_counts"), "category_counts")
    if severity_counts is None:
        severity_counts = derived_severity_counts
    if category_counts is None:
        category_counts = derived_category_counts

    max_severity_found_raw = report_payload.get("max_severity_found")
    if max_severity_found_raw is None:
        max_severity_found = derived_max_severity
    else:
        try:
            max_severity_found = int(max_severity_found_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_severity_found must be an integer") from exc

    finding_count_raw = report_payload.get("finding_count")
    if finding_count_raw is None:
        finding_count = len(findings)
    else:
        try:
            finding_count = int(finding_count_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("finding_count must be an integer") from exc

    metadata_target: str | None = None
    metadata = report_payload.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("target"), str):
        metadata_target = metadata["target"]

    payload_target = report_payload.get("target")
    target = target_override or (payload_target if isinstance(payload_target, str) else None) or metadata_target or "unknown"

    normalized_payload: dict[str, Any] = {
        "scan_id": scan_id,
        "target": target,
        "risk_score": risk_score,
        "max_severity_found": max(max_severity_found, 0),
        "finding_count": max(finding_count, 0),
        "severity_counts": severity_counts,
        "category_counts": category_counts,
        "findings": [finding.model_dump() for finding in findings],
    }

    if report_payload.get("timestamp") is not None:
        normalized_payload["timestamp"] = report_payload["timestamp"]

    try:
        return _SCAN_RESULT_ADAPTER.validate_python(normalized_payload)
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg", "invalid scan object")
        raise ValueError(f"Invalid normalized scan: {msg}") from exc


def _normalize_single_scan_candidate(candidate: Any) -> ScanResult:
    if not isinstance(candidate, dict):
        try:
            return _SCAN_RESULT_ADAPTER.validate_python(candidate)
        except ValidationError as exc:
            msg = exc.errors()[0].get("msg", "scan candidate must be a JSON object")
            raise ValueError(msg) from exc

    nested_report = candidate.get("report")
    if isinstance(nested_report, dict):
        target_override: str | None = None
        normalized = candidate.get("normalized")
        if isinstance(normalized, dict) and isinstance(normalized.get("target"), str):
            target_override = normalized["target"]
        elif isinstance(candidate.get("target"), str):
            target_override = candidate["target"]
        return _normalize_report_like_payload(nested_report, target_override=target_override)

    if "scan_id" in candidate and "risk_score" in candidate:
        target_override = candidate.get("target") if isinstance(candidate.get("target"), str) else None
        return _normalize_report_like_payload(candidate, target_override=target_override)

    try:
        return _SCAN_RESULT_ADAPTER.validate_python(candidate)
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg", "unsupported scan object shape")
        raise ValueError(msg) from exc


def _collect_scan_candidates(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return list(payload)

    if not isinstance(payload, dict):
        return []

    candidates: list[Any] = []

    if any(key in payload for key in ("scan_id", "report", "combined_score", "risk_score")):
        candidates.append(payload)

    for key in ("scans", "results", "items", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(value)

    for wrapper_key in ("output", "result", "data", "tool_output", "payload"):
        wrapped = payload.get(wrapper_key)
        if isinstance(wrapped, list):
            candidates.extend(wrapped)
            continue
        if isinstance(wrapped, dict):
            candidates.extend(_collect_scan_candidates(wrapped))

    return candidates


def normalize_ingest_payload(payload: Any) -> tuple[List[ScanResult], list[dict[str, Any]]]:
    """Normalize external payloads into ScanResult records for ingestion.

    Returns accepted scans and structured per-candidate errors.
    """
    candidates = _collect_scan_candidates(payload)
    if not candidates:
        raise ValueError("Invalid ingestion payload. Provide scan data or a wrapper with scans/report output.")

    accepted: list[ScanResult] = []
    errors: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        try:
            accepted.append(_normalize_single_scan_candidate(candidate))
        except ValueError as exc:
            errors.append({"index": index, "reason": str(exc)})

    if not accepted:
        raise ValueError("No valid scans found in payload.")

    return accepted, errors


def _normalize_finding_severity(severity: int | str) -> Literal["critical", "high", "medium", "low"]:
    if isinstance(severity, int):
        if severity >= 5:
            return "critical"
        if severity == 4:
            return "high"
        if severity == 3:
            return "medium"
        return "low"

    normalized = str(severity).strip().lower()
    if normalized.isdigit():
        return _normalize_finding_severity(int(normalized))
    if normalized == "critical":
        return "critical"
    if normalized == "high":
        return "high"
    if normalized == "medium":
        return "medium"
    return "low"


def _normalize_severity_filter(severity: str) -> Literal["critical", "high", "medium", "low"]:
    normalized = severity.strip().lower()
    mapping: dict[str, Literal["critical", "high", "medium", "low"]] = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }
    if normalized in mapping:
        return mapping[normalized]
    raise ValueError("Invalid severity filter. Use one of: critical, high, medium, low")


def _filter_findings(
    findings: list[ScanFinding],
    severity_filter: Literal["critical", "high", "medium", "low"] | None,
) -> list[ScanFinding]:
    if severity_filter is None:
        return list(findings)
    return [finding for finding in findings if _normalize_finding_severity(finding.severity) == severity_filter]


def filter_scans_by_severity(
    scans: List[ScanResult],
    severity_filter: str | None = None,
) -> List[ScanResult]:
    """Filter findings within each scan by severity before aggregation."""
    if severity_filter is None:
        return list(scans)

    normalized_filter = _normalize_severity_filter(severity_filter)

    filtered_scans: list[ScanResult] = []
    for scan in scans:
        filtered_findings = _filter_findings(scan.findings, normalized_filter)

        if filtered_findings:
            severity_counts: dict[str, int] = defaultdict(int)
            category_counts: dict[str, int] = defaultdict(int)
            max_severity = 0

            for finding in filtered_findings:
                if isinstance(finding.severity, int):
                    severity_value = finding.severity
                else:
                    mapped = _normalize_finding_severity(finding.severity)
                    severity_value = {"critical": 5, "high": 4, "medium": 3, "low": 2}[mapped]

                severity_counts[str(severity_value)] += 1
                category_counts[finding.category] += 1
                max_severity = max(max_severity, severity_value)

            filtered_scans.append(
                scan.model_copy(
                    update={
                        "findings": filtered_findings,
                        "finding_count": len(filtered_findings),
                        "severity_counts": dict(severity_counts),
                        "category_counts": dict(category_counts),
                        "max_severity_found": max_severity,
                    }
                )
            )
            continue

        # No granular findings to filter; preserve scan metadata with zeroed finding aggregates.
        filtered_scans.append(
            scan.model_copy(
                update={
                    "findings": [],
                    "finding_count": 0,
                    "severity_counts": {},
                    "category_counts": {},
                    "max_severity_found": 0,
                }
            )
        )

    return filtered_scans


def aggregate_scans(scan_list: List[ScanResult]) -> PortfolioSummary:
    """Aggregate scan-level input into portfolio-level executive metrics."""
    if not scan_list:
        return PortfolioSummary(
            total_scans=0,
            average_score=0.0,
            highest_score=0.0,
            critical_count=0,
            distribution={"Critical": 0, "High": 0, "Medium": 0, "Low": 0},
            severity_distribution={"Critical": 0, "High": 0, "Medium": 0, "Low": 0},
            category_breakdown={},
            risk_trend=[],
        )

    severity_distribution: dict[str, int] = {
        "Critical": 0,
        "High": 0,
        "Medium": 0,
        "Low": 0,
    }
    category_breakdown: dict[str, int] = defaultdict(int)
    critical_findings = 0

    for scan in scan_list:
        if scan.findings:
            for finding in scan.findings:
                severity_level = _normalize_finding_severity(finding.severity)
                if severity_level == "critical":
                    severity_distribution["Critical"] += 1
                    critical_findings += 1
                elif severity_level == "high":
                    severity_distribution["High"] += 1
                elif severity_level == "medium":
                    severity_distribution["Medium"] += 1
                else:
                    severity_distribution["Low"] += 1

                category_breakdown[finding.category] += 1
            continue

        # Backward compatibility for scans persisted without raw finding entries.
        for raw_severity, count in scan.severity_counts.items():
            try:
                level = _normalize_finding_severity(int(raw_severity))
            except ValueError:
                level = _normalize_finding_severity(raw_severity)

            if level == "critical":
                severity_distribution["Critical"] += count
                critical_findings += count
            elif level == "high":
                severity_distribution["High"] += count
            elif level == "medium":
                severity_distribution["Medium"] += count
            else:
                severity_distribution["Low"] += count

        for category, count in scan.category_counts.items():
            category_breakdown[category] += count

    scores = [scan.risk_score for scan in scan_list]
    risk_trend = [
        PortfolioTrendPoint(timestamp=scan.timestamp, scan_id=scan.scan_id, score=scan.risk_score)
        for scan in scan_list
    ]

    return PortfolioSummary(
        total_scans=len(scan_list),
        average_score=round(sum(scores) / len(scores), 2),
        highest_score=round(max(scores), 2),
        critical_count=critical_findings,
        distribution=dict(severity_distribution),
        severity_distribution=dict(severity_distribution),
        category_breakdown=dict(category_breakdown),
        risk_trend=risk_trend,
    )


def calculate_portfolio_summary(scans: List[ScanResult]) -> PortfolioSummary:
    if not scans:
        return PortfolioSummary(
            total_scans=0,
            average_score=0.0,
            highest_score=0.0,
            critical_count=0,
            distribution={"critical": 0, "high": 0, "medium": 0, "low": 0, "minimal": 0},
            severity_distribution={"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
            category_breakdown={},
            risk_trend=[],
        )

    distribution: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "minimal": 0}
    severity_distribution: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    category_breakdown: dict[str, int] = defaultdict(int)

    for scan in scans:
        distribution[_risk_level(scan.risk_score)] += 1

        for severity, count in scan.severity_counts.items():
            severity_distribution[severity] = severity_distribution.get(severity, 0) + count

        for category, count in scan.category_counts.items():
            category_breakdown[category] += count

    risk_trend = [
        PortfolioTrendPoint(timestamp=scan.timestamp, scan_id=scan.scan_id, score=scan.risk_score)
        for scan in sorted(scans, key=lambda item: item.timestamp)
    ]

    scores = [scan.risk_score for scan in scans]
    return PortfolioSummary(
        total_scans=len(scans),
        average_score=round(sum(scores) / len(scores), 2),
        highest_score=round(max(scores), 2),
        critical_count=distribution["critical"],
        distribution=distribution,
        severity_distribution=severity_distribution,
        category_breakdown=dict(category_breakdown),
        risk_trend=risk_trend,
    )


def sort_scans_by_risk(scans: List[ScanResult], order: Literal["asc", "desc"] = "desc") -> List[ScanResult]:
    return sorted(scans, key=lambda item: item.risk_score, reverse=(order != "asc"))
