from app.schemas import (
    PipelineRequest,
    PortfolioRiskDistribution,
    PortfolioRollupResponse,
    PortfolioScanSummary,
    RuleSet,
)
from app.services.pipeline import run_pipeline


def _risk_level(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "LOW"
    return "MINIMAL"


def _bump_risk_distribution(distribution: PortfolioRiskDistribution, level: str) -> None:
    key = level.lower()
    current = getattr(distribution, key)
    setattr(distribution, key, current + 1)


def build_portfolio_rollup(scans: list[PipelineRequest], rule_set: RuleSet) -> PortfolioRollupResponse:
    scan_summaries: list[PortfolioScanSummary] = []
    distribution = PortfolioRiskDistribution()
    total_findings = 0

    for index, scan in enumerate(scans, start=1):
        result = run_pipeline(scan, rule_set=rule_set)
        score = round(result.combined_score, 2)
        level = _risk_level(score)
        _bump_risk_distribution(distribution, level)

        finding_count = len(result.text_findings)
        total_findings += finding_count

        scan_id = result.report.scan_id if result.report else f"scan-{index}"
        scan_summaries.append(
            PortfolioScanSummary(
                index=index,
                scan_id=scan_id,
                target=result.normalized.target,
                risk_score=score,
                risk_level=level,
                finding_count=finding_count,
            )
        )

    scores = [item.risk_score for item in scan_summaries]
    top_risky_scan = max(scan_summaries, key=lambda item: item.risk_score)

    return PortfolioRollupResponse(
        scan_count=len(scan_summaries),
        portfolio_score=round(sum(scores) / len(scores), 2),
        max_risk_score=max(scores),
        min_risk_score=min(scores),
        total_findings=total_findings,
        risk_distribution=distribution,
        top_risky_scan=top_risky_scan,
        scans=scan_summaries,
    )
