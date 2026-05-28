from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.schemas import PipelineResult, ScanReport
from app.services.portfolio import calculate_portfolio_summary, list_scan_results

_SCAN_DETAILS: dict[str, dict[str, Any]] = {}
_SCAN_REPORTS: dict[str, ScanReport] = {}
_SCAN_DETAIL_ORDER: list[str] = []
_MAX_SCAN_DETAILS = 500


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


def _risk_level_label(score: float) -> str:
    level = _risk_level(score)
    if level == "minimal":
        return "low"
    return level


def record_scan_detail(result: PipelineResult) -> None:
    scan_id = result.report.scan_id if result.report else result.normalized.target
    timestamp = result.report.timestamp if result.report else None
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    category_counts: dict[str, int] = defaultdict(int)
    for finding in result.text_findings:
        category_counts[finding.category] += 1

    findings = [
        {
            "rule_id": finding.rule_id,
            "category": finding.category,
            "severity": finding.severity,
            "evidence": finding.evidence,
        }
        for finding in result.text_findings
    ]

    rule_explanations = [
        {
            "rule_id": detail.rule_id,
            "description": detail.description or "No rule description available.",
            "severity": detail.severity,
            "evidence_fragments": [fragment.evidence for fragment in detail.matched_fragments],
        }
        for detail in result.matched_rule_details
    ]

    _SCAN_DETAILS[scan_id] = {
        "scan_id": scan_id,
        "source": result.normalized.target,
        "score": round(result.combined_score, 2),
        "severity": _risk_level_label(result.combined_score),
        "date": timestamp.isoformat(),
        "category_breakdown": dict(category_counts),
        "findings": findings,
        "rule_explanations": rule_explanations,
    }
    if result.report is not None:
        _SCAN_REPORTS[scan_id] = result.report.model_copy(deep=True)

    if scan_id in _SCAN_DETAIL_ORDER:
        _SCAN_DETAIL_ORDER.remove(scan_id)
    _SCAN_DETAIL_ORDER.append(scan_id)

    while len(_SCAN_DETAIL_ORDER) > _MAX_SCAN_DETAILS:
        expired_scan_id = _SCAN_DETAIL_ORDER.pop(0)
        _SCAN_DETAILS.pop(expired_scan_id, None)
        _SCAN_REPORTS.pop(expired_scan_id, None)


def get_scan_report(scan_id: str) -> ScanReport | None:
    """Return an in-memory stored scan report by ID if available."""
    report = _SCAN_REPORTS.get(scan_id)
    if report is None:
        return None
    return report.model_copy(deep=True)


def build_dashboard_payload() -> dict[str, Any]:
    scans = list_scan_results()
    summary = calculate_portfolio_summary(scans)

    distribution = summary.distribution
    low_count = distribution.get("low", 0) + distribution.get("minimal", 0)
    risk_distribution = {
        "low": low_count,
        "medium": distribution.get("medium", 0),
        "high": distribution.get("high", 0),
        "critical": distribution.get("critical", 0),
    }

    rows: list[dict[str, Any]] = []
    sources: set[str] = set()
    for scan in scans:
        detail = _SCAN_DETAILS.get(scan.scan_id)
        severity = _risk_level_label(scan.risk_score)
        source = scan.target
        date = scan.timestamp.isoformat()
        category_breakdown = scan.category_counts
        findings: list[dict[str, Any]] = []
        rule_explanations: list[dict[str, Any]] = []

        if detail is not None:
            source = detail["source"]
            date = detail["date"]
            category_breakdown = detail["category_breakdown"]
            findings = detail["findings"]
            rule_explanations = detail["rule_explanations"]

        sources.add(source)
        rows.append(
            {
                "scan_id": scan.scan_id,
                "source": source,
                "score": round(scan.risk_score, 2),
                "severity": severity,
                "date": date,
                "finding_count": scan.finding_count,
                "max_severity_found": scan.max_severity_found,
                "category_breakdown": category_breakdown,
                "findings": findings,
                "rule_explanations": rule_explanations,
            }
        )

    return {
        "executive_summary": {
            "average_risk": summary.average_score,
            "highest_risk": summary.highest_score,
            "critical_count": summary.critical_count,
            "total_scans": summary.total_scans,
        },
        "risk_distribution": risk_distribution,
        "sources": sorted(sources),
        "scans": rows,
    }