# GitHub Setup

日期：2026-10-04

本页记录把本地科研工作流接到 GitHub 的最小闭环。两个私有仓库已创建并推送，仓库文件包含 Actions、Dependabot、PR 模板、CITATION、LICENSE 和安全说明；分支保护、跨仓库只读凭据和 secret scanning 仍需在 GitHub 中启用。

## 建议仓库

| 仓库 | 可见性 | 内容 |
| --- | --- | --- |
| `czfdth/research-workflow` | private | 工具、工作台、模板、文档 |
| `czfdth/rag-attack-defense` | private | 旗舰论文；双盲投稿期间不要公开 |

不要把本地 PDF 原文库、API key、临时诊断输出或未匿名投稿材料推到公开仓库。

## 本仓库 Actions

| Workflow | 触发 | 作用 |
| --- | --- | --- |
| `tests.yml` | push、pull_request、手动 | 跑工具与工作台的定向测试，不默认全量扫库 |
| `paper-check.yml` | 手动 | 工程确定性检查必须通过；readiness 与人工 gate 单独作为 informational job 运行并上传报告 |
| `repro-smoke.yml` | 手动 | 从干净的私有论文 checkout 验证已有 repro bundle |
| `release.yml` | tag 或手动 | 打包源码、生成 SHA-256 manifest；tag 触发时发布 GitHub release |
| `submission-gate.yml` | tag、手动（论文仓库） | fail-closed：high-assurance readiness、governance、argument-audit、严格跨族评审和复现包必须全部通过 |

`paper-check.yml` 和 `repro-smoke.yml` 默认检出 `czfdth/rag-attack-defense`。由于论文是独立私有仓库，需在工具仓库配置只读 `PAPER_REPOSITORY_TOKEN`；论文仓库反向检出工具时则使用只读 `RESEARCH_WORKFLOW_TOKEN`。

工具和应用 CI 都从带 SHA-256 的 `tools/requirements.lock`、
`app/requirements.lock` 安装依赖，不再直接解析未锁定的 `requirements.txt`。
lockfile 由 `uv pip compile --generate-hashes` 生成，锁文件变化会同时刷新
pip cache key。

`paper-check.yml` 不把人工科研 blocker 冒充成工程失败，也不把它们隐藏为
通过：`deterministic-paper-checks` 只运行可机械判定的检查，必须为绿；
`readiness-and-human-review` 使用 `continue-on-error` 运行 readiness、
governance、argument-audit 和 cross-review，并始终上传对应 JSON/Markdown。
因此工程 CI 可以保持绿色，同时 `ready=false` 与人工待办仍然可见。

真正提交或打 `v*` tag 时，论文仓库的 `submission-gate.yml` 不接受
`continue-on-error`。它会强制运行 high-assurance readiness、governance、
argument-audit、`--strict-cross-family` cross-review 和复现包验证；任一失败
都会阻止发布流程。informational job 负责日常可见性，submission gate 负责
提交时的最终阻断。

## 已接入的远端

```powershell
git remote -v
# origin https://github.com/czfdth/research-workflow.git
```

论文仓库单独执行：

```powershell
git -C papers/rag-attack-defense remote -v
# origin https://github.com/czfdth/rag-attack-defense.git
```

推送前先运行：

```powershell
scripts/readiness.ps1 --paper-root papers/rag-attack-defense --out reviews/readiness.md
git -C papers/rag-attack-defense status --short
```

## GitHub 设置

在两个私有仓库中启用：

- branch protection：主分支要求 PR、要求 Actions 通过、禁止直接 force push；
- Dependabot alerts 和 Dependabot security updates；
- secret scanning；
- private vulnerability reporting 或私有 issue 模板；
- release tag 规则：正式版本用 `vYYYY.MM.DD` 或语义版本。

论文仓库的 workflow 会读取私有 `czfdth/research-workflow` 工具仓库。若两个仓库都保持
private，需要在论文仓库中配置 `RESEARCH_WORKFLOW_TOKEN` secret，令它拥有读取
`research-workflow` 的最小权限；工具仓库配置 `PAPER_REPOSITORY_TOKEN`，令它只读论文
仓库。不要把 token 写入仓库文件。

这些设置是远端状态，不会被本地文件自动强制。readiness 只能检测本地是否存在 remote 和 `.github/workflows`，不能证明远端保护规则已经开启。

## 发布与归档

投稿前保持论文仓库 private。录用或允许公开后：

1. 创建 GitHub release，附 `SHA256SUMS.txt`。
2. 将最终源码、复现包、数据说明和 supplementary artifact 归档到 Zenodo 或 OSF。
3. 把 DOI 写回 `CITATION.cff`、artifact README 和论文的 data availability 段落。
