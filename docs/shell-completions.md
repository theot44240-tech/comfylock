# Shell completions

`comfy-lock completions --shell <bash|zsh|fish|powershell>` prints a completion
script to stdout. Install it for your shell:

## bash

```bash
comfy-lock completions --shell bash | sudo tee /etc/bash_completion.d/comfy-lock
# or, user-local:
comfy-lock completions --shell bash >> ~/.bash_completion
```

## zsh

```bash
comfy-lock completions --shell zsh > "${fpath[1]}/_comfy-lock"
# then restart your shell (ensure compinit runs)
```

## fish

```bash
comfy-lock completions --shell fish > ~/.config/fish/completions/comfy-lock.fish
```

## PowerShell

```powershell
comfy-lock completions --shell powershell | Out-String | Invoke-Expression
# to persist, append it to your $PROFILE:
comfy-lock completions --shell powershell >> $PROFILE
```

Completions cover the subcommands (`pack`, `verify`, `unpack`, `inspect`,
`export`, …) and fall back to file completion for path arguments.
