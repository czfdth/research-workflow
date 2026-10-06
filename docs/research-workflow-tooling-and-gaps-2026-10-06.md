# 科研工作流：插件工具清单与开源对标缺点分析

日期：2026-10-06（第二次修订）
范围：本仓库工作流自身的工具、配置的 MCP/插件/skills、已安装 CLI，以及相对于 GitHub 开源科研系统与智能体的差距

> 修订说明：初版把"零技能基线""尝试吞吐度量""远程算力未接通"列为缺点。核对后发现这三项在本日期附近已由 `5e84186`、`39706eb` 等提交补齐，本版按实际状态修正。

## 一句话结论

工具层已经完整：`doctor` 报 0 problems / 0 advisories，87 个工具模块、72 个入口、9 个 MCP、28 个插件、305 个 skills、25 类 CLI、9 个形式化引擎。上一轮提出的方法学建议（claim 极性、held-out、对照运行、零技能基线、尝试吞吐、guard 失败演练、双循环、不可变 artifact）**已全部吸收**。剩余缺点只剩外部链路与人工验证两类。

## 一、工作流自身的工具（87 模块 / 72 入口）

### 状态与编排

`state`、`stages`、`dispatch`、`long_task`、`watch`、`autoresearch`、`experiment_loop`、`experiment_optimizer`、`research_state`、`queue`、`compute`

### 证据与核验

`dataval`/`datavalue`、`trace_claims`、`citation_guard`、`citation_ledger`、`citation_calibration`、`doi_lookup`、`bib`、`provenance`、`datasource`、`figure_manifest`、`figurebytes`、`pdftext`、`run_log`、`run_ledger`、`passport_ledger`

### 论证与评审

`argument_audit`、`cross_review`、`review_loop`、`proof_run`、`proof_orchestrator`、`formal_check`、`verifiers`、`rigor`、`human_coding`、`claims_policy`、`claim_extract`、`research_ledgers`、`novelty`、`stats_plan`、`governance`、`governance_map`

### 写作与交付

`latex_check`、`latex_compile`、`latex_structure`、`texdoc`/`texscan`/`texcomment`、`final_check`、`revision_ledger`、`post_submission`、`resubmit_pipeline`、`talk_pipeline`、`venue_fixtures`、`reference_audit`

### 知识管理

`library`、`memory`、`research_wiki`、`dashboard`、`skill_registry`、`skillpack`

### 平台与运维

`doctor`、`readiness`、`e2e_check`、`change_log`、`archive_client`、`artifact_store`、`artifact_badge`、`repro_package`、`repro_container`、`repro_env`、`worktree_audit`、`test_impact`、`meta_optimize`、`friction_log`、`toolchain`、`session_replay`、`ara_compile`、`ara_extract`、`external_adapters`、`cli`、`validate`

## 二、MCP 服务器（9）

`arxiv`、`semantic_scholar`、`zotero`（实测 HTTP 200）、`academic_search`、`paper_search`、`overleaf_olcli`、`github`、`node_repl`、`consensus_bridge`

## 三、启用的插件（28）

- 文档与写作：documents、pdf、spreadsheets、presentations、template-creator、latex、deep-research
- 研究检索：consensus、zotero、github
- 工程与安全：code-review、codex-security、api-blackbox-tester、sentry、superpowers
- 设计与演示：figma、canva、remotion、visualize
- 协作：notion、linear
- 桌面与浏览：browser、chrome、computer-use、unified-computer-use
- 领域专用：boltz-api-cli

## 四、已安装 CLI（`doctor` 0/0）

- 版本控制与 CI：git、gh、git-lfs
- 容器：docker（daemon 可达）
- LaTeX：pdflatex、xelatex、bibtex、latexmk
- PDF 与文档：gswin64c、qpdf、mutool、soffice、pandoc
- 排版：typst、quarto
- 数据与环境：dvc、micromamba、jupyter、Rscript
- 图形与图像：inkscape、magick、ffmpeg、tesseract、pdfcrop
- 工程：codex、node、npx、uv、uvx、cmake、7z、perl
- 形式化（9/9）：z3、cvc5、lean、coqc、isabelle、agda、why3、sage、julia

## 五、Skills（`.codex/skills` 67 + `.agents/skills` 238）

| 类别 | 数量 | 代表 |
| --- | --- | --- |
| 文献与检索 | 47 | literature-review、arxiv-search、paper-lookup、deep-research、exa-search |
| 写作与评审 | 71 | academic-paper、paper-write-sci、latex-paper-en、nature-polishing、rebuttal-writing |
| 数据与统计 | 19 | statsmodels、pymc、scikit-learn、matplotlib、seaborn、shap |
| 知识库 | 9 | obsidian-project-kb-core、zotero-obsidian-bridge、pyzotero |
| 中文文献 | 10 | cnki-* 全套 |
| 投稿与基金 | 20 | ccf-rank、paper-select-journal、cover-letter、nsfc-* |
| 复现与工程 | 5 | reproduce、uv-package-manager、modal |

## 六、已吸收的对标能力（代码核对）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| claim 中心化 | ✅ | `claim-registry.yaml` 串联 proof / experiment / figure / citation / assumption / limitation |
| 探索图与死路 | ✅ | `exploration-graph.yaml` |
| claim 极性 | ✅ | `polarity` 13 处；`descriptive` 不得写成发现性 |
| held-out 纪律 | ✅ | `held_out` 56 处；效果类 claim 必须带 held-out 计划 |
| 对照运行 | ✅ | 效果类 claim 必须引用 negative-control / ablation / baseline |
| 负控 | ✅ | `run_log.VALID_ROLES` 含 `negative-control` |
| **零技能基线** | ✅ | `stats_plan.py`：claim 必须声明"一个零技能方法会得多少分" |
| **尝试吞吐度量** | ✅ | `research_ledgers.COST_METRIC_FIELDS` 要求 `time_to_first_attempt`（value/unit/source）与 `cost_per_attempt`（value/currency/source）；`e2e_check` 渲染趋势 |
| **远程算力声明** | ✅ | `data/compute.yaml` 存在，显式 `backends: []` 并写明"本论文不需要集群"；`compute probe/check/plan/run` 四个子命令 |
| guard 失败演练 | ✅ | `data/gate-failure-drills.yaml` + `gate-drill-not-triggered` 等校验 |
| 双循环编排 | ✅ | `experiment_loop.py` + `experiment_optimizer.py` |
| 不可变 artifact | ✅ | `artifact_store.py` 内容寻址 + `session_replay.py` |
| 跨仓库 CI 与提交门 | ✅ | 两个仓库 Actions + fail-closed `submission-gate` |

旗舰论文的实际台账也可佐证：`cost-ledger.yaml` 已含 `metrics.time_to_first_attempt.status: not-applicable`（附精确理由）与 `metrics.cost_per_attempt`（recorded，0.0 USD），并有 `metrics-history.jsonl` 记录趋势。

## 七、仍然存在的缺点

### 1. 外部归档未验证

`archive_client.py` 已实现 Zenodo（InvenioRDM）与 OSF，token 取自 `ZENODO_TOKEN` / `OSF_TOKEN`。但代码内注释记录本机解析 `zenodo.org` 异常。契约在、链路未通，DOI 未取得；`artifact-badge.yaml` 与 `scientific-acceptance.yaml` 仍未创建。

### 2. 安装版缺干净机器验收

`dist/ccfa-workbench-setup-0.1.0.exe` 已构建，本机 `--self-check` 通过（`probe_ok=true`），但尚未在未装开发环境的机器上完成安装、启动与工具调用验收。

### 3. 六项人工复核未完成

`e2e-check` 列出：proof（8 条）、citation-support（6 条）、figure-support（1 条）、cross-review、claim-candidates 晋升、research-plans 审批。这是 `ready=false` 的直接原因。

### 4. 评审模型能力不足

`cross-review` 由 `qwen3:30b` 出具，被判 `review-advisory-only`；叠加 15 条 `review-contradiction` 与 4 条 `review-unevidenced-pass`，共 20 条否决。另新增 `review-stale`。转绿需要：补完人工台账 + 换成 gate-capable 评审（≥32B 且模型名带参数量，或非本地不同 family provider）。

### 5. governance 台账仍是占位

COI、查重工具、披露联系人仍是 pending 文本，`ccfa.governance` 报 3 个 problem；因不在 standard profile 必需集合内，不阻塞但也未解决。

### 6. 工具自身缺少外部基准评价

MLGym（13 个开放研究任务）、Simreal-MLBench 这类基准用于评价智能体本身。工作流从未用外部基准评估自己，因此"提升了多少科研产出"只有内部台账、没有对照。

### 7. 轻微冗余

同时启用两个来源的 GitHub 插件与两个 computer-use 插件，功能重叠。

## 八、优先建议

1. **打通归档链路**：解决 `zenodo.org` 解析后跑一次 draft 取 DOI，并补 `artifact-badge.yaml`。
2. **干净机器验收安装包**：在无开发环境的机器上跑安装 + 自检 + 一次工具调用。
3. **完成六项人工复核**：唯一能把 `ready` 变 true 的路径。
4. **换 gate-capable 评审模型**：本地起一个 ≥32B 且名带参数量的模型，或接一个不同 family 的远端 provider。
5. **填 governance 真实值**：COI、查重、披露联系人。
6. **引外部基准**：选 1-2 个 MLGym 式任务度量工作流本身。
7. **清理重复插件**。

## 九、总结

工具、插件、CLI、形式化引擎与 skills 这一层已经没有缺口，`doctor` 全绿，两个仓库 CI 与提交门齐备。上一轮的方法学建议也已全部落地——包括零技能基线、尝试吞吐度量与远程算力声明。

当前缺点只剩两类：**外部链路未接通**（Zenodo DOI、干净机器验收、gate-capable 评审模型）与**人工验证未完成**（六项复核、governance 占位）。前者是工程可解的，后者只能由人来做。