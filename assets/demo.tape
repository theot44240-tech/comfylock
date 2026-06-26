# VHS tape for the ComfyLock terminal demo.
# Regenerate with:  vhs assets/demo.tape   (https://github.com/charmbracelet/vhs)
Output assets/demo.gif

Set FontSize 14
Set Width 1200
Set Height 640
Set Theme "Dracula"
Set Padding 18

Type "# Pack a workflow + its ComfyUI environment into one lockfile"
Sleep 600ms
Enter
Type "comfy-lock pack my_portrait_workflow.flow.json -r ./ComfyUI"
Enter
Sleep 3s

Type "# On another machine: verify the environment matches the lock"
Sleep 600ms
Enter
Type "comfy-lock verify my_portrait_workflow.lock -r ./ComfyUI"
Enter
Sleep 2s

Type "# Are any pinned nodes stale upstream? (one git ls-remote each)"
Sleep 600ms
Enter
Type "comfy-lock sync my_portrait_workflow.lock --check-only"
Enter
Sleep 2s

Type "# Security audit -> SARIF for GitHub Code Scanning"
Sleep 600ms
Enter
Type "comfy-lock audit my_portrait_workflow.lock --format sarif > comfylock.sarif"
Enter
Sleep 2s

Type "# See exactly what changed between two workflow versions"
Sleep 600ms
Enter
Type "comfy-lock diff v1.lock v2.lock"
Enter
Sleep 2500ms
