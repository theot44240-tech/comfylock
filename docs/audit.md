# Security advisory scanning (`comfy-lock audit`)

`audit` checks every pinned **GitHub** custom node against GitHub's public
[Security Advisories](https://docs.github.com/en/rest/security-advisories)
REST API. No token is required for public repositories.

```bash
comfy-lock audit my_workflow.lock
```

Example output:

```
ok  ltdrdata/ComfyUI-Impact-Pack: no advisories
XX  acme/some-node: 1 advisory(ies)
      [critical] GHSA-aaaa-bbbb-cccc CVE-2024-9999 Arbitrary code execution in loader
      https://github.com/acme/some-node/security/advisories/GHSA-aaaa-bbbb-cccc

audit: 1 advisory(ies) across 2 node(s).
```

## Flags

| Flag | Effect |
|------|--------|
| `--fail-on-advisory` | Exit code `1` if any advisory is found (use this in CI). |
| `--no-cache` | Bypass the 1-hour cache and always query the API. |
| `--json` | Emit the uniform JSON envelope instead of text. |

## Behaviour

- **Only GitHub nodes are queried.** Non-GitHub nodes (GitLab, self-hosted, …)
  are listed as *skipped*.
- **Failures are non-fatal.** A network error, an unreachable host, or a rate
  limit (HTTP 403/429) degrades to a warning — the scan never crashes.
- **Caching.** Raw advisory payloads are cached for one hour in
  `.comfylock-audit-cache.json` so repeated CI runs do not hammer the API.

## CI gate

```yaml
- name: Audit pinned nodes for advisories
  run: comfy-lock audit workflow.lock --fail-on-advisory
```

Pair it with `verify` for a complete reproducibility + security gate.
