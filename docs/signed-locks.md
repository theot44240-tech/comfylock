# Signed locks

A `.lock` is untrusted input — anyone can hand you one. Signing lets a recipient
confirm a lock came from you and was not modified in transit.

## Sign (GPG, default)

```bash
comfy-lock sign my_workflow.lock                 # uses your default GPG key
comfy-lock sign my_workflow.lock --key you@example.com
```

This writes an ASCII-armored detached signature `my_workflow.lock.asc` next to
the lock. Distribute both files together.

## Verify

```bash
comfy-lock verify my_workflow.lock --check-sig -r ~/ComfyUI
```

`--check-sig` verifies `my_workflow.lock.asc` **before** any other check. If the
signature is missing or invalid, `verify` exits with code 2 and touches nothing
else — so an unsigned or tampered lock never reaches `unpack`.

## Sigstore (keyless, CI)

`comfy-lock sign --sigstore` uses keyless signing via the optional `[sigstore]`
extra (`pip install "comfylock[sigstore]"`) and an OIDC identity — ideal for
GitHub Actions, where the workflow's OIDC token signs without managing a private
key. Without the extra, ComfyLock explains how to enable it and falls back to
GPG.

## Threat model

Signing protects **authenticity and integrity in transit**. It does not vouch for
the *contents* a lock points at — always combine signatures with the strong-hash
integrity gate (see [security.md](security.md)).
