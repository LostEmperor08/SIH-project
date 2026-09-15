# Running Chakravyuh SETU in Antigravity

The workspace is already assembled at `~/Documents/chakravyuh-setu` and its
tests pass there. This is the wiring.

---

## 1. Open it

Antigravity → **File → Open Folder** → `~/Documents/chakravyuh-setu`

You should see `backend/`, `aiml/`, `supabase/`, `scripts/`, `docs/`,
`frontend/`, and `AGENTS.md` at the root.

---

## 2. Make Antigravity actually read AGENTS.md

**This is the step everyone skips, and it silently does nothing if you do.**

Antigravity auto-loads `~/.gemini/GEMINI.md` for every conversation. It does
**not** read `AGENTS.md` or `CLAUDE.md` out of the box, and symlinking
`GEMINI.md` to them does not work reliably either. So a bootstrap line in
`GEMINI.md` has to point the agent at the project file.

```bash
cd ~/Documents/chakravyuh-setu
bash install-rules.sh
```

It appends a marked block to `~/.gemini/GEMINI.md` (backing up anything
already there) telling the agent to read the workspace `AGENTS.md` first.

**Verify it worked.** Restart Antigravity, then ask the agent:

> What does AGENTS.md say about mock data?

It should quote rule 1 — *never introduce mock or placeholder data*. If it
says it can't find the file, the bootstrap didn't take; check
`~/.gemini/GEMINI.md` contains the `chakravyuh-agents-bootstrap` marker.

A copy also sits at `.agent/rules/project.md` in case your Antigravity build
reads that path directly.

---

## 3. What AGENTS.md buys you

It is not documentation — it is a guardrail. It encodes the three bugs that
already bit this project, so the agent doesn't cheerfully reintroduce them:

- Blockscout's `filter=to | from` returns 422 (only `to` **or** `from`)
- Blockstream mempool txs have no `block_time` — never fall back to `now()`
- The audit hash must come from the single shared `audit_hash()` function

Plus the rules that matter for an investigation tool: never add mock data,
never weaken the nine security controls, never quote synthetic metrics as
accuracy, abstention is a valid answer.

Without it, an agent asked to "make the trace more robust" will very
plausibly add a mock fallback — which is exactly the thing your report
commits to having removed.

---

## 4. Using Claude inside Antigravity

Two ways, and they're different:

**Model picker.** Antigravity is multi-model — pick Claude in the model
selector for a conversation or an agent. Good for reasoning-heavy work:
reviewing the RLS policies, reasoning about the risk-fusion weights,
critiquing the weak-supervision label functions.

**Claude Code in the integrated terminal.** Antigravity is a VS Code fork,
so `claude` runs in its terminal like any other. This gets you the agentic
loop over the real filesystem — multi-file refactors, running the test
suites, fixing what breaks. `AGENTS.md` is worth pointing Claude Code at
too (`claude --append-system-prompt "$(cat AGENTS.md)"`, or copy it to
`CLAUDE.md`).

Rough split that works: Antigravity's Agent Manager for parallel scoped
tasks in the editor, Claude Code in the terminal for anything spanning all
three packages at once.

---

## 5. First commands

```bash
make install     # both requirements.txt files
make test        # 57 backend + 12 ML smoke + 30 parser = must all pass
make backend     # uvicorn on :8000
make aiml-train  # synthetic smoke train
```

Already verified on your machine: **57 passed** (backend), **30 passed**
(parsers).

---

## 6. Good first agent tasks

Scoped, verifiable, each ends in a test run:

1. *"Read AGENTS.md. Then add Arbitrum support end to end — schemas.py
   pattern, a provider adapter, the chain enum in 01_schema.sql, and a
   parser test. Run the test suites."*
2. *"Wire `client/skvClient.ts` into `frontend/` as a React Flow view that
   calls POST /trace and colours nodes by riskBand."*
3. *"Review `backend/app/security.py` against the nine controls in
   docs/BACKEND.md and report any gap. Change nothing yet."*
4. *"Run `python -m src.train --source elliptic` in aiml/ after I download
   Elliptic++, and write the real metrics into docs/AIML.md."*

Bad first task: *"improve the backend."* Unscoped work against a codebase
with this many invariants is how the guardrails get quietly removed.

---

## 7. Two gotchas on this machine

**Deno.** `scripts/verify-live.ts` needs it. Check with `deno --version`;
if missing: `brew install deno`. Everything else runs on Python 3 and Node,
both already present.

**Your frontend.** `frontend/` is empty — I couldn't find your React/Vite
app in Documents or Downloads. Copy it in, or open it as a second folder in
the same Antigravity workspace. `docs/LIVE_DATA.md` has the `/trace` fetch
snippet and the React Flow wiring.

---

## 8. Order of operations before the demo

This sequence matters and is easy to get backwards:

1. Apply `supabase/migrations/*.sql` **01 → 07** in the Supabase SQL editor
2. `SELECT * FROM verify_audit_chain();` → must say `chain intact`
3. Deploy the edge functions, run `sync-threat-intel` once
4. Trace real addresses so wallets land in the database
5. **Then** train the ML on that data
6. **Then** set `ML_API_URL` and confirm `/trace` returns
   `scoringMode: "ml"` rather than `"rules_only"`

Training before step 4 trains on an empty database and produces nothing.

---

## Sources

- [Google Antigravity IDE](https://antigravity.google/product/antigravity-ide/)
- [Build with Google Antigravity — Google Developers Blog](https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/)
- [Making Antigravity use AGENTS.md automatically](https://aiengineerguide.com/til/make-antigravity-use-agents-md-automatically/)
- [AGENTS.md guide for Antigravity](https://agentpedia.codes/blog/antigravity-agents-md-guide)
- [Antigravity rules guide](https://agentpedia.codes/blog/user-rules)
