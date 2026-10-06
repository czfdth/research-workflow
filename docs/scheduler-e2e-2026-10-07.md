# Slurm 提交路径的端到端实测（2026-10-07）

## 一句话

`ccfa compute run --backend <slurm>` 从"只探测、拒绝提交"改成了真的走
`sbatch --parsable` → 轮询 → 收退出的路径；这条路径今天在一台真实 sshd 上跑通了
两次（正常完成 + 预算击杀），回执进了 `experiments/log/compute-ledger.jsonl`。

## 这次跑的是什么

```powershell
$env:CCFA_SLURM_E2E = "1"
$env:CCFA_APK_MIRROR = "mirrors.aliyun.com"
tools/.venv/Scripts/python.exe -m unittest tools.tests.test_compute_slurm_e2e -v
```

环境：Docker 29.8.1（daemon 可达）、Windows 11 上的 OpenSSH 客户端、
镜像 `ccfa-slurm-e2e:test`（基于 `alpine:3.20`）。构建镜像时 apk 走
`mirrors.aliyun.com`：默认的 `dl-cdn.alpinelinux.org` 在本机网络下不可达，
这也是本机首次构建卡住十几分钟的原因。

harness 在 `tools/tests/fixtures/slurm-e2e/`：镜像里跑一个真的 `sshd`，并把
`sbatch` / `squeue` / `scancel` 换成 shell 脚本。这些脚本**不是 Slurm 实现**，
它们只负责用真实协议形状回答客户端。

## 实测结果（两条回执）

正常路径（`--minutes 2 -- sh -c "echo hello-from-slurm"`）：

```json
{"command": "sh -c echo hello-from-slurm", "backend": "slurm:root@127.0.0.1",
 "budget_minutes": 2.0, "wall_seconds": 0.12, "gpu_minutes": 0.0,
 "returncode": 0, "timed_out": false, "recorded_at": "2026-10-06T16:44:09Z",
 "scheduler": {"job_id": "1000", "job_dir": "$HOME/ccfa-jobs/ccfa-20261006T164408Z",
 "job_name": "ccfa-20261006T164408Z", "state": "completed", "polls": 0,
 "poll_seconds": 5.0, "stdout_tail": "hello-from-slurm"}}
```

预算击杀（`--minutes 0.1 -- sleep 120`）：

```json
{"command": "sleep 120", "backend": "slurm:root@127.0.0.1",
 "budget_minutes": 0.1, "wall_seconds": 10.76, "gpu_minutes": 0.0,
 "returncode": -1, "timed_out": true, "recorded_at": "2026-10-06T16:44:20Z",
 "scheduler": {"job_id": "1001", "job_dir": "$HOME/ccfa-jobs/ccfa-20261006T164409Z",
 "job_name": "ccfa-20261006T164409Z", "state": "cancelled", "polls": 2,
 "poll_seconds": 5.0, "stdout_tail": ""}}
```

（`Ran 2 tests in 21.331s — OK`）

## 这次证明了什么

1. 作业脚本在本地生成、base64 上传、`chmod +x`，全程只有 ssh 一条通道；
2. `sbatch --parsable` 的 job id 被解析并写进 ledger（`scheduler.job_id`）；
3. 轮询同时看退出码文件与 `squeue`，作业结束时正确收尾（`state=completed`）；
4. 预算到期会真的 `scancel`，并把 `timed_out=true`、`returncode=-1` 记进 ledger；
5. `--partition` / `--gres=gpu:N` / `workdir` 进入了作业脚本与提交命令；
6. 这条路径产出的 `wall_seconds` / `gpu_minutes` 正是 `ccfa.cost_metrics`
   用来算 `cost_per_attempt` 的输入——成本指标不再悬空。

## 这次没有证明什么

- **没有在真实集群上跑过。** 队列策略、qos、`--gres` 的真实语义、节点故障、
  `sacct` 行为、限额与计费口径都不在覆盖范围内。脚本化调度器只能证明客户端协议、
  传输、轮询与记账是对的。
- **PBS/Torque 仍未实现**：`kind: pbs` 依旧只能 `probe`，`compute run` 会明确拒绝。
- **队列（`ccfa.queue`）不接调度器后端**：队列自带的 stall 看门狗、波次 gate 与
  预算语义都是按"一条 ssh 一个 item"写的，所以它会拒绝 slurm 后端并指向
  `ccfa compute run --backend`。这条限制是故意保留的，不是遗漏。
- **远端 GPU 计量**：本文记录那次运行时确实还没实现（`gpu_budget_s` 对远程后端
  报错拒绝）；同日晚些已补上并在同一个 harness 上实测，见文末「追加」。

## 复现方式

```powershell
$env:CCFA_SLURM_E2E = "1"
tools/.venv/Scripts/python.exe -m unittest tools.tests.test_compute_slurm_e2e -v
```

默认按 `dl-cdn.alpinelinux.org` 构建；网络受限时用
`CCFA_APK_MIRROR=mirrors.aliyun.com`（或任何可达的 Alpine 镜像）。

## 追加：远端 GPU 计量实测（同日晚些）

`gpu_budget_s` 以前对远程后端直接报错拒绝。现在队列的 GPU 计量器改在**对端**采样：
每 5 秒经 ssh 跑一次 `nvidia-smi --query-gpu=utilization.gpu`，忙碌秒数累加进
run-log 的 `resource_usage.gpu_seconds`；对端没有 `nvidia-smi` 时在开跑前就报
工具错误（fail closed），不会拿本机读数冒充。

同一个 harness 里加了脚本化 `nvidia-smi`（恒返回 100%），实测：

```text
test_a_slurm_job_round_trips_and_lands_in_the_ledger ... ok
test_the_budget_kill_cancels_the_job_and_records_the_timeout ... ok
test_the_queue_meters_remote_gpu_seconds_and_stops_on_budget ... ok

Ran 3 tests in 29.862s — OK
```

第三条断言的内容：队列对 `kind: ssh` 后端下发两项，第一项 `sleep 8`，GPU 预算
0.5 秒；被测得的 `gpu_seconds > 0` 且 `gpu_samples >= 1`，第二项状态为
`skipped-gpu-budget`、队列 `stopped = "gpu-budget"`。

仍未验证：多卡/多进程 GPU 归属（当前按"任意一张卡忙就算忙"取最大值）、
`nvidia-smi` 不可用时的重试语义、以及真实集群上的 MIG/独占策略。
