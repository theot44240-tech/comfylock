"""`completions` - emit shell completion scripts for comfy-lock.

Pure string templates (no deps). Supports bash, zsh, fish, and PowerShell.
"""

from __future__ import annotations

SHELLS = ("bash", "zsh", "fish", "powershell")

# Kept in sync with the subcommands registered in cli.build_parser().
COMMANDS = (
    "pack",
    "verify",
    "unpack",
    "diff",
    "inspect",
    "export",
    "manager-import",
    "merge",
    "gc",
    "update",
    "sign",
    "init",
    "completions",
    "selftest",
)


def _bash() -> str:
    cmds = " ".join(COMMANDS)
    return f"""# bash completion for comfy-lock
_comfy_lock() {{
    local cur prev cmds
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    cmds="{cmds}"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$cmds --version --help" -- "$cur") )
        return 0
    fi
    COMPREPLY=( $(compgen -f -- "$cur") )
    return 0
}}
complete -F _comfy_lock comfy-lock
complete -F _comfy_lock comfylock
"""


def _zsh() -> str:
    cmds = " ".join(COMMANDS)
    return f"""#compdef comfy-lock comfylock
# zsh completion for comfy-lock
_comfy_lock() {{
    local -a cmds
    cmds=({cmds})
    if (( CURRENT == 2 )); then
        _describe 'command' cmds
    else
        _files
    fi
}}
compdef _comfy_lock comfy-lock comfylock
"""


def _fish() -> str:
    lines = ["# fish completion for comfy-lock"]
    for c in COMMANDS:
        lines.append(
            f"complete -c comfy-lock -n '__fish_use_subcommand' -a '{c}'"
        )
    lines.append("complete -c comfy-lock -l version -d 'Show version'")
    lines.append("complete -c comfy-lock -l help -d 'Show help'")
    return "\n".join(lines) + "\n"


def _powershell() -> str:
    cmds = "', '".join(COMMANDS)
    return f"""# PowerShell completion for comfy-lock
Register-ArgumentCompleter -Native -CommandName comfy-lock,comfylock -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $commands = @('{cmds}', '--version', '--help')
    $commands | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }}
}}
"""


def completion_script(shell: str) -> str:
    emitters = {
        "bash": _bash,
        "zsh": _zsh,
        "fish": _fish,
        "powershell": _powershell,
    }
    if shell not in emitters:
        raise RuntimeError(f"Unknown shell {shell!r}. Valid: {', '.join(SHELLS)}.")
    return emitters[shell]()
