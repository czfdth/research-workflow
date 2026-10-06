# research-workflow

An evidence-and-gate layer for research papers. It does not write your paper;
it makes the claims in it checkable, and it refuses to let a model acquit them.

[中文说明](README.md)

## The idea in one paragraph

Most research tooling automates *generation*: search the literature, draft the
text, run the experiment loop. This repository automates *verification*. Every
number in the manuscript is bound to the file it came from, every citation is
paired with a fetched DOI record, every figure has a byte-level manifest, and a
state machine decides whether the paper is ready. The rule that shapes
everything else: a model may drive the process, but it may never sign off on a
conclusion. Human review ledgers are checked for completeness, and a model that
tries to pass a gate whose evidence is missing is contradicted by deterministic
checks rather than believed.

## Quickstart

```bash
git clone <repo> && cd research-workflow
python -m venv tools/.venv
tools/.venv/bin/pip install -r tools/requirements.lock   # Windows: tools\.venv\Scripts\pip
```

Then one command answers "where am I":

```bash
python -m ccfa.quickstart --repo-root .        # POSIX launcher: sh scripts/ccfa quickstart
```

It prints environment health, your papers, and the single next action — with
the packet to read, the ledger to write and the criterion its checker enforces.

On Windows the same tools run through `scripts/*.ps1` wrappers; on Linux and
macOS use the wrapper-free `scripts/ccfa` dispatcher (`sh scripts/ccfa list`).

## What a paper repository looks like

`papers/<slug>/` is a separate Git repository with:

| path | what it holds |
| --- | --- |
| `ccfa.yaml` | the single source of truth: stage, gate, profile, venue |
| `manuscript/` | LaTeX; numbers are written as `\dataval{source:key}{value}` |
| `data/` | ledgers: claims, citations, proof audit, citation support, figures, statistics, governance, cost |
| `figures/` | manifest with hashes, plus a generator that reproduces each figure |
| `experiments/log/` | one JSON per run, with config, seed, commit and exit code |
| `reviews/` | cross-model review records, append-only review history |
| `submission/` | the reproducibility bundle and the submission checks |

## The gates

`readiness` runs the whole set and prints a fail-closed verdict. The ones worth
knowing about:

* **numeric traceability** — every flagged number must re-derive from its source file, and the tolerance shrinks with the precision you claim;
* **citation integrity** — ledger entries need fetched evidence (body hash, retrieval time, matched title), not a hand-written `verified`;
* **proof audit / citation support / figure support** — human ledgers, checked for completion, placeholders rejected;
* **statistics design** — alpha, power, sample size, seeds, stopping rule, missing-data policy, and a zero-skill baseline;
* **reproducibility** — container receipts with pinned digests, lockfile hashes, and a clean-environment re-run;
* **governance** — authorship, conflicts of interest, ethics and licences, AI-use disclosure, plagiarism, dual use;
* **anonymity** — double-blind leaks: author blocks, names and affiliations, self-referential phrasing, own URLs, PDF metadata;
* **integrity forensics** — a pinned launcher for the upstream detector ARIS points at, with append-only obligations that a later run can never auto-close.

## Design rules this repository holds itself to

1. **Fail closed.** A missing tool, an unreadable input or an unknown path is an error, never a silent pass.
2. **Deterministic before model.** Anything mechanically decidable is decided by code; models propose, they do not acquit.
3. **Append-only history.** Ledgers and review records are added to, not rewritten. A vanished finding is recorded as unresolved, not as fixed.
4. **Every change is logged.** A workflow change without a change-log entry fails CI.
5. **State boundaries are stated.** `schema-valid`, `evidence-present`, `gate-verified`, `independently-reviewed` and `scientifically-accepted` are separate, and the last one is `not-claimed` unless a human says otherwise.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: every change to
`tools/`, `scripts/`, `app/`, `.github/`, `automation/`, `checklists/`, `docs/`
or a root workflow file needs a change-log entry, the inventories that name
modules must move in the same commit, and tests must pass without a network.

## Status and honest limits

This is a working single-author tool, not a product. It has been exercised on
one paper, which has not yet been submitted, so its central claim — that these
gates improve research quality — is still an untested hypothesis. The gates
verify *internal consistency*: that a number matches its source, that a citation
exists and is what the ledger says, that a review was signed. They do not verify
that a theorem is true, that a citation supports the sentence it sits in, or that
a figure shows the effect the text claims. Those require people, and the
workflow is built to make that requirement visible instead of hiding it.

## Licence

MIT — see [LICENSE](LICENSE). Citation metadata is in [CITATION.cff](CITATION.cff).
