# 科研工作流缺口与完善清单

日期：2026-10-05（第八轮最终复检）

## 一句话结论

工程侧已经完成收尾，旗舰论文的新证据体系也已经落地：主仓库停在
`0d12c96`，论文仓库停在 `bd3acd8`，两者都与 `origin/master` 同步。最新
`readiness` 的 `missing_required` 为 **0**。当前 `ready=false` 只来自不能由
脚本替代的人工科研边界：证明、引用语义、图表语义复核，以及同族
cross-review 不得开释。

现在的正确动作是冻结新增工具，把人工验证真正做完，而不是继续增加 gate。

## 一、最终工程基线

| 检查 | 结果 |
| --- | --- |
| 主仓库 | `0d12c96`，与 `origin/master` 同步 |
| 论文仓库 | `bd3acd8`，与 `origin/master` 同步，工作树干净 |
| `tools/ccfa` 模块 | 68 个 |
| PowerShell 入口 | 50 个 |
| 测试方法 | 1,528 个 |
| readiness 快照 | 基于 clean commit `2e32fc0`，归档在 `bd3acd8` |
| `missing_required` | 0 |
| 远端跨仓库 CI | `paper-check #6` 已成功；主仓库定向测试已成功 |

本轮遵循“只测新增和修改”的约束，没有为了文档收尾重跑全量测试。历史全量
记录曾达到 1,441 项通过；当前测试方法数量为 1,528，新增模块各自带有定向测试。

## 二、旗舰论文迁移状态

论文已经把 10 类新台账全部迁入 `data/`：

```text
claim-registry, assumptions-limitations, venue-checklist,
artifact-provenance, exploration-graph, cost-ledger,
risk-register, experiment-loop, rigor-rubric, proof-campaign
```

最新 committed readiness 显示：

- `missing_required: 0`
- `schema-valid: pass`
- `experiment-loop: pass`
- `proof-orchestrator: pass`
- `research-ledgers: pass`
- `novelty: pass`
- `statistics: pass`
- `repro-environment: pass`
- `latex-structure: pass`
- `trace-claims: pass`
- `citation-guard: pass`
- `final-check: pass`，`problem_count=0`，保留 85 条 `untagged-number`
  advisory
- `repro-package: pass`，保留 2 条范围 advisory：未做容器级隔离；已记录输出
  尾部摘要

迁移后的论文仓库也带有可供真人填写的复核包：

```text
ccfa-workfiles/human-review/proof-review-packet.md
ccfa-workfiles/human-review/citation-support-packet.md
ccfa-workfiles/human-review/figure-support-packet.md
ccfa-workfiles/human-review/governance-checklist.md
```

这些是待人工执行的复核材料，不是已完成的复核结论。

## 三、唯一剩余的阻塞

| Gate | 结果 | 含义 |
| --- | --- | --- |
| `argument-audit` | `problem_count=15` | 8 条 proof pending、6 条 citation support missing、1 条 figure support missing |
| `cross-review` | `problem_count=1` | 同族评审只能驱动，不能开释 |
| readiness | `ready=false` | 工程证据已齐，人工科研证据未齐 |
| scientific acceptance | `not-claimed` | 脚本不能证明结论正确 |

对应的真实人工任务：

1. 逐条完成 8 个 proof 的人工复核，并写入 reviewer、日期和结论。
2. 完成 6 条 citation semantic support 记录，确认引用确实支撑对应论断。
3. 完成 1 张交付图的人工语义支持记录。
4. 完成真人盲法第二编码，报告 exact agreement、Cohen's kappa、bootstrap
   置信区间、分歧条目和裁决过程。
5. 接入不同 family 的 provider，重新生成真正跨族 cross-review，而不是沿用
   same-family override。

在这些动作完成前，系统必须继续显示 `ready=false`。这是正确行为，不是 bug。

## 四、本轮真正的收尾修正

1. 论文台账迁移状态与 `readiness` 重新对齐，文档不再声称论文未迁移。
2. 明确保留 85 条 `untagged-number` advisory，不用“全部已绑定”掩盖未标记
   数字。
3. 明确 `cross-review` 的同族限制，保留阻塞，不用模型自述替代独立评审。
4. 根目录的命令捕获文件纳入 `.gitignore`，避免它们污染工作树；文件本身不
   删除，正式证据仍应落到 `reviews/` 或论文仓库的 `ccfa-workfiles/`。
5. 两个仓库的跨仓库 CI 凭据、`run_log` 参数顺序、脏树豁免和日期边界测试均
   已修正并留下可审计记录。

## 五、后续纪律

### 冻结功能增长

在旗舰论文完成人工验证前，不再新增 gate 或抽象模块。新想法先进入
`docs/plans/`，不直接落代码。

### 每个 gate 必须回答四个问题

1. 它防止了什么真实事故？
2. 谁负责填写和更新？
3. 输入变化后如何判定 stale？
4. 如果删除它，会丢失什么证据？

### 区分四种状态

```text
schema-valid
evidence-present
independently-reviewed
scientifically-accepted
```

只有第四种才代表结论已经被外部人类科学审查接受。前三者都不能替代它。

## 六、结论

这套工作流的工程能力已经足够强：状态可恢复、失败留档、跨仓库 CI、复现包、
不可变证据、源码级对标和诚实的 blocker 都已具备。

真正决定论文质量的最后一段仍然必须由人完成：复核证明、确认引用支撑、
检查图表语义、做独立双编码，并使用真实跨族评审。完成这些之后，论文才应该
从 `internal-review` 进入 `review_cleared`。
