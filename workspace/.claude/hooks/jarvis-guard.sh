#!/bin/bash
# jarvis-guard: blocks destructive / risky Bash commands for Jarvis's inner Claude.
# Exit 2 = block the tool call (stderr is shown to the model as the reason).
input=$(cat)
cmd=$(echo "$input" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
[ -z "$cmd" ] && exit 0

block() {
  echo "BLOCKED by jarvis-guard: $1. This command is forbidden for Jarvis — tell the user instead of working around it." >&2
  exit 2
}

shopt -s nocasematch

# filesystem destruction
[[ "$cmd" =~ rm[[:space:]]+(-[a-z]*[rf][a-z]*[[:space:]]+)+ ]] && block "recursive/forced rm"
[[ "$cmd" =~ (mkfs|diskutil[[:space:]]+erase|dd[[:space:]]+if=) ]] && block "disk destruction"
[[ "$cmd" =~ \>[[:space:]]*/dev/ ]] && block "writing to device files"
[[ "$cmd" =~ (^|[[:space:];&|])sudo[[:space:]] ]] && block "sudo"

# git history / remote destruction
[[ "$cmd" =~ git[[:space:]]+push.*(--force|-f[[:space:]]|--delete) ]] && block "force/delete push"
[[ "$cmd" =~ git[[:space:]]+reset[[:space:]]+--hard ]] && block "hard reset"
[[ "$cmd" =~ git[[:space:]]+clean[[:space:]]+-[a-z]*f ]] && block "git clean -f"

# databases / production data
[[ "$cmd" =~ (DROP[[:space:]]+(TABLE|DATABASE|SCHEMA)|TRUNCATE[[:space:]]|DELETE[[:space:]]+FROM|FLUSHALL|FLUSHDB|dropDatabase) ]] && block "destructive database operation"
[[ "$cmd" =~ (migrate:fresh|migrate:reset|db:wipe) ]] && block "database wipe migration"

# anything that smells like production
[[ "$cmd" =~ (prod|production)[^a-z] && "$cmd" =~ (deploy|delete|drop|terminate|destroy|scale|restart) ]] && block "production-touching command"

# remote code execution / system control
[[ "$cmd" =~ (curl|wget).*\|[[:space:]]*(ba)?sh ]] && block "piping downloads to shell"
[[ "$cmd" =~ (^|[[:space:];&|])(shutdown|reboot|halt)([[:space:]]|$) ]] && block "system power command"
[[ "$cmd" =~ killall[[:space:]] ]] && block "killall"
[[ "$cmd" =~ launchctl[[:space:]]+(unload|remove|bootout) ]] && block "launchctl removal"

# credentials
[[ "$cmd" =~ (\.env|credentials|id_rsa|\.ssh/)[^a-z]*([[:space:]]|$) && "$cmd" =~ (cat|cp|curl|open|mail|base64) ]] && block "reading/exfiltrating credentials"

exit 0
