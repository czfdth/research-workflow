# 科研工作流介绍

日期：2026-10-04
对应设计版本：设计文档 v6

## 一句话

这是一套以「证据落在文件上」为准则的个人科研工作流。主路径是 LaTeX + BibTeX，
模板库固定一份，每开一篇新论文派生一个独立项目目录；阶段由状态文件 `ccfa.yaml`
驱动，凡是能机械判定的检查都写成脚本，需要模型判断的环节则让执行者与评审者分开。

它面向计算机方向的会议与期刊投稿。会议走 rebuttal 尾部，期刊走 major revision
尾部，前段共用同一套流程。

## 一、它要解决的问题

科研里真正反复出事的，通常不是写作能力，而是几类结构性问题：

- 结论与证据脱节：正文里的数字从哪里来，过两周连作者自己都说不清。
- 引用失控：引用的条目没人核验过，或正文里出现指向不存在 bib 键的悬空引用。
- 复现失败：论文说能复现，但打包时才发现少文件、缺参数、换机器跑不起来。
- 版本混乱：`v2`、`final`、`final-final` 满天飞，改坏一个数没法回滚也没法对比。
- 最后一刻加实验：审稿前临时补一组实验，结果主线崩掉，这是论文流产最常见的单一原因。
- 自动化噪声：定时任务天天发「已检查」，人很快就全部忽略。

这套工作流的每条设计，基本都能对应到上面某一项。

## 二、五层架构

| 层 | 职责 | 实现方式 |
| --- | --- | --- |
| 1 业务流程层 | 阶段推进与闭环回流 | `ccfa.yaml` 状态机 + gate 判据 |
| 2 Agent 执行层 | 五类角色路由，执行与评审分离 | 按 stage 路由到技能；gate 节点用独立模型评审 |
| 3 Skills 工具层 | 可复用能力 + 确定性工具 | 现有技能 + 自建校验、追踪、审计脚本 |
| 4 工具适配层 | 对接外部工具 | COM 原生操作 + 本地库 + 文件交换 + 浏览器自动化 |
| 5 知识资源层 | 检索、复用与记忆 | 文献库 + FTS5 全文索引 + 研究记忆（含反重复） |

模板库纳入 git 管理，改坏可回滚。论文库按 slug 派生，默认在 `papers/<slug>/` 下。

## 三、阶段流与 gate

### 会议模式

```
idea -> grounded -> data-ready -> experiment-design -> experiments-running
     -> results-ready -> writing -> internal-review -> submission-check
     -> submitted -> rebuttal -> camera-ready -> archived
```

### 期刊模式

前十个阶段与会议共用，尾部替换为：

```
submitted -> major-revision -> response-letter -> resubmitted -> accepted -> archived
```

每个阶段都有可检验的通过条件。不满足，就不算通过：

| Stage | Gate | 通过条件 |
| --- | --- | --- |
| idea | scope_defined | 问题陈述、至少一条可检验假设、目标 venue 均写明 |
| grounded | novelty_grounded | 列出三篇最近邻工作及各自盲区，说明本工作填补的是哪一块 |
| data-ready | provenance_recorded | 逐份数据有来源、分类与校验和；无未登记数据 |
| experiment-design | design_frozen | 每个 claim 对应一个实验；含种子计划、失败判据与平台画像 |
| experiments-running | results_recorded | 每次运行留有配置、种子、commit、退出码、指标 |
| results-ready | claims_supported | 每个 claim 指到具体数值，且通过行内标记脚本核对 |
| writing | draft_complete | 正文、图表、引用齐备；页数符合 venue |
| internal-review | review_cleared | 跨模型评审无 blocking；引用、数字、图表三项核验通过 |
| submission-check | package_ready | 模板、匿名、页数、元数据通过；复现包在干净环境重跑成功 |

回退是被允许的：任一阶段发现前置结论不成立，可以回退，但必须在 `ccfa.yaml`
里记下从哪退到哪、触发事实是什么、哪些产物仍有效、哪些作废。

## 四、确定性工具

能机械判定的工作不靠提示词反复推导，写成脚本，让证据落在文件上。
核心是九个工具：

| 工具 | 作用 |
| --- | --- |
| `citation-guard` | 引用只在检索期入库；核验 DOI 存在性；检测悬空引用 |
| `trace-claims` | 行内标记数字与活的 JSON / CSV / YAML 源值机械比对 |
| `provenance` | 逐文件来源、分类、校验和；生成可反查的来源文档 |
| `run-log` | 记录每次运行的配置、种子、commit、退出码、指标 |
| `repro-package` | 打包并在干净环境实际重跑，不只看包是否完整 |
| `latex-check` | 结构校验加多引擎编译，不依赖 latexmk |
| `research-version` | 用 git tag 建版本快照并输出任意两版真实 diff |
| `final-check` | 对渲染后的 PDF 做终稿确定性检查 |
| `friction-log` | 记录工具缺陷与指令缺口，跨论文聚合 |

围绕它们还有状态、文献、记忆、编排类工具，全部 CLI 合计 19 个 PowerShell 入口。

所有工具遵循同一份接口契约，否则它们会各自变成需要模型解释的黑盒：

- 输入是文件路径或 stage 名，不读对话历史。
- 机器可读 JSON 到 stdout，人读摘要到 stderr。
- 退出码 `0` 通过，`1` 发现问题，`2` 工具自身出错。
- 检查类工具只读、幂等；写盘工具原子写、不覆盖、可查。

`1` 和 `2` 必须分开。把「工具坏了」混进「检查通过」，比检查本身失效更危险。
这条也是整个 gate 体系的底线：需要「模型自述已完成」才能通过的检查，不算通过。

## 五、证据链

### 数字：从 claim 到源值

正文里每个关键数字写成 `\dataval{<source_path>:<key_path>}{<claimed_value>}`。
编译时它渲染为后面那个值，脚本独立按路径去源文件取值核对。比较语义里有两条
关键规则：按 claimed value 自身的小数位推隐含舍入容差，所以正文写 `0.143`
而源值是 `0.142857...` 不会误报；绝对值、相对值、布尔与字符串各有兜底规则。

指不到源的 claim 不允许标成 supported。`--untagged` 会列出未标记的数字线索，
但只作 advisory，永不改变退出码，因为启发式扫描只能提供线索，不能下判决。

### 图：每张交付图能回答四个问题

答案写在 `figures/manifest.yaml`：数据来自哪些 run、源数据文件是哪个、
生成脚本是谁、脚本哈希多少。两条硬规则：交付图必须由脚本生成，字节格式与扩展名
一致；确实需要手工修图的，必须在 manifest 里注明改了什么。静默修图属于学术诚信
问题，不是格式问题。

### 引用、来源与运行

引用条目来自检索期核验过的库，`citation-guard` 检查 DOI 与悬空引用。
数据文件在 `data/provenance.json` 登记来源与校验和。每次实验运行一运行一文件，
失败也留档，不得静默重试到成功。复现包必须在干净环境真实重跑。

## 六、执行与评审分离

同模型自查有系统性盲区，所以执行者与评审者用不同模型。本机实测的配置是：
执行用 `deepseek-v4-flash`，评审用 `deepseek-v4-pro` 起独立会话。

| 环节 | 执行 | 评审 |
| --- | --- | --- |
| 选题与实验设计 | v4-flash | v4-pro（独立会话） |
| 正文写作 | v4-flash | v4-pro（独立会话） |
| 终稿检查 | 脚本（确定性） | 不需要模型 |

跨模型评审只在 gate 关键节点触发，不逐轮触发，避免成本失控。
现在 `cross-review run` 默认拒绝把同族/未知族模型写成 pass：只有
`family_judgement=="cross-family"` 才允许写入，或显式
`--allow-same-family` 留 override；`check` 对旧同族记录报
`review-same-family`。当前本机尚未配置第二个可用 provider，所以真正跨族仍需
用户接入不同 family 的 provider；工具不会把同族评审冒充成跨族。

## 七、记忆与知识层

共享文献库放在 `library/`，BibTeX 纳入 git，PDF 原件不入库。全文检索用
SQLite FTS5，中文必须用 `trigram` 分词器；两字以内的中文查询回退 `LIKE`。

研究记忆分两类：

- `memory/ideas.md`：选题记忆，每次选题前先读，避免重复自己。
- `memory/dead-ends.md`：反重复记忆，记录走不通的路线，并留一个 `reopen_if`
  字段。没有它，反重复记忆会变成永久排除，误伤本来可行的方向。

## 八、自动化

四类定时或手动任务，默认安静：

| 任务 | 频率 | 行为 |
| --- | --- | --- |
| 文献监控 | 每周 | 只报告未见过的 ID 与实质重叠 |
| 里程碑提醒 | 按 deadline 倒排 | 检查 gate 缺口与到期节点 |
| 阶段推进 | 手动触发 | 读状态、给建议，不自动推进 |
| 实验队列 | 长任务运行期 | 顺序执行，受预算与重试上限约束 |

统一静默策略：没有实质变化就不通知。没有新增文献、没有到期 checkpoint、
没有状态变化、队列没有失败或停止项时，不发「我检查过了」的消息。

硬约束：自动化只做信息收集与提醒，不得修改正文与结论字段，不得自动推进 stage。
实际挂载需要用户明确确认；在此之前只保留模板与手动命令。

## 九、论文工作台

一个本地 PySide6 桌面壳，把「项目 → 阶段 → 检查 → 设置」这条最窄链路做成图形界面，
并在其上加了聊天面板与工具桥：

- 引擎可选 OpenAI 兼容接口或本机 `codex exec`，密钥只从 keyring 取。
- 选中项目后，模型可调用确定性工具：milestones、library、memory、state、trace_claims。
- 写操作（记忆追加、stage 推进或回退）必须先过确认弹窗，拒绝时返回 `user declined`。
- 每次调用追加到 `<paper>/ccfa-workfiles/agent-tools.jsonl`，只记参数哈希与结果，
  不记参数明文或密钥。
- 任意命令执行（`run-log run`）不暴露给模型。

## 十、倒排时间表

会议模式以 deadline 为锚点倒排，T 为截止日：

| 节点 | 要求 |
| --- | --- |
| T-90 | 端到端跑通，能力冻结，不再引入新方法 |
| T-60 | 主实验结果冻结，只补消融 |
| T-30 | 全部 claim 锁定，进入写作；此后不接受新实验 |
| T-21 | 初稿完成 |
| T-14 | 跨模型评审完成 |
| T-7 | 引用、数字、图表三项核验完成 |
| T-3 | 终稿确定性检查通过，打包完成 |
| T-1 | 只做格式与提交，不动内容 |

T-30 之后不接受新实验是硬规则。脚本会区分 `experiment` 与 `build` 运行，
图表渲染与编译不算新实验，但实验记录会被卡住。

## 十一、一个真实例子

`papers/rag-attack-defense/` 是这套流程端到端跑通的第一篇论文：
投 CSF 2027 的 SoK，主题是 RAG 安全威胁模型。

它走的是不同分支：SoK 路线不需要 data 与 experiment 阶段，从 grounded 直接进
writing，但证据要求没有放松。实际留下的记录包括：

- 文献筛选从 485 条唯一记录收敛到 43 篇编码工作，筛选协议与摘要入库。
- 第二轮编码审计对九篇分层抽样做独立复核，四项属性 9/9 一致；论文明确写出
  这是同族模型辅助审计，不是人工双编码。
- 43 行的完整编码矩阵作为生成式横向附录进 PDF，CSV 与生成脚本进匿名制品。
- 数字通过 `\dataval` 绑定到 `tables/matrix-stats.json`，`trace-claims` 零问题。
- 引用、LaTeX 结构、终稿 PDF、图表 manifest、运行日志、来源、复现包逐项通过。
- 跨模型评审经历十二轮，前几轮暴露的真问题包括：评审报告自指循环、形式化结论
  口径不一致、能力编码与定义不符、表格与矩阵不同步。每一轮的处置都留档在
  `reviews/history/`，历史 blocking 不被当成当前结论。
- 期间发现的工具缺陷记进 `friction_log.json`，并各自补了回归测试。

最终 11 页正文通过 CSF 的页数与双盲要求，`submission/checks.md` 汇总了全部
确定性检查结果与仍需作者本人确认的事项。

这个例子的价值不在结果好看，而在于它演示了工作流的核心主张：每个结论都能
指回一个文件，每处修改都有记录，每次失败都留在案卷里。

## 十二、设计原则

1. 确定性优先：能机械判定的，写成脚本；需要模型自述才能通过的 gate 不算通过。
2. 证据落在文件上：结论与证据绑在同一条结构化记录里，不在对话里。
3. 失败必须留档：不得静默重试到成功，否则会直接制造不可复现的结果。
4. 执行与评审分离：gate 节点换独立模型，且如实说明同族评审的局限。
5. 自动化只提醒：修改正文与状态必须经明确授权。
6. 默认安静：没有实质变化就不打扰，否则提醒会很快被忽略。
7. 长任务可中断、可观察、有停止条件：沙箱、预算、停止条件、失败分流四件事齐备。
8. 上下文不盲目压缩：上下文被饿死会让模型反复重读、重跑，成本反而更高。

## 十三、边界与不做什么

- 不把 Word 作为主路径，保留导出能力，但不进主链。
- 不做多人实时协作与云端同步。
- 第一版不做语义检索，只做全文检索。
- 不自动操作未安装的桌面软件，缺失的走 RIS / OMML / CSV 替代。
- 不做传播与影响力追踪，它与投稿是两件不同的事。
- 同一工作不同时投中文期刊与英文会议，跨语言并行投稿先核实两个 venue 的政策。

## 十四、当前规模

| 项 | 数量 |
| --- | --- |
| 确定性 CLI 入口 | 19 个 PowerShell 包装器 |
| 核心确定性工具 | 9 个 |
| 工具侧测试 | 约 785 个测试函数 |
| 工作台测试 | 约 141 个测试函数 |
| venue 模板 | 约 140 个目录 |
| 端到端跑通的论文 | 1 篇（SoK，CSF 2027） |

## 十五、怎么开始

从零搭建：

```powershell
cd <仓库根>
python -m venv tools/.venv
& tools/.venv/Scripts/python.exe -m pip install -r tools/requirements.txt
$env:PYTHONPATH = (Resolve-Path tools).Path
& tools/.venv/Scripts/python.exe -m unittest discover -s tools/tests -t tools -v
```

派生一篇新论文：

```powershell
scripts/new-paper.ps1 my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

随后按 `checklists/conference.md` 或 `checklists/journal.md` 逐阶段推进，
用 `scripts/milestones.ps1 due` 看倒排节点与 gate 缺口。

更完整的目录约定、工具一览、阶段命令速查和环境约束见仓库根目录的 `README.md`，
架构与契约细节见 `docs/design/2026-10-03-research-workflow-design.md`。
