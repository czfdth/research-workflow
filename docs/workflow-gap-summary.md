# 科研工作流缺口与完善清单

日期：2026-10-05（第二轮复检）

## 一句话结论

上一轮列出的工程类缺口大部分已经关闭：GitHub remote、CI、Dependabot、论文仓库干净快照、审计台账骨架都已落地。当前主要缺口已经从“管线没接好”转为三类：**人工验证还没有做、readiness 会假绿、外部服务尚未就绪**。

## 第三轮修复（2026-10-05）

- `readiness` 现在真实执行 profile 对应的下游 gate，新增 `gate-verified`，任一 gate
  problem 都会使 `ready=false`；`evidence-present` 只保留 presence-only 语义。
- `data/repro-environment.yaml` 的 lockfile 哈希已修正，`repro-env` 重新通过。
- `cross-review check` 对缺 provider provenance 的旧记录 fail-closed；
  `family_override` 不再掩盖缺失的 endpoint/config 哈希。
- `statistics-plan` 支持描述性研究的 `analysis_type: descriptive` 与
  `not-applicable`，论文台账不再伪造功效字段。

## 一、本轮已经关闭的缺口

| 上轮缺口 | 当前状态 | 证据 |
| --- | --- | --- |
| 主仓库没有 remote | 已关闭 | `origin = https://github.com/czfdth/research-workflow.git`，与 `origin/master` 同步 |
| 论文仓库没有 remote | 已关闭 | `origin = https://github.com/czfdth/rag-attack-defense.git`，与 `origin/master` 同步 |
| 没有 GitHub Actions | 已关闭 | 主仓库 `tests/paper-check/repro-smoke/release`，论文仓库 `paper-check/repro-smoke` |
| 没有依赖更新 | 已关闭 | `.github/dependabot.yml`（github-actions + tools pip + app pip） |
| 论文仓库 dirty | 已关闭 | `git status` 干净，HEAD `40b3f3c` |
| standard 台账缺失 | 已关闭 | 7 个台账文件已落地，`readiness` 报 `missing_required: []` |
| readiness 不通过 | 部分关闭 | `ready=true`、`blocking=[]`、`collaboration-ready=pass` |
| run-log E2E 测试隔离 | 已关闭 | 本轮 CI 目标测试集 213 项全部通过 |
| 论文仓库双盲风险 | 已缓解 | 两个仓库未认证 API 均返回 404，符合 private 预期 |

需要强调：台账“已落地”不等于“已验证”。本轮新增文件中有多个是**明确的 pending 占位**，下文单独说明。

## 二、本轮暴露与仍存在的问题

### 1. `readiness` 会假绿（本轮最重要的新发现）

`readiness` 目前只检查台账文件是否存在、schema 是否可解析，**不执行下游 gate**。

实测反例：

```text
python -m ccfa.repro_env --paper-root papers/rag-attack-defense
-> problem_count = 1  (repro-env-lockfile-drift)
-> exit 1

scripts/readiness.ps1 --paper-root papers/rag-attack-defense
-> ready = true
-> dimensions.evidence-present = pass
```

具体漂移：

| 项 | 值 |
| --- | --- |
| `data/repro-environment.yaml` 记录 | `sha256:cf503d5b7c2799659550291e8ff2a2c152257c8486b6b8d6d5803c8d27e8370f` |
| `requirements.lock` 实际 | `sha256:7481a005f985689c9a170de2cf3aa1429176574ce34dbd1209e31880641a2755` |

同样地，`independently-reviewed` 显示 `independent-evidence-present`，但 proof、citation、figure 三个台账的内容其实都是 pending 占位。

建议：`readiness` 应聚合各 gate 的真实退出码，或明确标注每个维度是 `presence-only` 还是 `gate-verified`。当前状态会让人误以为“存在即通过”。

### 2. 人工验证仍未完成（科学核心缺口）

| 台账 | 当前内容 | 结论 |
| --- | --- | --- |
| `proof-audit.yaml` | 8 条全部 `reviewer: Human reviewer pending`、`status: pending` | 未做人工证明复核 |
| `citation-support.yaml` | `supports: []` | 未做引用语义支持 |
| `figure-support.yaml` | `figures: []` | 未做图表语义支持 |
| `human-coding-report.json` | `status: pending-human-dual-coding` | 真人双编码未完成 |
| `governance.yaml` | COI、查重、披露联系人均为 pending | 治理证据不完整 |
| `scientific-acceptance.yaml` | 不存在 | `scientifically-accepted: not-claimed` |

这些是目前真正的科学阻塞项。特别是 Proposition 4 的 soundness 问题仍未被人工复核，而跨模型评审却已经给出 `pass`。

### 3. 模型 provenance：代码已收紧，运行时配置仍漂移

| 位置 | 值 |
| --- | --- |
| `~/.codex/config.toml` | `model = "deepseek-flash"` |
| provider `/v1/models` 实际返回 | 只列出 `deepseek-v4-pro` |
| `tools/ccfa/cross_review.py` | 已删除 `DEFAULT_EXECUTION_MODEL`；执行模型/provider 从 Codex config 解析，缺失 provenance 会 fail closed |
| 已存 `reviews/cross-review.json` | 旧记录仍是 `provider = null`、缺 prompt/config hashes；`cross-review check` 现在退 1 |

因此 doctor 仍报告“配置模型不在模型列表中”。旧同族评审虽然写了 override，但缺少 provider
provenance，readiness 与 cross-review check 都会把它判为 problem。

### 4. 外部服务未就绪

| 服务 | 状态 | 影响 |
| --- | --- | --- |
| Docker daemon | 不可达（本轮回归） | `queue` 的 Docker 沙箱后端不可用 |
| WorkBuddy converter `127.0.0.1:8787` | 连接被拒 | 模型转换链路不可用 |
| Zotero Desktop API `127.0.0.1:23119` | 连接被拒 | 文献管理与引用链路不可用 |

`doctor` 仍以 `exit 0` 结束，因为以上都按 advisory 处理。这在“快速体检”场景合理，但用户容易把退出码 0 读成“全绿”。投稿前应使用 `--strict`。

### 5. CI 跨仓库 secret 尚未验证

两个仓库的跨仓库 checkout 依赖 PAT：

| 仓库 | 需要 secret |
| --- | --- |
| `research-workflow` | `PAPER_REPOSITORY_TOKEN` |
| `rag-attack-defense` | `RESEARCH_WORKFLOW_TOKEN` |

本机没有安装 `gh` CLI，因此无法确认 secret 是否已配置、Actions 是否真正跑过。此外，两个跨仓库 workflow 都是手动触发类型，不是每次 push 都自动验证论文。

### 6. 复现仍停留在 stdlib 级别

- `submission/repro/MANIFEST.json` 的 `requirements` 仍为 `null`；
- `requirements.lock` 只有 `python==3.12.14`，没有第三方包、LaTeX 或容器 digest；
- `reviews/repro-check.json` 的 advisory 明确说明：只在新建 venv 中重跑，不提供容器级隔离；
- 尚无第二台机器或容器的成功实测证据。

因此当前更准确的表述是“关键汇总值可复算”，而不是“完整科研环境可复现”。

### 7. 统计台账存在填充痕迹

`statistics-plan.yaml` 把描述性 SoK 声明为无推断检验，却仍填了 `effect_size: 1.0`、`target_power: 0.8`。这类不适用字段容易被审稿人视为机械填表。建议在 schema 层允许 `not-applicable`，而不是强行填写数值。

### 8. 根仓库仍有轻微未提交改动

```text
 D docs/research-workflow-weaknesses.md
?? repro-bundle.out.json
```

论文仓库已经干净，这两个是主仓库的收尾项。

## 三、还缺的插件与应用

| 能力 | 建议 | 说明 |
| --- | --- | --- |
| 长期归档 / DOI | Zenodo 或 OSF | 录用后归档 artifact 并获取 DOI |
| 作者身份 | ORCID | 投稿元数据与成果归属 |
| CI 本地核验 | GitHub CLI (`gh`) | 查询 secret、Actions 运行与 branch protection |
| 文献管理 | Zotero Desktop | 已配置 MCP，但服务未启动 |
| 模型转换 | WorkBuddy converter | 需启动 8787 服务 |
| 依赖更新 | Dependabot | 已配置，无需新增 |

搜索类插件（arXiv、Semantic Scholar、Paper Search、Academic Search、Overleaf、浏览器）已经足够，不需要继续堆叠。真正缺的是它们之间的去重、证据快照与台账闭环。

## 四、优先行动清单

### P0：先消除假绿与科学阻塞

1. 修正 `repro-environment.yaml` 的 lockfile 哈希，或让 `readiness` 聚合 `repro_env` 的真实结果。
2. 让 `readiness` 汇总各 gate 退出码，区分 `presence-only` 与 `gate-verified`。
3. 完成 proof / citation / figure 三项人工复核。
4. 完成真人第二编码，输出 kappa、置信区间、分歧与裁决。

### P1：修 provenance 与 CI

5. 把 provider 的 `/v1/models` 与 config 的执行模型统一；旧评审记录必须重跑并写入完整 provenance。
6. 配置并验证 `PAPER_REPOSITORY_TOKEN` 与 `RESEARCH_WORKFLOW_TOKEN`，让跨仓库 CI 真正跑一次。
7. 复现包补 lockfile 语义、容器或第二环境证据，并回填 `MANIFEST.json` 的 `requirements`。

### P2：环境与收尾

8. 启动 Docker、WorkBuddy、Zotero，使 `doctor --strict` 归零。
9. 清理根仓库的 `research-workflow-weaknesses.md` 删除状态与 `repro-bundle.out.json`。
10. 把 governance 的 COI、查重、披露联系人补到真实值。
11. 录入 ORCID，并在录用后接入 Zenodo/OSF。

## 五、当前最短路径

如果只做三件事：

1. 修 `readiness` 的假绿问题，并修掉已经暴露的 lockfile 漂移。
2. 完成 Proposition 4 的独立证明复核与真人双编码。
3. 验证两个 PAT secret，让跨仓库 CI 真正在第二环境跑通论文检查与 repro smoke。

完成这三件事后，工作流才会从“结构完备”进入“证据可信”。
