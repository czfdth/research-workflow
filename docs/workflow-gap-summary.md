# 科研工作流缺口与完善清单

日期：2026-10-05（第六轮推进）

## 一句话结论

工程层面的 bug 已全部修复：全量测试恢复绿色（1211 OK），CI 参数正确并覆盖了两个 E2E 模块，doctor 不再误报 provider。当前 `readiness` 仍为 `ready=false`，但剩下的原因**不再是代码缺陷，而是尚未完成的人工科研验证**。

本轮又修复了相对 `--paper-root` 下 cross-review schema 路径被拼两遍的 bug，
重跑了 cross-review，并完成了一次 Codex Security diff scan（0 reportable findings）。
Zotero 本地端口现已监听；Docker engine 与 WorkBuddy converter 仍未就绪。

## 一、本轮验证基线

| 检查 | 结果 |
| --- | --- |
| 主仓库 | 干净，与 `origin/master` 同步 |
| 论文仓库 | 干净，与 `origin/master` 同步 |
| 工具全量测试 | `Ran 1211 tests, OK`（约 96 秒） |
| app 全量测试 | `Ran 187 tests, OK` |
| `doctor` | `0 problems, 3 advisories`，provider 报 `functional 配置模型可用` |
| `readiness` | `ready=false`，blocking 仅剩 scientific 两类 |

## 二、已修复的 bug（累计）

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| BUG-1 | `paper-check` CI 用 `--paper-root` 调 `citation_guard` / `trace_claims`，必然 exit 2 | 已修，参数改为 `--manuscript/--bib/--ledger` 与 `--manuscript` |
| BUG-2 | 没有守护 workflow↔CLI 参数一致性的测试 | 已修，新增 `test_*_paper_commands_are_parseable` |
| BUG-3 | `governance` gate 接受 pending 占位文本 | 已修，现在报 `governance-placeholder` 并 exit 1 |
| BUG-4 | 复现包 `requirements` 为 null、lockfile 哈希漂移 | 已修，`repro_env` 0 problem |
| BUG-NEW-1 | 全量测试 2 个 error，CI 子集检测不到 | 已修，测试补 `model`，CI 增加 `test_automation_e2e` / `test_evidence_integrity_e2e` |
| BUG-NEW-2 | doctor 只读 `data[].id`，对 `models[].slug` 误报 | 已修，`_model_ids` 同时解析 `id` 与 `slug` |

`readiness` 的假绿问题也在本轮之前修复：它现在会聚合各 gate 的真实退出码。

## 三、当前唯一的核心阻塞：

| 项 | 状态 |
| --- | --- |
| `proof-audit.yaml` | 8 条全部 `Human reviewer pending`，人工复核 0/8 |
| `citation-support.yaml` | `supports: []`，0/6 |
| `figure-support.yaml` | `figures: []`，0/1 |
| `human-coding-report.json` | `pending-human-dual-coding` |
| `scientific-acceptance.yaml` | 不存在，`scientifically-accepted: not-claimed` |

`readiness` 当前 blocking：

```text
argument-audit gate failed: proof-review-not-verified ×5
cross-review gate failed: review-blocking, review-uncited-blocking ×2
```

这两项都不是脚本能替代的：

- Proposition 4 等理论主张需要真人逐行复核；
- 需要一位独立真人完成盲法第二编码，并报告 exact agreement、Cohen's kappa 与置信区间。

## 四、仍需处理的问题（非 bug）

### 1. 跨模型评审记录尚未重生成

已重生成。`reviews/cross-review.json` 现在有完整 config-derived provenance、当前输入
哈希与 prompt hash，不再 stale。由于本机没有第二个 family 的 provider，记录仍显式
标为 same-family override；评审 verdict 为 `blocking`，理由正是 proof/citation/figure
人工台账全部 pending。另有 2 条 blocking evidence 未满足引文校验，因此 check 报
`review-uncited-blocking`。

真正跨族评审仍需要接入不同 family 的 provider；当前记录不会冒充独立评审。

### 2. governance 台账仍是占位值

`data/governance.yaml` 中 COI、查重工具、披露联系人仍为 pending 文本。`ccfa.governance` 会正确报 3 个 problem 并 exit 1，因此两个 `paper-check` workflow 目前会在此失败。需要填入真实值（或明确说明不适用）。

### 3. 本地服务未就绪

| 服务 | 状态 |
| --- | --- |
| Docker daemon | 不可达 |
| WorkBuddy `:8787` | 连接被拒 |
| Zotero `:23119` | 已监听；API 请求仍返回错误，需检查 Zotero 本地 API 设置 |

`doctor` 以 advisory 形式报告这 3 项并退出 0。投稿前应使用 `doctor --strict`。

### 4. CI 运维未验证

- `PAPER_REPOSITORY_TOKEN`、`RESEARCH_WORKFLOW_TOKEN` 是否配置未验证（本机无 `gh` CLI）；
- 跨仓库 workflow 为手动触发，不是每次 push 自动验证论文；
- 未见 branch protection 证据。

### 5. 长期归档与身份

- Zenodo / OSF：录用后归档 artifact 并获取 DOI；
- ORCID：投稿元数据与成果归属。

### 6. 复现范围仍有限

`repro_env` 与 `MANIFEST.json` 已对齐，但 `requirements.lock` 只有 `python==3.12.14`，`repro-check` 的 advisory 明确说明不提供容器级隔离，尚无第二机器或容器实测证据。

## 五、优先行动清单

### P0：科研验证

1. 完成 proof（0/8）、citation（0/6）、figure（0/1）人工复核。
2. 完成真人盲法第二编码，输出 kappa、置信区间、分歧与裁决。
3. 若无法及时完成，明确把论文定位为“验证待补”，不要以 `review_cleared` 提交。

### P1：让 gate 与 CI 真正转绿

4. 用真实跨族模型重跑 `cross-review`，替换当前 same-family override。
5. 把 `governance.yaml` 换成真实 COI / 查重 / 披露信息。
6. 验证两个 PAT secret，让跨仓库 CI 在第二环境跑通。

### P2：环境与归档

7. 启动 Docker、WorkBuddy、Zotero，使 `doctor --strict` 归零。
8. 补容器或第二环境复现证据。
9. 接入 ORCID，录用后接入 Zenodo/OSF。

## 六、结论

工具链这一层目前是健康的：1211 + 187 项测试全绿，CI 参数正确，doctor 判断准确，readiness 能忠实反映 gate 状态。工作流现在缺的不是代码，而是**证据**：证明没被人复核、引文语义没被人确认、编码没被第二个人独立做过、评审记录还没有用真实跨族模型重新生成。

换句话说，系统已经准备好承载可信科研；下一步是把人工验证真正做进去。

## 七、第六轮附加证据

- 相对 `--paper-root` 的 cross-review 路径 bug 已修：`paper_root` 在 run/check 入口
  统一 `resolve()`，并新增相对路径回归测试。
- cross-review 已重跑：完整 provenance、无 stale、无 provider-config drift；结果为
  `blocking`，不再用旧 `pass` 冒充有效评审。
- Codex Security diff scan `3e2db666-9c2b-4e48-83dc-df8e46b1f24d` 完成：
  `findingCount=0`。保留的 assurance limitation 是 provider 的 `functional` 状态仍
  基于它自报的模型列表，而不是一次真实推理能力探测。
