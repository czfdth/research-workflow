# 科研工作流工具与插件全清单

日期：2026-10-06
口径：仓库内工作流自身工具 + Codex 侧配置的 MCP/插件/skills + 本机 CLI

## 总览

| 层 | 数量 |
| --- | ---: |
| 工作流工具模块（`tools/ccfa/*.py`） | 102 |
| PowerShell 入口（`scripts/*.ps1`） | 87 |
| MCP 服务器 | 9 |
| 启用插件 | 28 |
| Skills（`.codex/skills` + `.agents/skills`） | 67 + 238 |
| CLI（`doctor` 收录） | 23 类 |
| 形式化引擎 | 9（全部可用） |
| `doctor` 状态 | 0 problems / 0 advisories |

## 一、工作流自身工具（102 模块 / 87 入口）

### 状态与编排

`state`、`stages`、`dispatch`、`long_task`、`watch`、`autoresearch`、`experiment_loop`、`experiment_optimizer`、`research_state`、`queue`、`compute`

对应入口：`state`、`stages`、`long-task`、`watch`、`autoresearch`、`experiment-loop`、`experiment-optimize`、`research-state`、`queue`、`compute`

### 证据与核验

`dataval`/`datavalue`、`trace_claims`、`citation_guard`、`citation_ledger`、`citation_calibration`、`doi_lookup`、`bib`、`provenance`、`datasource`、`figure_manifest`、`figurebytes`、`pdftext`、`run_log`、`run_ledger`、`passport_ledger`、`artifact_store`

### 论证与评审

`argument_audit`、`adversarial_review`、`cross_review`、`review_loop`、`proof_run`、`proof_orchestrator`、`formal_check`、`verifiers`、`rigor`、`integrity_forensics`、`human_coding`、`claims_policy`、`claim_extract`、`research_ledgers`、`novelty`、`stats_plan`

### 治理与合规

`governance`、`governance_map`、`anonymity`、`venue_fixtures`

### 写作与交付

`latex_check`、`latex_compile`、`latex_structure`、`texdoc`/`texscan`/`texcomment`、`final_check`、`revision_ledger`、`figure_spec`、`poster_html`、`poster_measure`、`poster_style`、`slides_polish`、`talk_deck`、`talk_gates`、`talk_pipeline`、`pptx_export`、`post_submission`、`resubmit_pipeline`、`reference_audit`、`patent`

### 知识管理

`library`、`memory`、`research_wiki`、`dashboard`、`skill_registry`、`skillpack`、`domain_adapters`、`ara_compile`、`ara_extract`

### 平台与运维

`doctor`、`readiness`、`e2e_check`、`change_log`、`archive_client`、`artifact_badge`、`repro_package`、`repro_container`、`repro_env`、`worktree_audit`、`test_impact`、`tool_eval`、`meta_optimize`、`meta_apply`、`friction_log`、`toolchain`、`session_replay`、`external_adapters`、`cli`、`validate`、`milestones`、`research_version`

## 二、MCP 服务器（9）

| 名称 | 用途 |
| --- | --- |
| `arxiv` | arXiv 检索与全文 |
| `semantic_scholar` | 引文图与语义检索 |
| `zotero` | 本地文献库读写（实测 HTTP 200） |
| `academic_search` | 综合学术检索 |
| `paper_search` | 论文检索 |
| `overleaf_olcli` | Overleaf 工程操作 |
| `github` | 仓库、PR、Actions、secret |
| `node_repl` | 浏览器与原生界面控制 |
| `consensus_bridge` | Consensus 学术证据检索 |

## 三、启用插件（28）

| 类别 | 插件 |
| --- | --- |
| 文档与写作 | documents、pdf、spreadsheets、presentations、template-creator、latex、deep-research |
| 研究检索 | consensus、zotero、github（两个来源重复启用） |
| 工程与安全 | code-review、codex-security、api-blackbox-tester、sentry、superpowers |
| 设计与演示 | figma、canva、remotion、visualize |
| 协作 | notion、linear |
| 桌面与浏览 | browser、chrome、computer-use、unified-computer-use |
| 领域专用 | boltz-api-cli |

## 四、已安装 CLI（`doctor` 0/0）

| 类别 | 命令 |
| --- | --- |
| 版本控制与 CI | git、gh、git-lfs |
| 容器 | docker（daemon 可达） |
| LaTeX | pdflatex、xelatex、bibtex、latexmk |
| PDF 与文档 | gswin64c、qpdf、mutool、soffice、pandoc |
| 排版 | typst、quarto |
| 数据与环境 | dvc、micromamba、jupyter、Rscript |
| 图形与图像 | inkscape、magick、ffmpeg、tesseract、pdfcrop |
| 工程 | codex、node、npx、uv、uvx、cmake、7z、perl |

## 五、形式化引擎（9/9 可用）

`z3` 5.1.0、`cvc5` 1.3.1、`lean` 4.34.1、`coqc`（Rocq 9.0）、`isabelle` 2025-2、`agda` 2.6.3（WSL）、`why3` 1.6.0（WSL）、`sage` 10.9（WSL）、`julia` 1.13.1

## 六、Skills（67 + 238）

| 类别 | 数量 | 代表 |
| --- | ---: | --- |
| 文献与检索 | 54 | literature-review、arxiv-search、paper-lookup、deep-research、exa-search、cnki-* 全套 |
| 写作与评审 | 73 | academic-paper、paper-write-sci、latex-paper-en、nature-polishing、rebuttal-writing |
| 数据统计与图表 | 19 | statsmodels、pymc、scikit-learn、matplotlib、seaborn、shap、cell-cns-figure |
| 复现与工程 | 7 | reproduce、uv-package-manager、modal、git-workflow、github-research |
| 知识库 | 9 | obsidian-project-kb-core、zotero-obsidian-bridge、pyzotero、open-notebook |
| 投稿与基金 | 21 | ccf-rank、paper-select-journal、cover-letter、nsfc-*、research-grants |

## 七、论文侧的 gate（22 项，按当前 profile）

`schema-valid`、`experiment-loop`、`rigor-rubric`、`proof-orchestrator`、`argument-audit`、`novelty`、`statistics`、`repro-environment`、`post-submission`、`formal-check`、`research-ledgers`、`latex-structure`、`trace-claims`、`citation-guard`、`final-check`、`cross-review`、`repro-package`、`claim-candidates`、`research-plan-candidates`、`gate-drills`、`anonymity`、`adversarial-review`（记录存在时）

## 八、一句话概括

工作流自身是**验证层**：102 个模块覆盖状态机、数字/引用/图表证据链、形式化证明、对抗评审、匿名门、复现收据、归档与 badge、自评与元优化。Codex 侧是**能力层**：9 个 MCP、28 个插件、305 个 skills 提供检索、写作、统计、图表、知识与工程能力。CLI 层提供 LaTeX、PDF、排版、数据与 9 个形式化引擎。三层合起来，`doctor` 全绿，工具侧没有缺口。