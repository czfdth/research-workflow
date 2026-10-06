# Scripted Slurm harness

This directory exists for one reason: `ccfa.compute` submits Slurm jobs
through `sbatch`, polls `squeue` and collects an exit-code file, and that path
has to be exercised against *something* before anyone claims it works. No real
cluster was available, so this image runs a real `sshd` on a real port and
answers the scheduler commands with the scripts in `bin/`.

What a green run proves:

* the job script is built, uploaded over SSH and submitted with
  `sbatch --parsable`;
* the poll loop reads the exit-code file, consults `squeue`, and stops;
* the budget kill runs `scancel` and records `timed_out: true`;
* `experiments/log/compute-ledger.jsonl` receives the job id, state and wall
  clock, so `ccfa.cost_metrics` can price the attempt.

What it does not prove: anything about a real Slurm installation. Queue
policy, `--gres`, partitions, node failures and `sacct` behaviour are out of
scope — those need a real cluster, and the report in
`docs/scheduler-e2e-2026-10-07.md` says so.

Run it with:

```powershell
$env:CCFA_SLURM_E2E = "1"
tools/.venv/Scripts/python.exe -m unittest tools.tests.test_compute_slurm_e2e -v
```
