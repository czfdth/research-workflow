# 科研工作流缺口与完善清单

日期：2026-10-05（第八轮复检：论文迁移完成）

## 一句话结论

这一轮发生了两件关键的事：**旗舰论文真正迁移到新证据体系**（readiness 阻塞从 13 项降到 2 项），以及 **CI 重新设计为“工程检查必须通过、人工 gate 只做信息报告”**。工具层与论文层之间那条越拉越大的剪刀差开始收窄。

剩下的阻塞已经纯粹是人工科研验证与真实跨族评审，不再有任何代码或迁移工作。

## 一、本轮验证基线

| 检查 | 结果 |
| --- | --- |
| 主仓库 / 论文仓库 | 均干净，与 `origin/master` 同步 |
| 工具全量测试 | `Ran 1446 tests, OK`（上轮 1441） |
| app 全量测试 | `Ran 187 tests, OK` |
| `doctor` | 0 problems，1 advisory |
| `readiness` | `ready=false`，阻塞仅剩 2 类 |

## 二、旗舰论文迁移完成

`papers/rag-attack-defense/data/` 已经补入 10 个新台账：

```text
claim-registry.yaml            7698 B
assumptions-limitations.yaml   4522 B
venue-checklist.yaml           1802 B
artifact-provenance.yaml       2535 B
exploration-graph.yaml         2025 B
cost-ledger.yaml                888 B
risk-register.yaml             3731 B
experiment-loop.yaml            460 B
rigor-rubric.yaml              2301 B
proof-campaign.yaml            6984 B
```

仍未创建的两个：

```text
artifact-badge.yaml        （需要第三方 evaluated / reusable 证据）
scientific-acceptance.yaml （需要外部人类接受）
```

readiness 的阻塞从上一轮的 13 项降到 2 项：

```text
argument-audit gate failed: proof-review-not-verified ×5
cross-review gate failed: review-provider-config-drift, review-blocking
```

这正是应有的结果：剩下的都是“必须由人或外部完成”的事。

## 三、CI 重新设计

`paper-check.yml` 现在拆成两个 job：

| Job | 内容 | 是否阻塞 |
| --- | --- | --- |
| `deterministic-paper-checks` | validate、citation_guard、trace_claims、novelty、stats_plan、repro_env、latex_check、final_check、run_log | 阻塞 |
| `readiness-and-human-review` | readiness、governance、argument_audit、cross-review | `continue-on-error: true`，只上传 artifact |

这是一个合理的设计：CI 绿灯表示**工程侧健康**，不再因为人工复核未完成而长期红灯；人工与科学 gate 单独跟踪。

### 由此产生的一个残余风险

informational job 永远不会让 CI 失败。加上 `standard` profile 不要求 `governance`，目前 **COI、查重工具、披露联系人这三条 placeholder 不再被任何自动检查阻断**：

```text
ccfa.governance -> problem_count = 3, exit 1
但 CI 中该步骤 continue-on-error
且 readiness standard profile 不包含 governance
```

**已修复：** 论文仓库增加了 fail-closed 的
`.github/workflows/submission-gate.yml`，在 `v*` tag 或手动触发时强制运行
high-assurance readiness、governance、argument-audit、
`--strict-cross-family` cross-review 和复现包验证。该 workflow 不使用
`continue-on-error`，任一 gate 失败都会阻止发布流程。

## 四、环境状态（明显改善）

| 服务 | 本轮状态 | 变化 |
| --- | --- | --- |
| provider | `functional`，配置模型可用 | 稳定 |
| Docker daemon | **可达** | 上轮不可达，本轮恢复 |
| WorkBuddy converter | **依赖已移除** | doctor / README / workflow-guide 中已无引用 |
| Zotero `:23119` | 不可达 | 本轮回退（上轮为可连接未认证） |

`doctor` 现在只剩 1 条 advisory，环境侧基本健康。

## 五、仍然阻塞的事项（全部非代码）

### 1. 人工证明复核（8 条）

`data/proof-audit.yaml` 仍是 `pending-human-review`，8 条 review 的 reviewer 都是 `Human reviewer pending`，文件自己注明 “must not be treated as verified”。这是当前第一阻塞。

### 2. 引用与图表语义支持

`citation-support.yaml` 的 `supports: []`、`figure-support.yaml` 的 `figures: []` 仍为空。

### 3. 真人双编码

`human-coding-report.json` 仍是 `pending-human-dual-coding`，需要 blind second coding + kappa + 置信区间。

### 4. governance 占位值

COI、查重工具、披露联系人仍是 placeholder。gate 能正确识别，但目前不在阻塞路径上。

### 5. 真实跨族评审

`cross-review` 报 `review-provider-config-drift` 与 `review-blocking`。真实跨族仍需要一个不同 family 的 provider。

### 6. 外部证据

```text
artifact-badge.yaml       缺失（需第三方 evaluated / reusable）
scientific-acceptance.yaml 缺失（需外部人类接受）
PAT secrets / branch protection / 跨仓库 CI 实测
第二环境或容器复现证据
Zenodo / OSF DOI、ORCID
```

## 六、值得注意的两个观察

### 1. 全量测试耗时上升到约 203 秒

上轮 1441 项约 123 秒，本轮 1446 项约 203 秒。测试数量只增加 5 项，耗时却增加约 65%。可能是新增 lint / dependency audit 或某些测试变慢。建议关注是否有慢测试进入主套件，必要时拆分 `--fast` / `--full`。

### 2. 工程检查与人工 gate 分离后，需要新的“提交门”

**已修复。** `submission-gate.yml` 提供了“提交/发布时必须全绿”的强制路径，
informational 报告不再可能被当成最终放行依据。

## 七、优先行动清单

### P0：人工验证（唯一真正的科研阻塞）

1. 逐行复核 8 条 proof，特别是 `prop:noncomp`（Proposition 4）。
2. 补齐 citation-support 与 figure-support。
3. 完成真人盲法双编码，输出 kappa 与置信区间。
4. 把 governance 的 COI / 查重 / 披露联系人换成真实值。

### P1：提交门与外部能力

5. **已完成：** high-assurance 提交门由论文仓库的 `submission-gate.yml`
   提供，tag 或手动触发，任一人工 gate 未通过即阻止发布。
6. 接入第二个 family provider，重跑 cross-review 去掉 same-family。
7. 验证两个 PAT secret 与跨仓库 CI 实测。
8. 完成容器或第二环境复现，填 artifact-badge 的 evaluated / reusable 证据。

### P2：收尾与减负

9. 排查全量测试变慢的原因，必要时拆分快速/完整套件。
10. 用 survey / systems / theory 分档 profile 给台账瘦身。
11. 接入 Zenodo/OSF DOI 与 ORCID。
12. 开始往 Research Wiki 填真实卡片。

## 八、结论

这一轮是转折点：论文完成迁移，CI 完成分层，环境基本恢复，工具与论文之间的剪刀差显著收窄。

现在 `ready=false` 的原因只剩两类，且都不是工程问题：

1. 8 条证明还没有真人复核；
2. cross-review 需要真实跨族 provider。

换句话说，**工作流本身已经不再阻塞论文；阻塞论文的只剩人力和外部资源**。下一步的价值不在写代码，而在找到一位能独立复核 Proposition 4 的人，以及接入第二个模型 family。
