
from typing import Any

from collections import defaultdict

from app.core.config import settings
from app.schemas import (
    ContextRuleSummary,
    DetectionFlags,
    MatchedFragment,
    MatchedRuleDetail,
    NormalizedInput,
    PipelineResult,
    RuleSet,
    RulesInfo,
    ScanInputResponse,
    ScanReport,
    TextFinding,
    TextScanRuleSummary,
)
from app.services.rule_engine import cvss_combined_score, severity_info


def _pipeline_metadata(result: PipelineResult) -> dict[str, Any]:
    """Combine normalizer + detection info into a flat metadata dict."""
    norm: NormalizedInput = result.normalized
    det: DetectionFlags = result.detection
    return {
        "target": norm.target,
        "input_kind": norm.input_kind,
        "content_length": norm.content_length,
        "encoding": norm.encoding,
        "content_type": det.content_type,
        "detected_language": det.detected_language,
        "token_count": det.token_count,
        "line_count": det.line_count,
        "detection_flags": det.flags,
        "context_score": result.context_score,
        "text_scan_score": result.text_scan_score,
        "passed_count": result.passed_count,
        "failed_count": result.failed_count,
        "text_matched_count": result.text_matched_count,
        "final_decision": result.final_decision,
        "policy_matched_count": sum(1 for d in result.policy_decisions if d.matched),
        "policy_total_count": len(result.policy_decisions),
        **norm.metadata,
    }


def build_matched_rule_details(
    findings: list[TextFinding],
    rule_set: RuleSet,
) -> list[MatchedRuleDetail]:
    """Build a clear view: for each matched rule, which parts of the prompt matched.

    Groups findings by rule_id and attaches rule description/family/severity from
    the rule set. Each entry shows the input fragments (evidence + offsets) that
    matched that rule.
    """
    rule_map = {r.id: r for r in rule_set.text_scan_rules}
    by_rule: dict[str, list[TextFinding]] = defaultdict(list)
    for f in findings:
        by_rule[f.rule_id].append(f)

    details: list[MatchedRuleDetail] = []
    for rule_id, rule_findings in sorted(by_rule.items()):
        rule = rule_map.get(rule_id)
        fragments = [
            MatchedFragment(
                evidence=f.evidence,
                match_start=f.match_start or 0,
                match_end=f.match_end or 0,
            )
            for f in rule_findings
        ]
        first = rule_findings[0] if rule_findings else None
        details.append(
            MatchedRuleDetail(
                rule_id=rule_id,
                description=rule.description if rule else None,
                family=first.family if first else (rule.family if rule else None),
                severity=first.severity if first else (rule.severity if rule else 1),
                matched_fragments=fragments,
            )
        )
    return details


def build_rules_info(rule_set: RuleSet) -> RulesInfo:
    """Build a :class:`RulesInfo` summary from the loaded rule set."""
    path = settings.rules_path
    ctx_summaries = [
        ContextRuleSummary(
            name=r.name,
            severity=r.severity,
            weight=r.weight,
            enabled=r.enabled,
            pattern_count=len(r.patterns),
        )
        for r in rule_set.rules
    ]
    ts_summaries = [
        TextScanRuleSummary(
            id=r.id,
            family=r.family,
            category=r.category,
            severity=r.severity,
            weight=r.weight,
            enabled=r.enabled,
            description=r.description,
        )
        for r in rule_set.text_scan_rules
    ]
    return RulesInfo(
        filename=path.name,
        filepath=str(path.resolve()),
        context_rule_count=len(rule_set.rules),
        text_scan_rule_count=len(rule_set.text_scan_rules),
        total_rule_count=len(rule_set.rules) + len(rule_set.text_scan_rules),
        context_rules=ctx_summaries,
        text_scan_rules=ts_summaries,
    )


def build_report_from_pipeline(result: PipelineResult, rule_set: RuleSet) -> ScanReport:
    max_sev, ceiling = severity_info(list(result.text_findings))
    input_prompt = result.normalized.content
    matched_rule_details = build_matched_rule_details(result.text_findings, rule_set)
    return ScanReport(
        risk_score=result.combined_score,
        max_severity_found=max_sev,
        severity_ceiling_applied=ceiling,
        input_prompt=input_prompt,
        matched_rule_details=matched_rule_details,
        findings=list(result.text_findings),
        matched_rules=[r for r in result.matched_rules if r.matched],
        rules_info=build_rules_info(rule_set),
        metadata=_pipeline_metadata(result),
        policy_decisions=list(result.policy_decisions),
        final_decision=result.final_decision,
    )


def build_report_from_scan_input(response: ScanInputResponse, rule_set: RuleSet) -> ScanReport:
    findings: list[TextFinding] = list(response.text_findings)
    meta: dict[str, Any] = {
        "target": response.target,
        "content_length": response.content_length,
        "total_score": response.total_score,
        "text_scan_score": response.text_scan_score,
        "passed_count": response.passed_count,
        "failed_count": response.failed_count,
        "text_matched_count": response.text_matched_count,
    }
    risk = cvss_combined_score(
        response.total_score, findings, rule_set.text_scan_rules
    )
    max_sev, ceiling = severity_info(findings)
    matched_rule_details = build_matched_rule_details(findings, rule_set)
    return ScanReport(
        risk_score=risk,
        max_severity_found=max_sev,
        severity_ceiling_applied=ceiling,
        input_prompt="",
        matched_rule_details=matched_rule_details,
        findings=findings,
        matched_rules=[r for r in response.matched_rules if r.matched],
        rules_info=build_rules_info(rule_set),
        metadata=meta,
    )
