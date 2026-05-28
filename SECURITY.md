# Security policy

## Supported versions

| Edition | Supported |
|---------|-----------|
| Community `v0.1.x` | Yes |
| Enterprise (private) | Per agreement |

## Reporting a vulnerability

Please report security issues privately to the repository maintainers.
Do not open public issues for undisclosed vulnerabilities.

Include:

- Affected component (API, web UI, proxy, policies)
- Steps to reproduce
- Impact assessment

We aim to acknowledge reports within 5 business days.

## Community edition scope

Community edition does not ship enforce-mode blocking, portfolio rollups,
or enterprise connectors. Run `APP_EDITION=community` and keep
`APP_ENFORCEMENT_MODE` at `monitor` or `off` for the intended OSS posture.
