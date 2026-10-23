#!/usr/bin/env bash
# Install the harness into a target project.
#
# Usage: ./install.sh <target-project-dir> [--force]
#
# Copies hooks, agents, commands, skills, rules, tools/env_inspect.py and .codex/hooks.json.
# Existing files are kept unless --force is given. An existing settings.json is
# never overwritten: the harness version is written next to it as
# settings.harness.json so the permissions and hooks can be merged by hand.
set -euo pipefail

usage() {
  echo "Usage: $0 <target-project-dir> [--force]" >&2
  exit 1
}

[ $# -ge 1 ] || usage
target=$1
force=${2:-}
[ -z "$force" ] || [ "$force" = "--force" ] || usage
[ -d "$target" ] || { echo "Target '$target' is not a directory." >&2; exit 1; }

src=$(cd "$(dirname "$0")" && pwd)
copied=0
skipped=0

copy() {
  local from=$1 to=$2
  if [ -e "$to" ] && [ "$force" != "--force" ]; then
    echo "  skip   ${to#"$target"/} (exists)"
    skipped=$((skipped + 1))
    return
  fi
  mkdir -p "$(dirname "$to")"
  cp "$from" "$to"
  echo "  write  ${to#"$target"/}"
  copied=$((copied + 1))
}

echo "Installing claude-code-harness into $target"

while IFS= read -r -d '' file; do
  rel=${file#"$src"/}
  [ "$rel" = ".claude/settings.json" ] && continue
  copy "$file" "$target/$rel"
done < <(find "$src/.claude" -type f -not -name '*.pyc' -not -path '*/__pycache__/*' -print0)

copy "$src/tools/env_inspect.py" "$target/tools/env_inspect.py"
chmod +x "$target"/.claude/hooks/*.py "$target/tools/env_inspect.py" 2>/dev/null || true

if [ -e "$target/.claude/settings.json" ] && cmp -s "$src/.claude/settings.json" "$target/.claude/settings.json"; then
  echo "  skip   .claude/settings.json (already up to date)"
elif [ -e "$target/.claude/settings.json" ]; then
  cp "$src/.claude/settings.json" "$target/.claude/settings.harness.json"
  echo "  note   .claude/settings.json exists; merge .claude/settings.harness.json into it"
else
  copy "$src/.claude/settings.json" "$target/.claude/settings.json"
fi

# Codex reads the same guards through .codex/hooks.json (it must be trusted with /hooks).
copy "$src/.codex/hooks.json" "$target/.codex/hooks.json"

[ -e "$target/CLAUDE.md" ] || copy "$src/templates/CLAUDE.md" "$target/CLAUDE.md"
copy "$src/templates/prd-template.md" "$target/templates/prd-template.md"

echo "Done: $copied written, $skipped skipped."
