#!/usr/bin/env bash
# =====================================================================
# Make Antigravity actually read AGENTS.md.
#
# Antigravity auto-loads ~/.gemini/GEMINI.md for every conversation. It
# does NOT read AGENTS.md or CLAUDE.md out of the box, and symlinking
# GEMINI.md to them does not work reliably either. So the fix is a small
# bootstrap in GEMINI.md that tells the agent to go read the project's
# AGENTS.md first.
#
#   bash install-rules.sh
#
# Appends to GEMINI.md if it already exists — never clobbers your rules.
# =====================================================================
set -euo pipefail

GEMINI_DIR="$HOME/.gemini"
GEMINI_MD="$GEMINI_DIR/GEMINI.md"
MARKER="<!-- chakravyuh-agents-bootstrap -->"

mkdir -p "$GEMINI_DIR"

if [ -f "$GEMINI_MD" ] && grep -qF "$MARKER" "$GEMINI_MD"; then
  echo "Bootstrap already present in $GEMINI_MD — nothing to do."
  exit 0
fi

if [ -f "$GEMINI_MD" ]; then
  cp "$GEMINI_MD" "$GEMINI_MD.bak.$(date +%Y%m%d%H%M%S)"
  echo "Backed up existing GEMINI.md"
  printf '\n\n' >> "$GEMINI_MD"
fi

cat >> "$GEMINI_MD" <<'EOF'
<!-- chakravyuh-agents-bootstrap -->
## Project rules

At the start of every task, look for an `AGENTS.md` in the workspace root
and read it before doing anything else. If the task touches a subfolder
that has its own `AGENTS.md`, read that too — the nearer file wins on any
conflict.

Treat the contents as binding project rules, not suggestions. Where a rule
says something must not be done, do not do it and say why rather than
working around it.

If no `AGENTS.md` exists, carry on normally.
<!-- end chakravyuh-agents-bootstrap -->
EOF

echo "Wrote bootstrap to $GEMINI_MD"
echo
echo "Verify inside Antigravity by asking the agent:"
echo "  \"What does AGENTS.md say about mock data?\""
echo "It should quote rule 1 — never introduce mock or placeholder data."
