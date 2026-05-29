# Community Edition: OWASP LLM and MITRE ATLAS mapping

Valo Community Edition ships the default prompt-injection rule pack in
`app/rules/default_yml_rule.yml`. Each `family` maps to common threat
categories from the OWASP Top 10 for LLM Applications and MITRE ATLAS.

## OWASP LLM Top 10 (2025) mapping

| Valo rule family | OWASP LLM risk area | Notes |
|---|---|---|
| `instruction_override` | LLM01 Prompt Injection | Direct and indirect override phrases |
| `role_confusion` | LLM01 Prompt Injection | Identity reassignment, jailbreak personas |
| `system_prompt_extraction` | LLM07 System Prompt Leakage | Requests to reveal hidden instructions |
| `data_exfiltration` | LLM02 Sensitive Information Disclosure | Secrets, credentials, PII in prompts |
| `tool_misuse` | LLM06 Excessive Agency | Shell, file, network tool invocation language |
| `access_control` | LLM08 Excessive Agency / auth bypass | Force-admin, bypass authorization language |
| `output_manipulation` | LLM05 Improper Output Handling | Format-only and structured-output coercion |
| `indirect_injection` | LLM01 Prompt Injection | RAG / document / URL injection patterns |
| Context rules (`pii_signal`, `secret_signal`) | LLM02, LLM06 | Metadata signals for governance policies |

Full threat-model narrative: [`docs/threat_model.md`](threat_model.md).

## MITRE ATLAS mapping (selected techniques)

| Valo family | ATLAS technique (illustrative) |
|---|---|
| `instruction_override` | AML.T0051 LLM Prompt Injection |
| `role_confusion` | AML.T0051 LLM Prompt Injection |
| `system_prompt_extraction` | AML.T0056 LLM Meta Prompt Extraction |
| `data_exfiltration` | AML.T0057 LLM Data Leakage |
| `tool_misuse` | AML.T0058 LLM Tool Invocation |
| `indirect_injection` | AML.T0051 (indirect variant) |

Reference: https://atlas.mitre.org/

## Governance policies (community examples)

Example policies under `app/policies/governance/`:

- `warn_pii.yml` - warn when PII signals are present
- `block_secret_exposure.yml` - deny on secret keywords (advisory in monitor mode)
- `block_high_risk.yml` - deny when combined score is high

Community Edition requires `APP_ENFORCEMENT_MODE` of `monitor` or `off`.
Policies with `enforce: true` emit `would_block` annotations in monitor mode;
HTTP blocking requires Valo Enterprise with enforce mode enabled.
