# 长任务安全 v1 实施计划（P1：可中断、可观察、有停止条件）

**Goal:** 关闭审计 P1-5：`queue` 目前只有墙钟预算与显式重试，没有并发上限、GPU 预算、卡死检测与受控运行策略。v1 面向本机单卡、人工启动的 ML 实验队列，先把可验证的停止条件做实；不把策略层伪装成 OS 级沙箱。

**裁定：**

- **E64 并发上限 = 1，按 log 目录加 OS 文件锁。** 同一 `--log-dir` 同时只允许一个队列实例；Windows 用 `msvcrt.locking`，POSIX 用 `fcntl.flock`。进程死亡由 OS 自动释放，不做易竞态的陈旧 PID 回收。第二条队列退 2，不排队、不静默并行。
- **E65 GPU 预算按 `nvidia-smi` 利用率采样。** `--gpu-budget-seconds` 或清单 `gpu_budget_s` 生效；默认每 1 秒采样一次，利用率 ≥ 5% 的墙钟时间计入 GPU 秒数。预算耗尽后当前 attempt 留档，后续项记 `skipped-gpu-budget`，整体退 1。`nvidia-smi` 不可用且确实要 GPU 预算时退 2，不静默忽略。
- **E66 看门狗按“无输出”判断卡死，不按总时长猜测。** `stall_timeout_s` 内子进程 stdout/stderr 都没有新行则 kill，记 `stalled`；是否重试由 `retry_on_stall` 显式声明。总时长仍由现有 `timeout_s` 管。
- **E67 沙箱 v1 = 进程策略沙箱，不是 OS 隔离。** `sandbox: policy` 只做三件事：`cwd` 必须解析到队列根内、默认环境只保留白名单变量、子进程由默认 runner 管理生命周期。它不限制文件系统写、网络或 GPU 可见性；需要这些隔离时必须另接 Docker/WSL/专用沙箱。help 与报告必须写明边界。

**Files:** Modify `tools/ccfa/queue.py`、`tools/tests/test_queue.py`、`docs/design/2026-10-03-research-workflow-design.md`、`docs/sdd/2026-10-03-evidence-tracking-progress.md`。

### Task 1: 独占锁与停止条件字段

- 清单新增可选 `stall_timeout_s`、`retry_on_stall`、`gpu_budget_s`、`sandbox`（`none|policy`）。
- `run_queue` 在开始时获取 `log_dir/.queue.lock` 的 OS 锁；正常/异常退出都释放。
- 判别力：锁被持有时第二次调用退 2；进程退出后锁自动可重获；残留元数据不阻塞下一次获取。

### Task 2: GPU 预算

- `GpuMeter` 默认调用 `nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits`，采样线程累计 busy 秒数。
- `run_queue` 每次 attempt 后把 `gpu_seconds`/`gpu_samples` 写进独立 `resource_usage` 字段，不写 `metrics`；累计超预算后停止并标记后续项。成功但未记实验指标的 run 仍会被 `run-log-metrics-pending` 报出。
- 测试注入 fake meter；真实冒烟只验证 `nvidia-smi` 读取路径不崩且记录非负秒数。

### Task 3: 卡死看门狗

- 默认 runner 维护 last-output 时间；超过 `stall_timeout_s` 无输出则 kill 并抛 `QueueStalled`。
- `run_queue` 把 `stalled` attempt 留档；`retry_on_stall` 为真才重试。
- 判别力：真实子进程先输出后 sleep → 看门狗在 stall 阈值附近 kill；无 `stall_timeout_s` 时不触发。

### Task 4: 策略沙箱

- `sandbox: policy`：`cwd` 越出 queue root → `ValueError`；默认 runner 用 `_sandbox_env()` 白名单环境；注入 runner 不能宣称 policy，直接退 2。
- 边界写进 docstring/help：不承诺只读数据、不承诺禁网、不承诺 GPU 隔离。
- 判别力：`..` 逃逸与绝对外部路径均被拒；白名单外变量不传给子进程。

## 完成定义

- `queue` 有并发锁、GPU 预算、卡死看门狗、策略沙箱四类停止/约束，并全部有判别性测试。
- 所有 attempt 仍先写 `running` 再写终态；失败、超时、卡死都不被静默重试掉。
- 全量 tools/app 全绿；真实 `nvidia-smi` 与真实子进程冒烟留档。
- 文档明确 v1 沙箱边界，不使用“OS 沙箱/容器隔离”措辞。
