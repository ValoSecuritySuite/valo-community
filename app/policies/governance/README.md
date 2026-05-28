# Governance policy examples

These YAML files ship with Valo Community Edition as **examples**.

- Policies evaluate pipeline context (scores, signals, matched rules).
- `then.decision` is `allow`, `warn`, or `deny`.
- `enforce: true` only blocks HTTP traffic when `APP_ENFORCEMENT_MODE=enforce`
  (enterprise edition). Community edition runs in **monitor** mode: denials are
  advisory in response headers and logs.

Customize policies for your environment; reload via `POST /policies/reload`.
