
import hashlib
import re
from typing import Any

from app.core.logging import get_logger
from app.schemas import (
    DetectionFlags,
    NormalizedInput,
    PipelineRequest,
    PipelineResult,
    PolicySet,
    RuleSet,
    TextScanResult,
)
from app.services.detection import detect
from app.services.normalizer import normalize, normalize_text
from app.services.policy_engine import (
    aggregate_decision,
    context_from_pipeline,
    evaluate_policies,
)
from app.services.policy_store import load_policies
from app.services.report_generator import build_matched_rule_details, build_report_from_pipeline
from app.services.rule_engine import (
    cvss_combined_score,
    evaluate,
    scan_text,
    text_scan_rule_matches,
)
from app.services.rules_loader import load_rules

logger = get_logger(__name__)


_FINGERPRINT_NORMALIZER = re.compile(r"\s+")


def _compute_prompt_fingerprint(content: str) -> str:
    """Stable SHA-256 fingerprint of the normalized prompt for the Correlation Engine.

    The fingerprint collapses whitespace and lowercases the content so trivially
    different copies of the same prompt collide on the same canonical key. The
    plaintext is never stored downstream (only the hash crosses the wire).
    """
    if not content:
        return "sha256:empty"
    normalized = _FINGERPRINT_NORMALIZER.sub(" ", content.strip().lower())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── Stage helpers ─────────────────────────────────────────────────────────────


def _stage_normalize_from_request(req: PipelineRequest) -> NormalizedInput:
    """Stage 1 - Normalize: build canonical NormalizedInput from the prompt."""
    content = req.prompt or req.text or ""
    metadata: dict[str, Any] = {}
    if req.report_branding:
        metadata["report_branding"] = req.report_branding.model_dump(exclude_none=True)
    return normalize_text(content, target=req.target, metadata=metadata)


def _stage_detect(normalized: NormalizedInput) -> DetectionFlags:
    """Stage 2 - Detection utilities."""
    return detect(normalized)


def _build_rule_context(
    normalized: NormalizedInput,
    detection: DetectionFlags,
    text_result: TextScanResult,
) -> dict[str, Any]:
    """Build the context dict consumed by the YAML context rule engine.

    Surfaces normalized metadata, detection flags, text-scan signals, and
    convenience derived counts (e.g. distinct families, max severity) so
    governance-style rules can express predicates without re-parsing input.
    """
    text_finding_ids = sorted({f.rule_id for f in text_result.findings})
    families = sorted({f.family for f in text_result.findings if f.family})

    context: dict[str, Any] = dict(normalized.metadata)
    context.update(
        {
            "target": normalized.target,
            "input_kind": normalized.input_kind,
            "content_length": normalized.content_length,
            "content": normalized.content,
            "encoding": normalized.encoding,
            "content_type": detection.content_type,
            "detected_language": detection.detected_language,
            "token_count": detection.token_count,
            "line_count": detection.line_count,
            "detection_flags": list(detection.flags),
            "text_finding_count": len(text_result.findings),
            "text_matched_count": text_result.matched_count,
            "text_scan_score": text_result.total_score,
            "text_finding_rule_ids": text_finding_ids,
            "text_finding_families": families,
            "max_text_severity": max(
                (f.severity for f in text_result.findings), default=0
            ),
        }
    )
    # Each detection flag is also lifted to a top-level boolean (e.g.
    # ``contains_email: true``) so YAML rules can reference flags directly.
    for flag in detection.flags:
        context[flag] = True
    return context


def _stage_rule_engine(
    normalized: NormalizedInput,
    rule_set: RuleSet,
    detection: DetectionFlags,
) -> PipelineResult:
    """Stage 3 - Run context rules + text-scan engine, then combine scores."""
    txt_result = scan_text(normalized.content, rule_set)
    text_matches = text_scan_rule_matches(txt_result, rule_set)

    rule_context = _build_rule_context(normalized, detection, txt_result)
    ctx_eval = evaluate(rule_context, rule_set)

    # Merge context-rule matches with text-scan rule matches so the report
    # surfaces both engines under a single `matched_rules` list, which is the
    # contract expected by ``build_report_from_pipeline``.
    matched_rules = list(ctx_eval.matched_rules) + list(text_matches)
    matched_passed = ctx_eval.passed_count + sum(1 for r in text_matches if r.matched)
    matched_failed = ctx_eval.failed_count + sum(1 for r in text_matches if not r.matched)

    combined = cvss_combined_score(
        ctx_eval.total_score, txt_result.findings, rule_set.text_scan_rules
    )
    matched_rule_details = build_matched_rule_details(txt_result.findings, rule_set)

    return PipelineResult(
        input_prompt=normalized.content,
        matched_rule_details=matched_rule_details,
        normalized=normalized,
        detection=detection,
        matched_rules=matched_rules,
        context_score=ctx_eval.total_score,
        passed_count=matched_passed,
        failed_count=matched_failed,
        text_findings=txt_result.findings,
        text_scan_score=txt_result.total_score,
        text_matched_count=txt_result.matched_count,
        combined_score=combined,
        prompt_fingerprint=_compute_prompt_fingerprint(normalized.content),
    )


def _stage_policy_engine(
    result: PipelineResult,
    detection: DetectionFlags,
    policy_set: PolicySet | None = None,
) -> PipelineResult:
    """Stage 4 - Evaluate governance policies and attach decisions to the result."""
    if policy_set is None:
        policy_set = load_policies()
    if not policy_set.policies:
        return result.model_copy(update={"policy_decisions": [], "final_decision": "allow"})

    context = context_from_pipeline(result, detection)
    decisions = evaluate_policies(context, policy_set)
    final = aggregate_decision(decisions)
    return result.model_copy(
        update={"policy_decisions": decisions, "final_decision": final}
    )


# ── Public pipeline functions ─────────────────────────────────────────────────


def run_pipeline(
    req: PipelineRequest,
    rule_set: RuleSet | None = None,
    policy_set: PolicySet | None = None,
) -> PipelineResult:
    """Execute the full pipeline: Normalize, Detect, Rule engines, Policy engine.

    Args:
        req:        Validated pipeline request.
        rule_set:   Optional pre-loaded rule set (loaded from disk when ``None``).
        policy_set: Optional pre-loaded policy set (loaded from disk when ``None``).

    Returns:
        A fully populated :class:`PipelineResult` including governance decisions.
    """
    if rule_set is None:
        rule_set = load_rules()

    logger.info("Pipeline start: target=%s", req.target)

    # Stage 1 - Normalize
    normalized = _stage_normalize_from_request(req)
    logger.debug("Normalized: kind=%s len=%d", normalized.input_kind, normalized.content_length)

    # Stage 2 - Detect
    detection = _stage_detect(normalized)
    logger.debug("Detection: type=%s flags=%s", detection.content_type, detection.flags)

    # Stage 3 - Rule engines (context + text-scan)
    result = _stage_rule_engine(normalized, rule_set, detection)

    # Stage 4 - Policy Engine (governance gates)
    result = _stage_policy_engine(result, detection, policy_set=policy_set)

    # Build exportable JSON report (aware of policy decisions)
    result = result.model_copy(update={"report": build_report_from_pipeline(result, rule_set)})

    logger.info(
        "Pipeline complete: target=%s ctx_score=%.2f text_score=%.2f combined=%.2f decision=%s",
        req.target,
        result.context_score,
        result.text_scan_score,
        result.combined_score,
        result.final_decision,
    )
    return result


def run_pipeline_raw(
    raw: str | bytes | dict[str, Any],
    target: str = "raw-input",
    metadata: dict[str, Any] | None = None,
    filename: str | None = None,
    rule_set: RuleSet | None = None,
    policy_set: PolicySet | None = None,
) -> PipelineResult:
    """Convenience wrapper: accepts raw str / bytes / dict directly.

    Useful for programmatic callers and unit tests without building a
    ``PipelineRequest``.
    """
    normalized = normalize(raw, target=target, metadata=metadata, filename=filename)

    if rule_set is None:
        rule_set = load_rules()

    detection = _stage_detect(normalized)
    result = _stage_rule_engine(normalized, rule_set, detection)
    result = _stage_policy_engine(result, detection, policy_set=policy_set)
    result = result.model_copy(update={"report": build_report_from_pipeline(result, rule_set)})
    return result


def get_or_run_pipeline(
    request: Any,
    payload: PipelineRequest,
    rule_set: RuleSet | None = None,
    policy_set: PolicySet | None = None,
) -> PipelineResult:
    """Reuse the middleware's cached pipeline result, or run the pipeline now.

    The :class:`PolicyEnforcementMiddleware` runs the full pipeline before the
    handler is invoked and stashes the resulting :class:`EnforcementOutcome`
    on ``request.state``. Handlers that would otherwise call ``run_pipeline``
    a second time should use this helper to avoid the duplicate work; if the
    middleware did not run (e.g. unprotected route, mode=off, oversized body)
    we transparently fall through to ``run_pipeline``.
    """
    from app.middleware.policy_enforcement import REQUEST_STATE_ATTR

    state = getattr(request, "state", None)
    outcome = getattr(state, REQUEST_STATE_ATTR, None) if state is not None else None
    if outcome is not None and outcome.pipeline_result is not None:
        return outcome.pipeline_result

    return run_pipeline(payload, rule_set=rule_set, policy_set=policy_set)
