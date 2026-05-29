# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `v0.1.x` | Yes |

## Reporting a vulnerability

Report security vulnerabilities via **Security → Report a vulnerability** on the
GitHub repository, or through the contact channel listed in the repository profile.

Please do not disclose exploitable issues in public issues before a fix is available.

Include:

- Affected component (API, web UI, proxy, policies)
- Steps to reproduce
- Impact assessment

Maintainers aim to acknowledge reports within five business days.

## Secure deployment

Community Edition is designed for **monitor** or **off** enforcement. Keep
`APP_ENFORCEMENT_MODE` at `monitor` (the default in `docker-compose.yml`) unless
you intentionally disable policy instrumentation.

Do not commit `.env` files, API keys, or production data under `data/` to version control.
