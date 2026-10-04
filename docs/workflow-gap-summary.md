# 科研工作流缺口与完善清单

日期：2026-10-05（第四轮修复）

## 一句话结论

上一轮的 `readiness` 假绿问题已经修好。本轮逐条复现 CI 命令后，修复了
workflow↔CLI 参数不一致、governance pending 占位值、repro bundle 陈旧哈希、
cross-review 隐式默认模型等问题；剩余阻塞集中在真实人工复核、运行时 provider
配置、跨仓库 CI secret 与容器级复现。

## 第四轮已修复

| 问题 | 修复 |
| --- | --- |
| `paper-check` 用 `--paper-root` 调 `citation_guard` / `trace_claims` | workflow 改为真实参数；`trace_claims` 新增 `--manuscript` 便捷入口 |
| workflow 参数缺少回归测试 | 新增执行 workflow 中 `python -m ccfa.*` 命令的解析测试 |
| governance 接受 pending 占位值 | `governance-placeholder` 拒绝 pending/TBD/todo/placeholder |
| cross-review 隐式默认模型 | 删除 `DEFAULT_MODEL` / `DEFAULT_EXECUTION_MODEL`；`--model` 必填 |
| repro bundle 哈希陈旧、`requirements=null` | 重建 bundle，写入 60 文件哈希与 `requirements.txt` 哈希；readiness 执行 verify |
| doctor exit 0 容易被误读 | 明确输出 problem/advisory 汇总，并提示投稿前 `--strict` |
| statistics 机械填充 | 支持 `analysis_type: descriptive` 与 `not-applicable` |

## 一、本轮验证基线

| 检查 | 结果 |
| --- | --- |
| 主仓库 `git status` | 干净，与 `origin/master` 同步 |
| 论文仓库 `git status` | 干净，HEAD `42f3000`，与 `origin/master` 同步 |
| 工具全量测试 | `1202 tests, OK`（约 100 秒） |
| app 全量测试 | `187 tests, OK` |
| `readiness` | `ready=false`，正确聚合 gate，不再假绿 |
| `repro_env` | `problem_count=0`，上一轮 lockfile 漂移已修复 |

## 二、发现的 bug

### BUG-1（P0，已修复）：`paper-check` CI 用错误参数调用两个 CLI

两个 workflow 原先用 `--paper-root` 调用 `citation_guard` 和 `trace_claims`，两个
CLI 都不接受该参数。现在 workflow 已改为：

- `citation_guard --manuscript ... --bib ... --ledger ...`
- `trace_claims --manuscript ... --base-dir ...`

`trace_claims` 同时新增 `--manuscript` 入口，扫描目录下全部 `.tex`；原有 `--doc`
接口保持兼容。

### BUG-2（P1，已修复）：没有测试守护 workflow 与 CLI 参数一致性

`tools/tests/test_github_workflows.py` 现在会执行 workflow 中的每条
`python -m ccfa.*` 命令，并拒绝 argparse 的 `unrecognized arguments`、
required-argument 和 invalid-choice 失败。两个 workflow 都已纳入测试。

### BUG-3（P1，已修复）：`governance` gate 接受 pending 占位文本

`data/governance.yaml` 中：

| 字段 | 值 |
| --- | --- |
| COI | `pending final author-specific COI disclosure after de-anonymization` |
| 查重工具 | `manual self-check pending institutional similarity tool before submission` |
| 披露联系人 | `anonymous-submission-contact-pending` |

`governance.py` 现在对 pending/TBD/todo/placeholder/to-be-determined 做显式拒绝，
报 `governance-placeholder`。真实论文当前因此正确返回 3 problems；补真实 COI、
查重工具和披露联系人之前，不应通过 governance gate。

### BUG-4（P1，代码已修复；运行时配置仍漂移）

| 位置 | 值 |
| --- | --- |
| `~/.codex/config.toml` | `model = "deepseek-flash"` |
| provider `/v1/models` | 只列出 `deepseek-v4-pro` |
| `tools/ccfa/cross_review.py` | 已删除硬编码默认模型；`--model` 现在必填，执行模型/provider 从 Codex config 解析 |
| 已存 `reviews/cross-review.json` | `provider=null`、`family_judgement=same-family`、`verdict=pass`、`override_reason=null` |

代码侧的隐式模型选择和 provenance fail-closed 已修复。剩余问题是运行环境：
config 写 `deepseek-flash`，provider 只暴露 `deepseek-v4-pro`；旧评审记录没有
provider/prompt/config hashes，必须重跑后才能可信。

### BUG-5（P2，已缓解）：`doctor` 退出 0 但环境未就绪

```text
Docker daemon        不可达（本轮回归）
WorkBuddy  :8787     连接被拒
Zotero     :23119    连接被拒
provider            配置模型不在 /v1/models 列表中
-> doctor exit 0（全部按 advisory 处理）
```

`doctor` 现在总会输出 problem/advisory 汇总，并明确提示投稿前运行
`scripts/doctor.ps1 --strict`；退出码语义保持不变。

### BUG-6（P2，已修复）：统计台账有机械填充痕迹

`statistics-plan.yaml` 现在使用 `analysis_type: descriptive`，不适用的
effect size、power、seeds 与 alpha 明确写 `not-applicable`；推断性设计仍拒绝该值。

### BUG-7（P2，bundle 已修复；容器隔离仍待补）

- `submission/repro/MANIFEST.json` 已重建：60 个文件哈希更新，`requirements`
  指向 `requirements.txt` 并记录 SHA-256；
- `readiness` 现在会执行 `repro_package verify`，陈旧 bundle 不再假绿；
- `repro-check` 仍仅供标准的 venv 重跑，不提供容器隔离；
- 仍缺第二机器或容器 digest 证据。

## 三、仍然缺失的能力

### 1. 人工验证（科学核心，全部 pending）

| 项 | 状态 |
| --- | --- |
| `proof-audit.yaml` | 8 条全部 `Human reviewer pending`，`0/8` 通过 |
| `citation-support.yaml` | `supports: []`，`0/6` |
| `figure-support.yaml` | `figures: []`，`0/1` |
| `human-coding-report.json` | `pending-human-dual-coding` |
| `scientific-acceptance.yaml` | 不存在，`scientifically-accepted: not-claimed` |

`readiness` 当前 blocking 也正是这两组：`argument-audit gate failed`（proof/citation/figure）与 `cross-review gate failed`。

### 2. CI 运维

- `PAPER_REPOSITORY_TOKEN`、`RESEARCH_WORKFLOW_TOKEN` 未验证（本机无 `gh` CLI）；
- 跨仓库 workflow 为手动触发，不是每次 push 自动验证论文；
- 未见 branch protection 证据。

### 3. 长期归档与身份

- Zenodo / OSF：录用后归档并获取 DOI；
- ORCID：投稿元数据与成果归属。

## 四、优先行动清单

### P0

1. 完成 proof（0/8）、citation（0/6）、figure（0/1）人工复核与真人双编码。
2. 在拥有 repo 权限的凭据下，让两个跨仓库 workflow 真实跑通一次。

### P1

3. 统一 config 与 provider 的实际模型列表，重跑并替换旧 cross-review 记录。
4. 补真实 governance COI、查重工具和披露联系人。
5. 配置并验证 `PAPER_REPOSITORY_TOKEN`、`RESEARCH_WORKFLOW_TOKEN`。

### P2

6. 启动 Docker、WorkBuddy、Zotero，使 `doctor --strict` 归零。
7. 给复现包补 Docker/Dockerfile digest 或第二环境实跑证据。
8. 接入 ORCID，录用后接入 Zenodo/OSF。

## 五、当前最短路径

1. 完成人工证明复核与真人双编码，让 `argument-audit` 从 blocking 变 pass。
2. 修运行时 provider 模型配置，重跑 cross-review 并补齐 provenance。
3. 配置最小权限 token，让两个跨仓库 CI 在第二环境真实跑通。
