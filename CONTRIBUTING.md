# Contributing

Thanks for looking. This repository is an evidence-and-gate layer for research
papers, and it holds contributors to the same rules it holds authors to.

## The three hard rules

**1. Every workflow change gets a change-log entry, in the same commit.**

```powershell
scripts/change-log.ps1 add `
    --summary "<what changed>" `
    --reason "<why>" `
    --file tools/ccfa/example.py `
    --test "tools.tests.test_example" `
    --author codex
scripts/change-log.ps1 render
scripts/change-log.ps1 check --base origin/master
```

This applies to `tools/`, `scripts/`, `app/`, `.github/`, `automation/`,
`checklists/`, `docs/` (except the change-log files), and root workflow files
such as `README.md`, `ccfa.yaml.template` and dependency locks. `check` fails
closed when a workflow file changed since the base ref is not covered. Do not
bypass it by deleting or rewriting old entries, and never write a log claiming a
test or review was completed when it was not.

**2. Inventories move with the modules they name.** Adding, renaming or removing
a `tools/ccfa/*.py` module means updating, in the same commit:

1. `CCFA_WRAPPERS` in `tools/tests/test_scripts.py`
2. `CLI_WRAPPERS` in `tools/tests/test_docs_consistency.py`
3. the `py_compile` list in `.github/workflows/tests.yml`
4. `COMMANDS` in `tools/ccfa/dispatch.py`
5. the impact map in `tools/ccfa/test_impact.py`
6. `README.md` (the tool table and a usage snippet)

A commit that lists a path before the file exists fails CI at "Compile core
modules"; one that names a deleted path fails the wrapper inventory test.

**3. Models may drive, never acquit.** If you add anything that consults a
model, the model's output must be a proposal that a deterministic check or a
human ledger then decides on. A gate that passes because a model said so is a
bug, and `readiness` has explicit contradiction checks for that case.

## Running things

```bash
# the portable path (Linux/macOS, and Windows under WSL)
PYTHONPATH=tools python -m unittest tools.tests.test_<module>

# the impacted subset for a change (what CI runs on a branch)
sh scripts/ccfa test-impact run --suite tools --base origin/master

# the full suite
PYTHONPATH=tools python -m unittest discover -s tools/tests -t .
```

Tests must not require the network. If a test needs a browser, a LaTeX engine or
a Windows shell, it should skip with a stated reason rather than fail — a skip is
a documented gap, a failure is a bug.

## Style

* Standard library first. A new dependency needs a comment in
  `tools/requirements.txt` explaining what breaks without it.
* Errors are values: return `Problem` objects and let `emit` decide the exit
  code. Exit 1 is a failed check, exit 2 is a usage or environment error.
* Never write a conclusion into a ledger that a human has not signed. Placeholder
  text is rejected on purpose.
* Comments explain *why*. "Assigns x to y" is noise.

## Pull requests

The template asks for the change-log entry, the tests you ran, and whether
anything is left pending. Small, single-purpose PRs are much easier to review
than bundled ones. If you are unsure whether something counts as a workflow
change, it does — the check will tell you.

## Reporting problems

Security issues: see [SECURITY.md](SECURITY.md). Everything else: open an issue
using the templates in `.github/ISSUE_TEMPLATE/`. If a gate produced a wrong
answer, a reproducible input is worth more than a description.
