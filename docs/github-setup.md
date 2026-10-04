# GitHub Setup

日期：2026-10-04

本页记录把本地科研工作流接到 GitHub 的最小闭环。仓库文件已经包含 Actions、Dependabot、PR 模板、CITATION、LICENSE 和安全说明；远端仓库、分支保护和 secret scanning 仍需在 GitHub 私有仓库中启用。

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
| `paper-check.yml` | 手动 | 检出指定私有论文仓库，跑 readiness、人工论证台账与确定性检查 |
| `repro-smoke.yml` | 手动 | 从干净的私有论文 checkout 验证已有 repro bundle |
| `release.yml` | tag 或手动 | 打包源码、生成 SHA-256 manifest；tag 触发时发布 GitHub release |

`paper-check.yml` 和 `repro-smoke.yml` 默认检出 `czfdth/rag-attack-defense`。由于论文是独立私有仓库，需在工具仓库配置只读 `PAPER_REPOSITORY_TOKEN`；论文仓库反向检出工具时则使用只读 `RESEARCH_WORKFLOW_TOKEN`。

## 远端接线步骤

```powershell
git remote add origin https://github.com/czfdth/research-workflow.git
git push -u origin master
```

论文仓库单独执行：

```powershell
git -C papers/rag-attack-defense remote add origin https://github.com/czfdth/rag-attack-defense.git
git -C papers/rag-attack-defense push -u origin master
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
