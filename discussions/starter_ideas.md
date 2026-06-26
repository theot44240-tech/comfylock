# 💡 Ideas & Feature Requests

Have an idea for ComfyLock? This is the place. We read every one.

A good idea post answers:

- **What problem are you hitting?** (the pain, not just the proposed fix)
- **What would the ideal command/flag look like?** (sketch the UX)
- **Have you tried a workaround?** What was missing?
- **Would you be up for contributing it?** (totally optional!)

Two hard constraints to keep in mind — they're what make ComfyLock trustworthy:

1. **The core stays zero-dependency.** New features are stdlib-only, or behind an
   optional extra (`[hf]`, `[blake3]`, …).
2. **stdout stays machine-readable.** Progress and status go to stderr; exit codes
   are stable.

On the radar already (see the README roadmap): registry-backed node/model search,
lock templates, resume-able downloads, an SBOM export. Tell us what's most useful!
