# 科研工作流缺口与完善清单

日期：2026-10-04

## 一句话结论

当前工作流已经从“脚本集合”升级为一套有状态、有 gate、有证据、有 readiness 报告的科研基础设施。最新更新补强了环境体检和一页式 readiness 检查，这是实质进步。

但它仍未形成完整闭环：两个私有 GitHub 远端、Actions 与审计台账已经落地，WorkBuddy/Zotero/provider 服务不可用或不完整，跨私有仓库只读凭据尚未配置，科学正确性仍依赖尚未完成的人类复核。

## 已经改善的部分

### 1. `doctor` 体检更诚实

`scripts/doctor.ps1` 已经不再只报告“程序是否存在”，而是开始区分：

| 层级 | 含义 |
| --- | --- |
| `installed` | 命令或虚拟环境存在 |
| `reachable` | daemon 或 HTTP 服务可连接 |
| `authenticated` | 服务没有拒绝凭据 |
| `functional` | 返回了最小预期结果 |

本次检测中它正确发现：

- provider 可连接，但配置模型不在 `/v1/models` 返回列表中；
- WorkBuddy converter 不可达；
- Zotero Desktop API 不可达。

这解决了上一轮最大的“假绿”问题：基础工具存在不再被误读为完整科研链路可用。

### 2. 新增 `readiness` 总览

新增的 `scripts/readiness.ps1` / `tools/ccfa/readiness.py` 能把论文状态、证据台账、Git 状态、deadline 检查和科学边界汇总到一份报告。

它明确区分：

- schema 是否有效；
- evidence 是否存在；
- 是否有独立复核证据；
- 是否声明科学结论已被外部接受。

这比单独运行很多命令更适合日常决策，也能避免“某个检查通过，所以论文科学上正确”的误解。

### 3. `run-log` 测试隔离问题已修复

上一轮失败的两个 `run-log` E2E 测试现在通过。用正确的 `PYTHONPATH=tools` 环境重跑：

```text
tools.tests.test_doctor
tools.tests.test_readiness
tools.tests.test_run_log_e2e
```

共 38 个测试全部通过。

## 当前仍缺什么

### 1. GitHub 远端已建立，保护策略与跨仓库凭据待配置

账号 `czfdth` 下的两个私有仓库已经创建并完成首次推送。Actions、Dependabot、PR 模板和安全元数据已生效；分支保护、secret scanning 与跨私有仓库只读 token 尚未配置。

因此目前缺少：

- 分支保护；
- 论文仓库读取工具仓库所需的最小权限凭据；
- secret scanning 与发布前安全检查；
- 论文 Actions 的成功第二环境运行。

建议创建两个私有仓库：

| 仓库 | 建议可见性 | 用途 |
| --- | --- | --- |
| `research-workflow` | private | 工具、应用、模板、文档 |
| `rag-attack-defense` | private | 旗舰论文；双盲投稿期间不能公开 |

### 2. 旗舰论文审计台账已建，但人工语义审计未完成

`papers/rag-attack-defense/data/` 下八类关键台账均已创建。自动可核验的 governance、novelty、statistics 与 repro environment 检查已通过；以下人工台账仍明确标为 pending：

| 台账 | 当前状态 | 作用 |
| --- | --- | --- |
| `proof-audit.yaml` | pending，0/8 | 人工逐项复核 theorem/proposition/lemma |
| `citation-support.yaml` | pending，0/6 | 人工判断引用是否支撑正文 claim |
| `figure-support.yaml` | pending，0/1 | 人工判断图表是否支撑对应结论 |
| `human-coding-report.json` | pending | 真人双重编码一致性与分歧裁决 |

`readiness` 已进一步收紧：`standard` 和 `high-assurance` 要求 remote 与 Actions；`high-assurance` 不再把 pending 占位台账当作独立复核完成。

### 3. 论文当前不 ready

`scripts/readiness.ps1 --paper-root papers/rag-attack-defense` 当前判定 `ready=false`。

主要 blocking 包括：

- paper git worktree 是 dirty；
- 跨私有仓库工具 checkout 尚未配置只读 secret；
- proof、citation support、figure support 与真人双编码尚未完成人工复核。

当前 `ccfa.yaml` 仍显示：

```text
internal-review / review_cleared
```

但从 readiness 看，更准确的状态应接近：

```text
internal-review / evidence-incomplete
```

### 4. 本地服务仍不可用

最新检测结果：

| 服务 | 当前状态 | 问题 |
| --- | --- | --- |
| provider `127.0.0.1:15721` | 可连接但不 functional | `/v1/models` 返回空列表，配置模型不在列表中 |
| WorkBuddy converter `127.0.0.1:8787` | 不可达 | 服务未启动或端口未监听 |
| Zotero API `127.0.0.1:23119` | 不可达 | Zotero Desktop 或本地 API 未启动 |

这意味着本地科研环境还不是完整可用状态。基础命令存在，但模型评审、WorkBuddy 转换和 Zotero 文献链路不能算 ready。

### 5. 论文仓库仍然 dirty

旗舰论文仓库仍有大量 modified / untracked 文件，包含：

- 论文源文件；
- PDF；
- 复现包；
- stderr / stdout 诊断文件；
- 审计报告；
- 人工编码材料；
- supplementary 压缩包。

这会削弱：

- run-log 的 commit 可追溯性；
- cross-review provenance；
- 复现包与源状态的一致性；
- release 的可审计性。

### 6. 科学正确性仍未闭环

`readiness` 很好地标注了：

```text
scientifically-accepted: not-claimed
```

这意味着系统没有声称脚本能证明论文科学上正确。仍需人工完成：

- Proposition 4 或等价理论主张的独立证明复核；
- 真人第二编码；
- 引用语义支持复核；
- 图表语义支持复核；
- 统计计划人工审查；
- 新颖性检索召回检查；
- 外部人类挑战性评审。

## 还可以完善的插件与应用接入

### 应优先接入或恢复

| 能力 | 建议工具 | 当前问题 |
| --- | --- | --- |
| 远程备份与 CI | GitHub private repos + Actions | 两个 remote 已推送；主 CI 正在修复首次 runner 差异，论文 CI 待只读 secret |
| 文献管理 | Zotero Desktop + Zotero MCP | 配置存在，本地 API 不可达 |
| WorkBuddy 模型/转换服务 | WorkBuddy converter | 桌面进程可能在，但 `8787` 不可达 |
| 长期归档 | Zenodo 或 OSF | 尚未接入 release/DOI 流程 |
| 依赖更新 | Dependabot | 配置已就绪，待推送后启用 |
| 复现环境 | lockfile / GitHub Actions smoke test | 本地环境证据已通过，待 GitHub runner 第二环境实跑 |
| 作者身份 | ORCID | 尚未纳入投稿元数据与归档流程 |

### 暂不需要继续堆叠

以下能力已经足够多，当前问题不是插件不足：

- arXiv / Semantic Scholar / Paper Search / Academic Search；
- Overleaf；
- PDF / Office / 表格插件；
- Docker；
- LaTeX；
- 浏览器和 computer-use。

真正缺的是这些工具之间的闭环：去重、证据快照、台账、CI、复现和长期归档。

## 优先行动清单

### P0：先让当前论文可信

1. 修复、降级或删除 Proposition 4，并完成独立证明复核。
2. 完成真人第二编码，输出 kappa、置信区间、分歧和裁决记录。
3. 补齐 standard profile 必需台账：
   - `citation-support.yaml`
   - `figure-support.yaml`
   - `novelty-audit.yaml`
   - `statistics-plan.yaml`
   - `repro-environment.yaml`
4. 清理旗舰论文 dirty worktree，区分权威输入、生成输出、临时诊断文件和 release artifact。

### P1：建立 GitHub 工程闭环

1. 配置跨私有仓库只读 secret。
2. 验证 GitHub Actions：
   - unit tests；
   - `doctor --skip-services`；
   - `readiness`；
   - citation / trace / latex / final checks；
   - repro smoke test。
3. 配置 branch protection。
4. 配置 Dependabot 或 Renovate。
5. 配置 release 产物生成与 SHA-256 manifest。

### P2：恢复本地服务

1. 修 provider，使 `/v1/models` 返回当前配置模型。
2. 启动 WorkBuddy converter，并验证 `/health`。
3. 启动 Zotero Desktop，并验证 `127.0.0.1:23119`。
4. 用 `scripts/doctor.ps1 --strict` 作为投稿前环境 gate。

### P3：长期归档与公开发布

1. 投稿前保持论文仓库 private，避免双盲泄露。
2. 录用或允许公开后，创建 GitHub release。
3. 将 artifact 同步到 Zenodo 或 OSF，获取 DOI。
4. 增加 `CITATION.cff`、license、数据许可和 artifact README。

## 当前最短路径

如果只选三件事，优先做：

1. 完成四项仍 pending 的人类审计，不伪造 reviewer 或结论。
2. 提交旗舰论文仓库，使 run-log 和 review provenance 能指向确定 commit。
3. 配置最小权限 token，并在论文 Actions 第二环境实跑一次。

完成这三件事后，工作流才会从“本机很强的科研脚手架”变成“可协作、可审计、可恢复、可发布的科研生产线”。
