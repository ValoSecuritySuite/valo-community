"""In-memory scan history for Community Edition overview and per-scan PDF export."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import List

from app.schemas import PipelineResult, PortfolioSummary, PortfolioTrendPoint, ScanFinding, ScanResult

_SCAN_HISTORY: list[ScanResult] = []
_MAX_SCAN_HISTORY = 500


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
