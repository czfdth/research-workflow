# 科研工作流全量测试与 GitHub 开源方案对比

- 日期：2026-10-06（Asia/Shanghai）
- 被测对象：`C:\Users\best\Documents\ChatGPT\科研` @ `c59f0242066b82dc72dcbfe77fb84ed73e413e68`
- 样例论文：`papers/rag-attack-defense` @ `8f62955d25f661f0cb73eac9c51e729c03c1fbf5`
- 执行者：Codex
- 对比范围：GitHub 上与本工作流相关的开源科研工作流、科研智能体、技能包与文献研究组件
- 证据口径：本工作流执行了真实全量测试；开源项目以 GitHub 实时元数据 + README/源码树/CI/测试目录/许可文件为依据做能力对比，未对开源项目做端到端功能执行（见第 9 节局限）

## 1. 执行摘要

一句话结论：**本工作流的工程质量与"证据/门禁"能力在同类项目中处于第一梯队，测试与诚实性都经得起检查；最大短板不是功能，而是社区、分发、跨平台与自动化程度。选型上它应定位为"验证与证据层"，与生成型科研智能体互补，而不是二选一。**

| 维度 | 本次结果 |
| --- | --- |
| 全量测试 | tools `2317/2317` 通过，app `268/268` 通过，共 `2585/2585`，0 个 unittest 级跳过 |
| 测试耗时 | tools `276.630s`，app `31.453s`，合计约 `308s` |
| 静态质量 | `ruff 0.16.10`：All checks passed |
| 依赖漏洞 | `pip-audit 2.10.1`：tools 与 app 锁文件均 No known vulnerabilities found |
| 环境自检 | `doctor.ps1`：0 problems，0 advisories；形式化引擎 9/9 可用 |
| 变更日志 | `change-log.ps1 check --base origin/master`：0 problems |
| 论文真实状态 | `ready=false`；22 个 gate 中 20 个通过；2 条真实阻塞；6 项人工待办 |
| 真实阻塞 | `argument-audit` 15 个问题（proof 8、citation-support 6、figure-support 1）；`cross-review` provider config drift + blocking |
| 性能抽样 | CLI 冷启动 `stages` 81.7ms、`dispatch list` 74.2ms |
| 六维自评 | 功能 5 / 性能 4 / 扩展 4 / 易用 3 / 社区 1 / 依赖许可 4 |
| 对比结论 | 最强：确定性证据链、fail-closed 门禁、变更日志纪律；最弱：社区与分发、跨平台、自动生成与执行 |

## 2. 全量测试执行记录

### 2.1 执行命令

```powershell
# tools 全量（不是 impact 子集）
$env:PYTHONPATH = 'tools'
$env:PYTHONUTF8 = '1'
tools/.venv/Scripts/python.exe -m unittest discover -s tools/tests -t tools -v

# app 全量
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
app/.venv/Scripts/python.exe -m unittest discover -s app/tests -t app -v

# 环境与整篇论文快照
scripts/doctor.ps1
scripts/e2e-check.ps1 --paper-root papers/rag-attack-defense

# 仓库契约与 CI 同款质量门
scripts/change-log.ps1 check --base origin/master
uvx ruff@0.16.10 check tools app
uvx pip-audit@2.10.1 -r tools/requirements.lock --disable-pip --progress-spinner off
uvx pip-audit@2.10.1 -r app/requirements.lock --disable-pip --progress-spinner off
```

### 2.2 原始结果

| 检查 | 结果 | 退出码 |
| --- | --- | --- |
| tools unittest discover | `Ran 2317 tests in 276.630s` -> `OK`，汇总行无 `skipped=`，即 0 个 unittest 级跳过 | 0 |
| app unittest discover | `Ran 268 tests in 31.453s` -> `OK`，无跳过 | 0 |
| ruff | `All checks passed!` | 0 |
| pip-audit（tools lock） | `No known vulnerabilities found` | 0 |
| pip-audit（app lock） | `No known vulnerabilities found` | 0 |
| doctor | `0 problems, 0 advisories` | 0 |
| change-log check | `{"problems": [], "advisories": [], "problem_count": 0}` | 0 |
| e2e-check | `ready=false, 2 blocking, 0 environment problems` | 0（快照生成成功，不代表论文就绪） |
| git 工作树 | 测试结束后 `git status --short` 为空 | - |

说明：tools 套件摘要未出现 `skipped=N`，与旧记录里的 `OK (skipped=4)` 不同；本次所有测试都以 `ok` 完成。部分测试内部验证的是"条件不满足时应跳过"的行为，它们本身仍是执行通过的测试。

### 2.3 整篇论文 e2e 快照（节选）

- 阶段：`internal-review` / gate `review_cleared`
- 投稿倒计时：9 天（2026-10-15）
- gate：22 个中 20 个通过；未通过 `argument-audit`、`cross-review`
- `argument-audit` 问题 15 个：`proof-review-not-verified` x8、`citation-support-missing` x6、`figure-support-missing` x1
- `cross-review` 问题 2 个：`review-provider-config-drift`、`review-blocking`
- 人工待办 6 项：proof、citation-support、figure-support、cross-review、claim-candidates、research-plans
- scientific acceptance：`not-claimed`
- 环境：0 problems，0 advisories

这 2 条阻塞是本次"真实测试"最重要的产出：它们说明工作流没有为了全绿而伪造人工复核或模型开释。`argument-audit` 的三类缺口只能由人或真实证据补齐；`cross-review` 的 provider config drift 是配置/记录漂移，可以机械修复，但必须在确定性 gate 不再否决模型 pass 之后才算解决。

度量趋势里的 `blocking=3` 是更早一次带 `--out` 运行时写入 `data/metrics-history.jsonl` 的历史采样；本次快照是只读运行（未传 `--out`），当前阻塞数以本次摘要的 2 条为准。

## 3. 本工作流能力画像

### 3.1 实时规模（2026-10-06 从磁盘重算）

| 指标 | 数值 |
| --- | --- |
| `tools/ccfa/*.py` | 104 |
| `tools/newpaper/*.py` | 4 |
| `scripts/*.ps1` 包装器 | 88 |
| tools 测试文件 | 125 |
| tools 测试定义数（含动态生成/重载） | 2116 个 `def test_*`，实际执行 2317 项 |
| app 测试定义/执行 | 268 / 268 |
| tools 锁文件依赖行 | 691 |
| app 锁文件依赖行 | 137 |
| 变更日志条目 | 125 |
| GitHub Actions workflows | 5（tests、paper-check、repro-smoke、release、reference-audit） |
| 已派生论文项目 | 1（`papers/rag-attack-defense`） |
| 顶层许可 | MIT |
| 公开镜像 | `czfdth/evidence-gated-research`：0 stars、1 open issue、1 contributor |

### 3.2 六维自评（1-5，5 最好；这是判断不是基准测量）

| 维度 | 分数 | 依据 |
| --- | --- | --- |
| 功能完整性 | 5 | idea -> grounded -> experiment -> writing -> review -> submission -> rebuttal -> camera-ready -> archive 全阶段；104 个 CLI 模块覆盖统计、引用、图表、匿名、复现、形式化、talk/poster、归档 |
| 性能与效率 | 4 | CLI 冷启动约 75-82ms；工具链基本确定性；但 88 个包装器逐项 spawn 的测试成本不低，LLM 门禁的速度取决于外部模型 |
| 可扩展性 | 4 | dispatch + wrapper + registry + skillpack 架构清晰；但新增一个 CLI 模块需要同时改 wrapper、测试清单、CI py_compile、README、dispatch、test_impact 六个触点，扩展摩擦偏大 |
| 易用性 | 3 | 文档、worklist、dashboard、桌面工作台都有；但 88 个脚本、PowerShell 优先、安装面（LaTeX/Docker/形式化引擎/本地模型）对新手仍陡峭 |
| 社区活跃度与维护 | 1 | 单人维护、私有开发、公开镜像 0 star/1 issue、无外部贡献者；bus factor 风险最高的一项 |
| 依赖与许可 | 4 | 核心依赖克制（PyYAML、bibtexparser、pylatexenc、PyMuPDF），MIT；但完整能力依赖大量可选重型外部工具（LaTeX、Docker、9 个形式化引擎、MCP/外部服务） |

### 3.3 主要优点

1. 证据优先与 fail-closed：门禁区分 `evidence-present` 与 `gate-verified`，`ready=true` 必须下游检查真实执行。
2. 机械反假通过：跨模型评审必须跨族、gate-capable、绑定输入/配置哈希；本地小模型只能 advisory，不能开释。
3. 可追溯性强：run-log、run-ledger、passport-ledger、artifact-store、change-log、`\dataval` 数字回源构成完整取证链。
4. 工程纪律好：2317 + 268 项全量测试、ruff、pip-audit、change-log check 全过；CI 覆盖 Windows + 真实 LaTeX 编译。
5. 论文状态诚实：当前样例论文如实报告 2 条阻塞和 6 项人工待办，没有伪造完成感。

### 3.4 主要缺点与风险

1. 社区与分发最弱：无外部用户与贡献者，公开镜像几乎无流量；知识集中在单人。
2. 自动化程度有限：强在检查与编排，不强在自主生成实验、写正文或联网做大规模文献发现；这些靠 Codex/外部智能体补。
3. 平台偏向 Windows/PowerShell：POSIX 入口存在，但 CI 只在 `windows-latest` 上跑全量；跨平台承诺缺少真实矩阵证据。
4. 学习曲线：88 个 CLI 对"只想投一篇论文"的用户过量，缺少一条命令的快速路径。
5. 门禁自身缺少外部校准：`tool_eval` 与 gate failure drills 已具备，但缺少公开数据集上的 TPR/FPR 报告，误报/漏报率未量化。
6. 成本与吞吐指标未闭环：e2e 快照中 `time_to_first_attempt` 为空、`cost_per_attempt` 为 0.0，尚未接入真实 provider 用量。
7. 单论文样本：目前只有一篇真实论文走完全流程，规模化（多论文并行、多人协作）证据不足。

## 4. 对比对象与实时元数据

以下数据于 2026-10-06 通过 `gh api` 实时拉取。star/fork 会随时间变化；`90 天提交` 统计窗口为 2026-07-08 至 2026-10-06，`100` 表示达到 API 单页上限（>=100）；`贡献者` 为 contributors 行数（anon=true，上限 100）。

| 项目 | 定位 | Stars | Forks | 许可 | 最近推送 | 90 天提交 | 贡献者 | 测试/CI | 分发方式 |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- | --- |
| wanshuiyin/Auto-claude-code-research-in-sleep（ARIS） | 技能型自主 ML 科研 + 跨模型评审 | 17045 | 1434 | MIT | 2026-10-05 | >=100 | 98 | tests/ 69 项 + 4 workflows | CLI / Claude/Codex 插件 / skills |
| Imbad0202/academic-research-skills-codex（ARS-Codex） | Codex 原生学术研究技能套件 | 12178 | 523 | CC BY-NC 4.0 | 2026-10-03 | 17 | 6 | 顶层无 tests/CI；vendored ARS 内含 pytest.yml、test-count-monotonic、adapters/tests 与 heldout evals | Codex 插件 / skills |
| Imbad0202/academic-research-skills（Claude 版，参考） | Claude 原生学术研究技能套件 | 50635 | 3905 | CC BY-NC 4.0 | 2026-10-03 | >=100 | 22 | tests/ 5 项 + 14 workflows（含 pytest、eval-harness） | Claude 插件 / skills |
| Orchestra-Research/AI-Research-SKILLs | 98 个 ML 科研工程技能库 | 13306 | 940 | MIT | 2026-06-16 | 0 | 17 | 无根级 tests/ + 4 workflows | npm / skills |
| aipoch/open-science | 本地优先科研工作台（桌面应用） | 5427 | 502 | Apache-2.0 | 2026-10-06 | >=100 | 24 | e2e/ 模块测试 + 31 workflows | 安装包 / npm / 源码 |
| SakanaAI/AI-Scientist | 端到端自动科学发现（v1，模板化） | 14671 | 2058 | 自定义 Responsible AI 许可 | 2025-12-19 | 0 | 22 | 无 tests/、无 workflows | 源码 + conda/pip |
| SakanaAI/AI-Scientist-v2 | 树搜索式自动科研（v2） | 7270 | 996 | 自定义 Responsible AI 许可 | 2025-12-19 | 0 | 8 | 无 tests/、无 workflows | 源码 + pip |
| SamuelSchmidgall/AgentLaboratory | 人在环的端到端研究助理 | 5888 | 805 | MIT | 2025-08-20 | 0 | 10 | 无 tests/、无 workflows | 源码 + pip |
| HKUDS/AI-Researcher | 自主科学创新研究原型 | 5779 | 724 | 未发现 LICENSE（API 404） | 2025-10-16 | 0 | 4 | 无 tests/、无 workflows | 源码 + docker |
| RUC-NLPIR/Arbor | 假设树 + 留出集验证的实验优化智能体 | 1099 | 128 | Apache-2.0 | 2026-09-08 | 10 | 13 | tests/ 54 项 + 3 workflows | pip / 源码 |
| microsoft/RD-Agent | 数据/模型研发自动化（LLM 驱动 R&D） | 14852 | 1949 | MIT | 2026-10-02 | 14 | 40 | tests/ 9 项 + 4 workflows | pip（官方标注 Linux） |
| LMDHQ-0420/ResearchPilot-Skills | 中文全流程科研技能（G.0-G.8） | 307 | 6 | MIT | 2026-09-14 | 14 | 2 | 无 tests/、无 workflows | skills + bat/sh 安装 |
| assafelovic/gpt-researcher | Web/本地深研报告智能体 | 29929 | 4084 | LICENSE 为 Apache-2.0，pyproject 声明 MIT（冲突） | 2026-10-01 | >=100 | >=100 | tests/ 142 项 + 6 workflows | pip / Docker / npm |
| Future-House/paper-qa | 科学文献高精度 RAG 组件 | 9318 | 933 | Apache-2.0 | 2026-09-25 | 1 | 42 | tests/ 12 项 + 2 workflows | pip / uv |
| stanford-oval/storm | 主题大纲与长文生成 | 31579 | 2977 | MIT | 2025-09-30 | 0 | 26 | 根目录无 tests/ + 2 workflows | pip（knowledge-storm） |
| Alibaba-NLP/DeepResearch | 开源深研智能体（模型权重 + agent） | 20014 | 1529 | Apache-2.0 | 2026-02-27 | 0 | 30 | 无 tests/、无 workflows | 源码 + 模型权重 |
| dzhng/deep-research | 极简 TS 深研循环 | 19761 | 2002 | MIT | 2026-04-11 | 0 | 16 | 无 tests/、无 workflows | npm / Docker |
| AmberLJC/ara-paperbench | 机器可读科研工件数据集（32 篇 ARA） | 5 | 2 | CC-BY-4.0 | 2026-07-09 | 2 | 1 | 无 tests/、无 workflows | 数据仓库 |
| czfdth/evidence-gated-research（本工作流公开镜像） | 本地证据门禁科研工作流 | 0 | 0 | MIT | 2026-10-05 | 8 | 1 | 无公开 CI 徽章数据可查 | 源码 |

## 5. 逐项目对比

### 5.1 直接同类：技能/工作流型

#### ARIS（wanshuiyin/Auto-claude-code-research-in-sleep）

- 定位：把"睡后自动科研"做成 Markdown 技能 + CLI + 插件，强调跨模型评审循环、idea 发现与实验自动化。
- 优点：MIT；社区最活跃（17045 stars、98 贡献者、90 天 >=100 次提交、v0.4.28 持续发布）；69 个测试文件与 4 条 CI（安装脚本、技能清单、lint、test-suite）；适配 Claude Code、Codex、Cursor、Copilot CLI 等 8 种宿主；内置 provider 漂移应对（`codex mcp-server` 移除后的 `codex exec` 桥）。
- 缺点与风险：定位是"方法论而非平台"，证据链偏 prompt/receipt 而非论文级确定性账本；迭代快意味着接口漂移快（README 自己记录了 Codex CLI 破坏性变更）；技能数量大（80+）带来选择与上下文成本；没有 venue 提交门禁、匿名检查、数字回源这类投稿期硬检查。
- 适用场景：希望用现有 coding agent 在夜间迭代 ML 实验、并强制独立模型评审的个人研究者。
- 与本工作流的关系：最互补的同类。ARIS 负责"生成与驱动"，本工作流负责"证据与门禁"；两者的跨模型评审理念同源，但本工作流的 gate-capable/跨族/配置哈希判定更机械、更 fail-closed。

#### ARS-Codex（Imbad0202/academic-research-skills-codex）

- 定位：Codex 原生的学术研究技能套件，覆盖 deep-research、论文写作、审稿、实验与工作流编排，多语言文档齐全。
- 优点：Codex 安装路径最顺（插件 + `skills/academic-research-suite`）；中文文档完善；12178 stars、活跃更新、v3.22.2；对不熟悉 Codex 技能机制的人最省事；vendored ARS 内容自带 adapter tests、pytest CI、test-count-monotonic、eval harness 与 heldout evals。
- 缺点与风险：CC BY-NC 4.0，禁止商业用途，团队/企业场景是硬约束；顶层仓库没有直接运行的 tests/CI，Codex 适配层自身的自动化验证明显少于内容层与父仓库；技能内容以 prompt/agent 编排为主，缺少投稿期确定性验证器；Claude 父仓库（50635 stars）有 5 项 tests/ 与 14 条 workflows（含 pytest、eval-harness），但许可同样为 NC。
- 适用场景：非商业、个人、愿意把写作与调研委托给 Codex 技能的学术用户。
- 与本工作流的关系：可直接作为"内容生成前端"；本工作流补上它没有的引用支持、图表支持、数字回源、匿名与复现门禁。

#### AI-Research-SKILLs（Orchestra-Research）

- 定位：98 个 ML 科研工程技能的开放库，覆盖模型架构、微调、后训练、分布式训练、推理部署、论文写作等 23 类。
- 优点：MIT；技能覆盖面最广；npm 分发 + 4 条 CI（inventory、sync、publish-npm、claude）；文档与 promo 完整；13306 stars。
- 缺点与风险：根目录无测试；90 天内 0 次提交，最近推送为 2026-06-16，已有约 4 个月静默；技能主要面向 ML 工程实现，不覆盖投稿合规、证据链与论文级验证；star/fork 比偏高，需谨慎看待热度。
- 适用场景：需要"模型训练/微调/部署"技能库的 LLM/ML 研究者。
- 与本工作流的关系：它强在实验工程技能，本工作流强在论文证据与送审门禁，两者重叠很小。

#### ResearchPilot-Skills（LMDHQ-0420）

- 定位：中文全流程科研技能，G.0-G.8 覆盖方向探索到写作与翻译。
- 优点：MIT；中文语境贴合；安装脚本简单（bat/sh）；307 stars、14 次/90 天提交、v3.0；作者响应维护中。
- 缺点与风险：仅 2 名贡献者；无 tests/、无 workflows；覆盖广但每阶段深度有限；生态与宿主适配远少于 ARS/ARIS。
- 适用场景：中文个人研究者想要轻量、可读的技能模板。
- 与本工作流的关系：可当写作模板参考，不能替代证据链与门禁。

### 5.2 平台与端到端智能体

#### open-science（aipoch）

- 定位：本地优先、模型无关的科研工作台，桌面应用 + skills + MCP + Python/R 执行，强调可复现工件。
- 优点：Apache-2.0；极活跃（31 条 workflows、90 天 >=100 提交、v0.35.1、24 贡献者）；macOS/Windows/Linux 三平台安装包；e2e/模块/受影响测试脚本齐全；有 Zenodo DOI，科研工件规范意识强；社区渠道（Discord）明确。
- 缺点与风险：年轻（2026-07 创建），接口与数据格式仍在快速演进；JS/Electron 依赖重（41 运行时依赖 + 74 开发依赖）；面向科学数据分析工作台，不是投稿阶段的状态机与证据账本；桌面应用形态对纯 CLI/服务器流程不友好。
- 适用场景：需要图形工作台、跑 Python/R 数据分析、希望本地优先与可复现工件的科研团队或个人。
- 与本工作流的关系：最互补的"平台型"选手。它可在前端做数据分析与工件管理，本工作流在投稿期做证据门禁；两者都强调可复现，但覆盖阶段不同。

#### AI-Scientist v1 / v2（SakanaAI）

- 定位：端到端自动科学发现。v1 依赖人类模板、成功率高；v2 用 agentic tree search 做开放式探索。
- 优点：开创性与影响力最大（v1 14671 stars、v2 7270 stars、有真实 workshop 论文案例）；v1 模板化路径成熟；文档包含完整实验与示例论文；README 给出成本量级（v1 典型 < $15/篇，Claude Sonnet 3.5）。
- 缺点与风险：许可证是自定义 "AI Scientist Source Code License"（基于 Responsible AI Source Code License），第 3.2 节限制监视、未标注合成媒体、医疗诊断等用途，并要求在衍生分发协议中继续传递限制；不是 OSI 开源许可，商业/敏感用途需法律审查。无 tests/、无 CI；最近提交 2025-12-19，已静默约 10 个月；执行 LLM 生成的代码，README 明确要求容器与网络隔离；v2 泛化更强但成功率更低、成本更高；只面向 ML 领域。
- 适用场景：有 GPU 与 API 预算、能在沙箱里跑 ML 课题、希望拿到论文初稿的研究者。
- 与本工作流的关系：它能生成实验与初稿，但几乎没有投稿级证据门禁、匿名检查、数字回源；与本工作流组合时必须由本工作流的 gate 做最终把关，绝不能拿它的"完成"当投稿就绪。

#### AgentLaboratory（SamuelSchmidgall）

- 定位：三个阶段的自主研究助理（文献 -> 实验 -> 报告），支持不同人类参与程度，附带 AgentRxiv 累积研究概念。
- 优点：MIT；人在环设计实用；多语言 README；5888 stars；论文与网站齐全。
- 缺点与风险：最近提交 2025-08-20（约 13 个月静默）；无 tests/、无 CI；`requirements.txt` 是 135 行全量 pin，升级与安全维护困难；文献/实验质量高度依赖 API 模型；无投稿合规与证据账本。
- 适用场景：想要"研究助理"而非"全自动科学家"的个人或小团队。
- 与本工作流的关系：可作为实验与报告的生成器；证据与门禁仍由本工作流负责。

#### AI-Researcher（HKUDS）

- 定位：面向科学创新的自主研究原型，带 benchmark 与 docker。
- 优点：5779 stars；研究叙事完整（NeurIPS 2025）；提供 benchmark 与容器化资产。
- 缺点与风险：无 LICENSE 文件、GitHub 许可接口 404，默认"保留所有权利"，复用与分发法律风险高；最近提交 2025-10-16；无 tests/、无 CI；仓库约 762 MB，工程可维护性弱；4 名贡献者。
- 适用场景：仅适合在授权明确的前提下做研究复现或方法参考。
- 与本工作流的关系：不建议直接集成；如需使用，先解决许可问题。

#### Arbor（RUC-NLPIR）

- 定位：给一个基准和目标，智能体提假设、改代码、跑真实实验，并只保留通过留出数据验证的增益。
- 优点：Apache-2.0；pip 可安装；54 个测试条目 + 3 条 CI；90 天 10 次提交、v0.1.4；强调 held-out 验证与收益保留，实验方法论扎实；支持 Claude 插件。
- 缺点与风险：1099 stars、13 贡献者、尚年轻；覆盖面限于实验优化与 ML 基准，不覆盖投稿、写作、合规；需要真实算力与基准环境。
- 适用场景：已有 benchmark 与评测协议，想自动做模型/超参/代码优化循环的团队。
- 与本工作流的关系：它填补"实验优化执行"空档；其 held-out 保留原则与本工作流的证据门禁理念一致，可对接 run-log 与 experiment-loop。

#### RD-Agent（microsoft）

- 定位：LLM 驱动的数据/模型研发自动化（量化、数据挖掘、Kaggle 等场景），企业级工程规范。
- 优点：MIT；14852 stars、40 贡献者、14 次/90 天提交、v1.0.0；CI、CodeQL、Dependabot、pre-commit、mypy、ruff、readthedocs 齐全；9 个测试目录；pip 安装。
- 缺点与风险：官方平台徽章标注 Linux；重依赖（pyproject 中约 34 个依赖行）；面向 R&D 工程循环而非论文生命周期；cloud/LLM 成本与数据合规需自评。
- 适用场景：企业或实验室里的数据驱动研发自动化，而非个人投稿工作流。
- 与本工作流的关系：可参考其 CI/发布工程；功能上更像"实验研发执行器"，与本工作流互补。

### 5.3 文献研究与深研组件

#### gpt-researcher（assafelovic）

- 定位：Web + 本地资料的深研报告智能体。
- 优点：Apache LICENSE 文件 + 极活跃生态（29929 stars、90 天 >=100 提交、v3.7.0、142 个测试条目、6 条 workflows）；pip/Docker/npm/Colab 全分发；文档与社区成熟（Discord）。
- 缺点与风险：**许可元数据冲突**：仓库 LICENSE 是 Apache-2.0，但 `pyproject.toml` 两处声明 `license = "MIT"`，GitHub 识别为 Apache-2.0；商业使用前必须向上游澄清。功能是"生成报告"，不提供论文级证据账本、投稿合规或数字回源。
- 适用场景：快速调研、技术报告、背景与 related work 素材收集。
- 与本工作流的关系：可作为文献发现与摘要前端；其产出进入本工作流后仍需 citation-support 与 trace-claims 门禁。

#### paper-qa / PaperQA2（Future-House）

- 定位：科学 PDF/Office/代码文件的高精度 RAG 问答与矛盾检测。
- 优点：Apache-2.0；9318 stars、42 贡献者；uv.lock 可复现；12 个测试目录 + 2 条 CI；Python 包与 CLI 双形态；论文声称在科学问答/摘要/矛盾检测上达到超人水平（自述）。
- 缺点与风险：152 个 open issues，90 天仅 1 次提交，进入低速维护；它是组件而非工作流；回答质量依赖底层模型与文献解析质量；不管理投稿状态与合规。
- 适用场景：构建文献问答/证据检索基础设施，或作为写作前的证据检索组件。
- 与本工作流的关系：与本工作流的 `library`/citation 体系互补，可作为检索后端。

#### STORM（stanford-oval）

- 定位：多视角提问 + 检索生成完整带引用长文。
- 优点：MIT；31579 stars、学术影响大；pip 包 `knowledge-storm` 与 Streamlit demo 易上手；2 条 CI。
- 缺点与风险：最近推送 2025-09-30，约 12 个月无提交，维护停滞；根目录无 tests/；生成质量依赖搜索 API 与模型；不覆盖论文投稿与复现。
- 适用场景：生成综述初稿、教学材料、知识整理报告。
- 与本工作流的关系：可作为 related-work 初稿生成器，但引用必须再过本工作流门禁。

#### Alibaba-NLP/DeepResearch（Tongyi）

- 定位：开源深研智能体，含模型与推理代码。
- 优点：Apache-2.0；20014 stars、30 贡献者；技术报告齐全；Web agent 与评测代码完整。
- 缺点与风险：最近提交 2026-02-27；无 tests/、无 CI；仓库约 309 MB，模型部署需要 GPU；不是论文工作流；评测口径与真实科研证据链无关。
- 适用场景：需要开源深研模型/agent 做信息检索任务的研究与工程团队。
- 与本工作流的关系：信息检索能力可参考，但工程形态差异大。

#### dzhng/deep-research

- 定位：极简 TypeScript 深研循环（搜索 -> 抓取 -> 递归深挖 -> 报告）。
- 优点：MIT；19761 stars；实现极小（仓库约 74 KB）、易读；Docker 可跑。
- 缺点与风险：最近提交 2026-04-11；无 tests/、无 CI；依赖 Firecrawl/OpenAI 等外部服务；无科研证据链；更适合当教学示例。
- 适用场景：学习深研 agent 的最小实现，或轻量调研工具。
- 与本工作流的关系：仅作参考实现，不构成竞争。

### 5.4 标准与数据

#### ara-paperbench（AmberLJC）

- 定位：32 篇论文的机器可读、可复现优先研究工件（claims、runnable code、grounded evidence、exploration traces），CC-BY-4.0。
- 优点：把"研究工件应该长什么样"数据化，与本工作流的 claim/exploration/provenance 账本理念高度一致；CC-BY-4.0 便于学术复用。
- 缺点与风险：5 stars、1 贡献者、2026-07 后无更新；是数据集/规范，不是工具；规模小；不能执行验证。
- 适用场景：作为工件 schema 设计参考、评测夹具或对外交换格式。
- 与本工作流的关系：建议作为 `ara-compile`/`ara-extract` 的兼容目标与回归夹具来源。

### 5.5 本工作流的公开镜像定位

`czfdth/evidence-gated-research` 当前 0 stars、0 forks、1 open issue、1 contributor。工程内容不弱，但社区信号几乎为零。这是与 ARIS/ARS/open-science 等最直观的差距，也是第 7 节 P1 建议的第一优先级。

## 6. 六维评分矩阵

评分口径（1-5，判断性评分，不是运行基准）：功能完整性看覆盖阶段；性能与效率看确定性、单机开销与测试成本；可扩展性看插件/API/技能架构；易用性看安装、文档与上手路径；社区活跃度看 stars/贡献者/90 天提交/发布/CI 综合；依赖与许可看依赖重量、可复现性与许可清晰度。本工作流与 OSS 项目使用同一口径，但数据完备度不同，横向比较时请结合第 4 节原始证据。

| 项目 | 功能 | 性能 | 扩展 | 易用 | 社区 | 依赖/许可 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 本工作流（科研） | 5 | 4 | 4 | 3 | 1 | 4 |
| ARIS | 5 | 4 | 5 | 4 | 5 | 5 |
| ARS-Codex | 4 | 3 | 4 | 5 | 5 | 2（NC） |
| AI-Research-SKILLs | 4 | 3 | 5 | 4 | 4 | 5 |
| open-science | 5 | 3 | 5 | 5 | 5 | 5 |
| AI-Scientist v1/v2 | 4 | 2 | 3 | 3 | 4 | 2（自定义） |
| AgentLaboratory | 4 | 2 | 3 | 3 | 3 | 5 |
| AI-Researcher | 3 | 2 | 2 | 3 | 2 | 1（无许可） |
| Arbor | 4 | 4 | 4 | 4 | 3 | 5 |
| RD-Agent | 4 | 4 | 4 | 4 | 5 | 5 |
| ResearchPilot-Skills | 4 | 3 | 3 | 4 | 2 | 5 |
| gpt-researcher | 3 | 4 | 5 | 5 | 5 | 3（许可冲突） |
| paper-qa | 3 | 4 | 4 | 4 | 4 | 5 |
| STORM | 3 | 3 | 3 | 4 | 2 | 5 |
| Alibaba DeepResearch | 3 | 2 | 3 | 2 | 3 | 5 |
| dzhng/deep-research | 2 | 3 | 2 | 3 | 3 | 5 |
| ara-paperbench | 2 | 5 | 3 | 3 | 1 | 4 |

## 7. 改进建议（按优先级）

### P0：投稿前 9 天（2026-10-15）必须处理

1. 用 `scripts/worklist.ps1 --paper-root papers/rag-attack-defense --next` 逐项清理 6 个人工待办：proof 8 条、citation-support 6 条、figure-support 1 条。这些只能靠真实复核，不能用脚本绕过。
2. 处理 `cross-review` 的 `review-provider-config-drift`：用当前 provider/model 配置重新运行 `scripts/cross-review.ps1 run --model <gate-capable 模型>` 并 `check`。不要在 drift 未消除时接受旧 pass。
3. `review-blocking` 必须等到 `argument-audit` 不再否决模型 pass 后再解除；在此之前 `ready=false` 是正确状态。
4. 投稿前按顺序执行：`scripts/doctor.ps1 --strict` -> `scripts/final-check.ps1` -> `scripts/e2e-check.ps1 --paper-root papers/rag-attack-defense --out reviews/e2e-20261006.md`（传 `--out` 会追加一条度量采样，这是有意为之）。

### P1：1-2 个月，决定它能否从"个人工具"变成"可被使用的产品"

5. 快速路径：新增 `scripts/quickstart.ps1`（或 `ccfa start`），把 doctor -> dashboard -> worklist --next 合成一条命令；文档把日常命令压缩到 10 个以内，其余 78 个降级为高级参考。
6. 跨平台实证：CI 从 `windows-latest` 扩到 `ubuntu-latest` 矩阵，真实跑通 POSIX `scripts/ccfa`；把 WSL 作为一等公民写进安装文档与 smoke test。
7. 社区冷启动：公开镜像补齐英文 README、CONTRIBUTING、issue/PR 模板、语义化版本 tag、release notes 与 Discussions；处理当前 1 个 open issue；准备 3-5 个 `good first issue`（文档、跨平台、adapter 类）。
8. 门禁外部校准：用 `scripts/tool-eval.ps1 --benchmark` 对公开 bug/retraction/数值不一致语料跑 argument-audit、citation、figure、trace-claims，公布 TPR/FPR 与样本量；现有 `data/gate-failure-drills.yaml` 已提供基础设施。
9. Agent 互操作：提供只读 MCP server 暴露 `readiness`、`worklist`、`argument-audit`、`e2e-check`，让 Codex/ARIS/open-science 等生成型智能体能调用本工作流的门禁；同时把 ARA paperbench 工件纳入兼容夹具。

### P2：中期能力建设

10. 成本吞吐闭环：把 `time_to_first_attempt`、`cost_per_attempt` 从占位值接到真实 provider 用量与 run-log，按阶段设预算告警。
    **已接通（2026-10-07）**：新增 `ccfa.cost_metrics`，`derive` 从 `ccfa.yaml` 的
    grounded 时间戳（或计划里的 `Frozen at:` 行）、`experiments/log` 的非 build
    运行与 `compute-ledger` + `data/compute.yaml` 的 `pricing` 反推两个指标，
    推不出来就写 `not-applicable` 并点名缺哪个文件，`check` 对台账做双向漂移校验；
    `readiness` 的 cost-ledger 门现在真的跑这个推导，`ccfa.state` 之后的阶段迁移
    写完整 ISO-8601 时间戳。注意：旗舰论文当前两条都是 `not-applicable`——它以
    日期而非时刻冻结计划，且是一篇没有非 build 运行的 SoK；这不是占位值，而是
    有据可查的"不适用"。
11. 远程算力：`queue` 已支持 SSH/SLURM/PBS 后端，但缺一条经过验证的端到端 HPC 路径；补一份可复现实验与故障排查手册。
    **已有一条验证过的路径（2026-10-07）**：`kind: slurm` 现在真的走
    `sbatch --parsable` → `squeue`/退出码轮询 → `scancel` 预算击杀，job id 与状态
    写进 compute-ledger；实测记录与"这次没证明什么"见
    `docs/scheduler-e2e-2026-10-07.md`。仍未验证：真实集群与 PBS/Torque；
    `ccfa.queue` 依旧只接 `kind: ssh`（它的 stall 看门狗与波次 gate 按单条 ssh 写的）。
12. 分发工程：考虑把核心 gate 拆成可 pip 安装的 `ccfa-gates`，用插件 entry point 扩展；为"新增一个 CLI 模块"提供脚手架生成器，自动更新 wrapper、测试清单、CI py_compile、README、dispatch、test_impact 六处触点。
    **已完成（2026-10-07）**：`pyproject.toml` 增加 `smt/crypto/deck/poster/all`
    extras，干净 venv 里 `uv pip install .` 后 `ccfa <gate>` 可直接跑；
    `ccfa new-module create` 一次写模块、wrapper、测试存根与六份清单（任一锚点缺失
    整体拒写），`audit` 只读报告双向漂移，`cost_metrics` 就是它的第一个产物。
13. 快照可读性：e2e 趋势表标注采样时间；当历史采样与当前快照阻塞数不同时，明确显示"历史 vs 当前"，避免读者误判。

## 8. 选型参考

| 你的目标 | 推荐组合 | 理由 |
| --- | --- | --- |
| 个人投稿前的证据与合规把关 | 本工作流（主）+ ARIS 或 ARS-Codex（生成） | 本工作流的 gate 最机械、最诚实；生成型技能补内容产能 |
| 用 Codex 做中文科研，最快上手 | ARS-Codex；如介意 NC 许可则用 ARIS + 本工作流 | ARS-Codex 安装最顺、文档最全；ARIS MIT 且测试/社区更强 |
| 全自动 ML 实验 + 论文初稿 | AI-Scientist-v2（沙箱+预算）或 AgentLaboratory | 端到端生成能力强；必须配本工作流做证据审计与投稿门禁 |
| 已有 benchmark，想自动优化实验 | Arbor；数据/模型 R&D 用 RD-Agent | 都在"实验执行与优化"层，和本工作流互补 |
| 需要图形式科研工作台 | open-science | 三平台桌面应用、本地优先、工程与社区都强 |
| 文献综述、背景调研、深研报告 | gpt-researcher / paper-qa / STORM | 生成与检索成熟；引用与数字仍需本工作流复核 |
| 团队/商业环境 | ARIS、AI-Research-SKILLs、open-science、RD-Agent、paper-qa、Arbor（MIT/Apache） | 许可清晰；避开 AI-Scientist 自定义许可、ARS 的 NC、AI-Researcher 的无许可 |
| 工件格式与可复现规范 | ara-paperbench + 本工作流的 provenance/artifact-store | 前者给数据集与 schema，后者给执行与验证 |

许可红线速查：

- 可直接商用（仍需常规合规）：MIT/Apache-2.0 项目（ARIS、AI-Research-SKILLs、open-science、RD-Agent、paper-qa、Arbor、STORM、AgentLaboratory、ResearchPilot、dzhng）。
- 商用前必须澄清：AI-Scientist v1/v2（Responsible AI 自定义条款与传递义务）、gpt-researcher（LICENSE Apache-2.0 与 pyproject MIT 冲突）。
- 非商业限制：ARS-Codex / academic-research-skills（CC BY-NC 4.0）。
- 无许可默认保留权利：HKUDS/AI-Researcher。

## 9. 局限与证据声明

1. 本次只对**本工作流**执行了端到端真实测试；对开源项目做的是实时元数据、README、源码树、依赖清单、许可文件、CI/测试目录的静态审计，没有运行它们的 agent 任务，因此第 6 节包含判断性评分，不是基准测量。
2. 没有做"同一科研任务、同一模型预算"的跨项目性能对比。各项目的 LLM/GPU 成本、任务形态与依赖差异过大，强行对比会误导；第 4 节的提交频率、测试与 CI 数据是可验证的替代指标。
3. star/fork/issue 数会随时间变化，数据时间戳为 2026-10-06（Asia/Shanghai）；`90 天提交` 与 `贡献者` 有 API 分页上限，已在表头标注。
4. 许可判断基于仓库公开文件，不构成法律意见；CC BY-NC、Responsible AI 许可与无许可项目的实际使用边界应由使用者自行完成法律审查。
5. 论文样例的 `ready=false` 是诚实状态而非测试失败：工具全绿，论文未就绪。两件事必须分开看。
6. 测试环境：Windows 11 + PowerShell 7 + Python 3.12.14（tools/app venv 同版本）；形式化引擎含 Z3 5.1.0、cvc5 1.3.1、Lean 4.34.1、Rocq 9.0、Isabelle2025-2、Agda 2.6.3（WSL）、Why3 1.6.0（WSL）、Sage 10.9（WSL）、Julia 1.13.1。换环境后需要重新验证。

## 附录 A：复现用命令

```powershell
cd C:\Users\best\Documents\ChatGPT\科研

# 1. 全量测试
$env:PYTHONPATH = 'tools'; $env:PYTHONUTF8 = '1'
tools/.venv/Scripts/python.exe -m unittest discover -s tools/tests -t tools
$env:QT_QPA_PLATFORM = 'offscreen'
app/.venv/Scripts/python.exe -m unittest discover -s app/tests -t app

# 2. 环境与论文现状
scripts/doctor.ps1
scripts/e2e-check.ps1 --paper-root papers/rag-attack-defense
scripts/worklist.ps1 --paper-root papers/rag-attack-defense --next

# 3. 仓库契约与质量
scripts/change-log.ps1 check --base origin/master
uvx ruff@0.16.10 check tools app
uvx pip-audit@2.10.1 -r tools/requirements.lock --disable-pip --progress-spinner off
uvx pip-audit@2.10.1 -r app/requirements.lock --disable-pip --progress-spinner off

# 4. 开源项目实时元数据（示例）
gh api repos/wanshuiyin/Auto-claude-code-research-in-sleep --jq '{stars:.stargazers_count,pushed:.pushed_at,license:.license.spdx_id}'
gh api "repos/wanshuiyin/Auto-claude-code-research-in-sleep/commits?since=2026-07-08T00:00:00Z&per_page=100" --jq 'length'
```

## 附录 B：本次使用的关键证据位置

- 测试日志：`%TEMP%\ccfa-tools-full-20261006.log`、`%TEMP%\ccfa-app-full-20261006.log`
- 变更日志：`docs/workflow-change-log.jsonl`（本报告自身条目见同 commit）
- 论文快照数据：`papers/rag-attack-defense/data/metrics-history.jsonl`
- 既有参考：`docs/research-workflow-reference-audit-2026-10-05.md`、`docs/research-workflow-benchmark-2026-10-05.md`、`docs/research-workflow-tooling-and-gaps-2026-10-06.md`
- 上游源码快照（部分空工作树，可用 `git show` 读取）：`C:\Users\best\Documents\Codex\research-refs-20261005`
