# Reference Drift Review

Date: 2026-11-18

Method: for every registry entry that `reference-audit check --strict` flagged as
stale, compare the pinned commit with the repository's current default-branch
HEAD through the GitHub compare API, then check the current tree for the
artifacts our audit document relies on. This is a drift review of the claims we
actually made, not a claim that every upstream change has been read or copied
locally.

## Imbad0202/academic-research-skills

- Previous pin: `6ab4b03bf70a118a1b3ee7f3263ed9f19031061b`
- New pin: `c70feb7ab43265b31988c3ab38e8731d3bca0784`
- Changed: 70 commits, 225 files.
- Material changes: the passport ledger now allows an experiment to state that
  it has no honest lock values and aligns its repro-lock documentation, example,
  gate and validators with each other; the Zotero adapter rejects malformed DOI
  format before it reaches the passport; citation compliance work tightened
  output naming, non-APA auto-correction behaviour and pattern performance; the
  write-scope fence gained coverage for plugin-scoped agent types and foreign
  timeout binaries, with follow-up docs clarifying its actual boundary.
- Current tree still contains the passport, ledger, citation compliance and
  risk-register artifacts referenced by the audit document.

Decision: these are refinements in the same direction as our fail-closed rules.
Nothing here lets an unverified record be accepted, so no local gate changes.
In particular, a write-scope fence is a boundary statement, not permission to
write from a read-only MCP surface; our MCP contract stays read-only.

## aipoch/open-science

- Previous pin: `bd9a61a80a73df317573b15ce1a32f1d007cba9b`
- New pin: `28dcea7229efea8e9768c1edabf8fc40fcd25ba8`
- Changed: 855 commits (compare API caps the file list at 300).
- Material changes: the CLI now exposes both read-only and *write* literature
  tools over MCP; replay gained step-anchored questioning and clearer delayed
  actions; notebook evidence logging added a lane-private dual-write path;
  session inspection and diagnostic replay are bounded.
- Current tree still contains replay, immutable-input authority, provenance and
  literature artifacts. The GUI-level execution graph named as an unimplemented
  item in the audit document is still listed as future work, not silently
  marked done.

Decision: the MCP write tools are an explicit design divergence. This project
keeps its MCP surface read-only and does not expose any tool that can clear a
gate or mutate an evidence ledger, so upstream's write capability is recorded
but not imported. Replay and evidence-log refinements affect the upstream GUI,
not our CLI verification path.

## wanshuiyin/Auto-claude-code-research-in-sleep (ARIS)

- Previous pin: `3b19a22dc5a64c983d2eafd6c2c94000fadc4f8d`
- New pin: `9f30e834d24a337dbdd06fb20a1150d4376dfa59`
- Changed: 104 commits, 228 files.
- Material changes: a bounded read-only fan-out contract with a leaf agent and
  ownership tracking; a new `citation-crosscheck` skill for double-blind
  bib-vs-web field auditing, where invalid citation flags now fail closed and
  ambiguous surname coverage is rejected; reviewer-gate traces now preserve
  reported-model provenance and cwd; an opt-in Lean proof workflow appeared.
- Current tree still contains the proof, resubmit/talk, review-loop and
  citation-crosscheck skills that the audit document relies on.

Decision: the two changes closest to our gates are provenance preservation and
fail-closed citation flags. Our `cross_review.py` already recomputes the review
tier from model/provider and rejects a mismatch rather than trusting a stored
label, and `citation_guard.py` already blocks invalid or unbound evidence. No
gate weakening is warranted; bounded fan-out is outside this CLI's read-only
surface.

## Boundary

Updating a pin means "this upstream snapshot was read and classified against
our documented claims", not "all upstream behaviour is now implemented here".
The scheduled audit is intentionally fail-closed: it will fail again whenever
one of these repositories publishes a new default-branch commit, and a human
must repeat this classification before re-pinning.
