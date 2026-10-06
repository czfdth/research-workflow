# 与 ARIS 的对比：skill 语料 vs 验证基础设施

日期：2026-10-06
对标对象：`wanshuiyin/Auto-claude-code-research-in-sleep`（ARIS），83 个 skill、10 个分类
对比对象：本仓库科研工作流，87 个工具模块 / 72 个入口 / 20 个 gate

## 一句话结论

两者不是同一类东西：**ARIS 是 agent 侧的 skill 语料（markdown 提示词 + 调用契约），你的工作流是验证侧的基础设施（确定性 gate + 证据台账 + provenance）**。ARIS 在"能做什么"上更宽，你在"做过什么能不能被证明"上更深。真正的差距集中在**执行面（GPU 接入）**和**对抗评审的角色细度**，而不是工具数量。

## 二、ARIS 的结构

### 10 个分类、83 个 skill

| 分类 | 数量 | 代表 skill |
| --- | --- | --- |
| Workflow Orchestrators | 15 | research-pipeline、idea-discovery、experiment-bridge、auto-review-loop、paper-writing、rebuttal、resubmit-pipeline、paper-talk、patent-pipeline、meta-optimize、meta-apply |
| Literature & Search | 11 | research-lit、arxiv、semantic-scholar、deepxiv、exa-search、openalex、alphaxiv、novelty-check |
| Ideation & Method Design | 5 | idea-creator、research-refine、experiment-plan、ablation-planner、formula-derivation |
| Proof Engineering | 1 | proof-orchestrator |
| Experiments & Infrastructure | 8 | research-implement-feature、run-experiment、monitor-experiment、analyze-results、experiment-queue、vast-gpu、serverless-modal、qzcli、training-check、system-profile |
| Review, Audit & Assurance | 8 | research-review、experiment-audit、result-to-claim、paper-claim-audit、citation-audit、proof-checker、kill-argument、integrity-forensics |
| Paper Writing & Figures | 13 | paper-plan、paper-write、paper-figure、figure-spec、paper-illustration、mermaid-diagram、paper-compile、auto-paper-improvement-loop、proof-writer、grant-proposal |
| Talks, Posters & Resubmission | 4 | paper-slides、slides-polish、paper-poster-html |
| Patents | 9 | invention-structuring、claims-drafting、specification-writing、prior-art-search、patent-review、jurisdiction-format |
| Meta, Utilities & Integrations | 6 | research-wiki、wiki-enrich、render-html、overleaf-sync、feishu-notify |

### 关键设计特征

1. **skill 即一等公民**：每个 skill 是一个 `SKILL.md`，任何 LLM agent 可读，无框架锁定；为 Codex CLI 提供 `skills-codex/` 镜像。
2. **跨模型评审是默认配置**：执行用 Claude，评审用 GPT xhigh；`/auto-review-loop-llm` 支持任意 OpenAI 兼容后端，`-minimax` 变体，`oracle-pro` 走 Pro 层。
3. **"只产出、不开释"的分离**：`/meta-optimize` 是 read-only producer，`/meta-apply` 是唯一被允许改写 skill 语料的特权落地点，且需跨模型 jury 对 staged diff 给 PASS。
4. **执行面很宽**：本机 / SSH / Vast.ai / Modal / 启智平台；`/experiment-queue` 做多 seed/多配置扫描，带 OOM 重试、stale-screen 清理、wave gating、crash-safe state；`/training-check` 轮询 W&B 抓 NaN 与 loss 发散；`/system-profile` 做性能剖析。
5. **对抗评审角色细**：`/experiment-audit` 专抓假 ground truth、分数归一化作弊、幽灵结果、范围膨胀；`/paper-claim-audit` 用零上下文复核每个数字；`/kill-argument` 用两条独立线程分别写最强拒稿备忘与逐点辩护；`/integrity-forensics` 是 46 种模式的取证扫描。

## 三、逐项对比

### ARIS 明显更强的地方

| 维度 | ARIS | 你 | 差距性质 |
| --- | --- | --- | --- |
| GPU / 算力接入 | 本机 / SSH / Vast.ai / Modal / 启智；队列带 OOM 重试与 wave gating | `compute.py` 已写 Slurm/PBS over SSH，但**未配置**，实际只有本机 + Docker | 执行面缺口，最大 |
| 训练监控 | `/training-check` 轮询 W&B 抓 NaN / 发散 / 空转 | 无 | 缺口 |
| 性能剖析 | `/system-profile` | 无 | 缺口 |
| 对抗评审细度 | 8 个专门角色（含零上下文数值复核、双线 kill-argument、作弊模式取证） | cross_review + review_loop + argument_audit，角色较粗 | 细度缺口 |
| 图件生成 | `/figure-spec` 确定性 JSON→SVG（含形状感知裁边、自环、CJK 宽度）、illustration、mermaid、poster HTML | figure_manifest + 外部 figure skill，无内置确定性渲染器 | 缺口 |
| 投稿后产出 | slides（Beamer+PPTX+notes+script）、slides-polish、poster-html 带度量硬门 | post_submission / resubmit / talk 契约 | 深度缺口 |
| 专利链路 | 9 个 skill 的完整链路 | 无 | 可选缺口 |
| 领域适配 | communications、robotics、architecture/EDA 三个方向适配器 | 无 | 缺口 |
| 知识库自动化 | research-wiki 有生命周期 hook 自动 ingest，wiki-enrich 补 TODO | research_wiki 工具存在但**手工**，只有 3 个文件 | 自动化缺口 |
| 自演化落地 | meta-optimize（只读）→ meta-apply（特权落地 + jury） | meta_optimize 有，缺独立特权落地门 | 设计缺口 |
| 多后端评审 | Codex / 任意 OpenAI 兼容 / MiniMax / Oracle Pro | 4 个 provider（custom、local-qwen、zhipu、openrouter），已用 OpenRouter 免费跨族模型跑通 | 基本持平 |

### 你明显更强的地方

| 维度 | 你 | ARIS |
| --- | --- | --- |
| 确定性校验 | 87 模块、20 个 gate、`fail-closed`；数字回源 `\dataval`、引用 DOI 台账、图表哈希 manifest、台账 schema 校验 | skill 多为 LLM 判断；`/integrity-forensics` 是薄启动器，指向另一个仓库 |
| 状态机与回退 | `ccfa.yaml` 单一事实源，含 stage/gate/history 与 `void_artifacts` 回退作废 | 状态散在 run directory，无统一状态机 |
| 变更审计 | `workflow-change-log.jsonl` 追加式，`change-log check --base` **fail closed**；79 条全 complete | 仅 advisory CI lint（检查硬编码路径） |
| 形式化验证 | 9 个引擎（z3/cvc5/lean/coqc/isabelle/agda/why3/sage/julia）+ `formal-check` gate + 机器校验证明 | `/proof-checker` 是 LLM + 20 类问题分型，无 SMT/证明助手集成 |
| 复现收据 | `repro_container` 固定 digest、`network=none`、收据带 exit code；`repro_env` 校验 lockfile 哈希；Windows 与 Linux 双平台 CI | `/paper-compile` 有编译检查，无收据式容器验证 |
| 归档与 badge | `artifact_badge`（ACM available/evaluated/reusable）、`archive_client`（Zenodo/OSF）、`artifact_store` 内容寻址不可变、`session_replay` | 无对应能力 |
| 单页现状报告 | `e2e_check` 汇总 20 gate + 环境 + 倒计时 + 人工检查点 | 无 |
| 环境预检 | `doctor` 分级（installed/reachable/authenticated/functional），当前 0/0 | 每个 skill 文档写 `Requires`，无预检工具 |
| 人工账本 | proof-audit / citation-support / figure-support / human-coding / governance，含占位符检测与 fail-closed | 依赖 skill 输出，无结构化台账 |

## 四、结论式判断

1. **不是同类替代**：ARIS 解决"智能体能做什么"，你解决"做过的事能不能被证明"。把 ARIS 的 skill 直接搬进来并不能补你的短板，因为你的短板不在提示词层。
2. **你真正的执行缺口是算力**：ARIS 的五种算力后端 + 队列 + 训练监控，是你目前唯一在"能力"层面缺失的整块。`compute.py` 已经把适配器写好了，缺的是配置与使用。
3. **对抗评审可以借两条**：零上下文的 `/paper-claim-audit`（用全新视角复核每个数字）与双线 `/kill-argument`（最强拒稿备忘 + 独立辩护）。这两个模式和你现有的 cross_review 互补，且实现成本低。
4. **自演化的门禁设计值得抄**：read-only producer 与 privileged applier 分离，且落地前对 staged diff 做跨模型 jury。你的 `meta_optimize` 目前没有这一层。
5. **不要照搬专利与 slides 全套**：除非你真要出专利或做 talk，否则先做算力与对抗评审这两块收益最大的。

## 五、建议顺序

1. **接算力**：写 `data/compute.yaml`，先接一台 SSH 机器，验证 `probe_remote` 返回真实后端；再考虑 Vast.ai / Modal。
2. **补队列与监控**：把 `queue.py` 的 OOM 重试 / wave gating 用起来，并加一个 W&B 轮询检查（对应 `/training-check`）。
3. **加两个对抗角色**：零上下文数值复核、双线 kill-argument，输出并入 `argument_audit` 台账。
4. **拆自演化门禁**：`meta_optimize` 只产出，新增特权落地门 + staged diff jury。
5. **自动化 research-wiki**：把 decision / dead-end / method / result 的写入挂到生命周期节点，而不是手工。
6. **按需补图件与投稿后**：若近期要投系统类会议或做 talk，再补确定性 SVG 渲染器与 poster。
7. **领域适配器**：只为长期主攻方向建 1 个，不要铺开。

## 六、一句话总结

ARIS 宽在执行与产出，你深在证据与可验证性；**ARIS 的 skill 数量不是你的短板，它的算力接入面和对抗评审角色细度才是**。

## 七、本次更新后的状态（2026-10-06 修订）

### 对比表里已经过期的行

- **多后端评审**：上表原写"一条 cross_review 路径"，现已过期。`config.toml` 中有 4 个 provider（`custom`、`local-qwen`、`zhipu`、`openrouter`），并且论文已用 OpenRouter 的 `nvidia/nemotron-3-super-120b-a12b:free` 跑通一次 **gate-capable + cross-family** 评审（`exit_code=0`，耗时 289 秒，`model_verdict=blocking`）。
- **工具自评**：新增 `ccfa.tool_eval`，用注入缺陷测量自身 gate 的检出率，当前 10 例中 6 例抓住、4 例干净、0 漏报、0 误报；已接入 `dispatch` 与 `tests.yml`。这缓解了"从未评价过自己"的问题，但仍是自设计用例，不是 MLGym 式外部任务。

### 仍然落后 ARIS 的地方（按差距大小）

| 序号 | 差距 | ARIS | 你 |
| --- | --- | --- | --- |
| 1 | 算力接入面 | 本机 / SSH / Vast.ai / Modal / 启智，队列带 OOM 重试、wave gating、crash-safe state，另有 W&B 训练监控与 `/system-profile` 剖析 | 本机（CPU/GPU + Docker GPU 沙箱）+ `kind: ssh` 通用远程执行，且**整条队列可下发到该后端**（超时/stall/重试/流式输出语义照旧，已实测）；Slurm/PBS 只探测不提交；仍无 Vast.ai/Modal API、无 W&B 监控、无 `/system-profile`、无 wave gating 与可续跑的队列状态；远端 GPU 计量未实现（`gpu_budget_s` 会被拒绝）；论文仍未声明远程后端 |
| 2 | 对抗评审角色细度 | 8 个专门角色：`/experiment-audit` 抓假 ground truth 与分数归一化作弊、`/paper-claim-audit` 零上下文复核数字、`/kill-argument` 双线对抗、`/proof-checker` 20 类分型 + 反例红队、`/integrity-forensics` 46 模式 | 6 个：`cross_review`、`review_loop`、`argument_audit`、`formal_check`，以及 `adversarial_review`（`claim-audit` 零上下文复核数字 + `kill-argument` 双线拒稿/辩护，只产出不开释） |
| 3 | 自演化落地门 | `/meta-optimize`（只读产出）→ `/meta-apply`（唯一特权落地点 + staged diff 跨模型 jury） | 只有 `meta_optimize`，无独立特权落地门 |
| 4 | 图件生成 | `/figure-spec` 确定性 JSON→SVG（形状感知裁边、自环、CJK 宽度）、illustration、mermaid、poster HTML | 依赖外部 figure skill + `figure_manifest`，无内置确定性渲染器 |
| 5 | 投稿后产出深度 | slides + slides-polish + poster-html（带度量硬门） | `post_submission` / `resubmit_pipeline` / `talk_pipeline` 只有契约，无生成器 |
| 6 | 专利链路 | 9 个 skill 的完整链路 | 无 |
| 7 | 领域适配器 | communications / robotics / architecture-EDA | 无 |
| 8 | 知识库自动化 | research-wiki 生命周期 hook 自动 ingest + `/wiki-enrich` 补 TODO | `research_wiki` 工具存在但靠手工，当前只有 3 个文件 |
| 9 | 外部基准评价 | 无（ARIS 也未做） | `tool_eval` 有 10 例自设计用例，仍属自评 |

差距 2 已收窄：`ccfa.adversarial_review` 把零上下文数值复核（`claim-audit`）与双线
kill-argument 落成两个只产出、永不开释的角色。`claim-audit` 按机械规则排除作者的推导
文件并把排除集写入记录，评审进程指向的 staging 目录里不含这些文件；`kill-argument`
用两次互不可见的独立子进程分别写最强拒稿备忘与逐点辩护。未解决的 finding 一律进入
readiness 的 `adversarial-review` gate，无法靠不读它来消化。

差距 1 部分收窄：`ccfa.compute` 新增 `kind: ssh` 通用远程后端，可真正在远端执行
并记账；Slurm/PBS 仍只做可达性探测，`run --backend` 会明确拒绝。实测记录见下方
“算力接口实测”。

### 算力接口实测（2026-10-06）

本机没有可用的远程主机或云 CLI（无 SSH 目标、无 `vastai`/`modal`/`sbatch`/`qsub`），
因此用一个容器内的真实 SSH 服务器做端到端验证，而不是只跑 mock：

* 服务器：`alpine:latest` + `openssh`，容器内 `/usr/sbin/sshd`，映射到 `127.0.0.1:2222`。
* 客户端：Windows 自带 OpenSSH `9.5p2`，通过 `identity_file` + `options` 传私钥与
  `StrictHostKeyChecking=no` / 临时 `UserKnownHostsFile`。
* `compute validate` → 0 problem；`compute probe` → `reachable=true`、`ccfa_ok=true`
  （回执字符串确实从远端返回，不是 TCP 通就算数）。
* `compute run --backend live --minutes 1 -- sh -c "…"` → 远端真的执行了：容器里
  留下了 `/tmp/ccfa-ran` 标记；ledger 记 `backend=ssh:root@127.0.0.1`、`wall_seconds=0.08`。
* 预算：`--minutes 0.05` 跑 `sleep 120`，3.03 秒被杀死，ledger 记 `timed_out=true`、exit 1。
* 超预算与调度器拒绝两条路径都不会写出「看起来成功」的记录。
* 队列远端化：清单写 `backend: live` 后，3 个队列项都在容器里执行——成功项留下
  `/tmp/ccfa-q-ran` 标记；重试项 `FIRST`(exit 7) → `SECOND`(exit 0) 两次尝试后
  `complete`；`timeout_s: 3` 的项在 3 秒被杀、记 exit 124。每条 run-log 都带
  `policy.backend=live` 与 `workdir`，所以"跑在远端"是可核对的字段，不是口头声明。

过程中踩过一个真实坑，值得记下来：用 `ssh-keygen -N '""'`（PowerShell 单引号）会生成
**带口令 `""` 的私钥**，客户端在 BatchMode 下无法解锁，表现为服务端日志已经是
`Accepted key` / `Postponed publickey`，随后连接被关闭——很容易误判成服务端或
算法不兼容。教训是先用 `ssh-keygen -y -f <key>`（不应提示输入口令）确认私钥可
无口令使用，再去怀疑协议层。

`identity_file` 与 `options` 两个字段则是被真实连接需求逼出来的：这次实测就用了
非默认端口、显式私钥、临时 `UserKnownHostsFile` 与 `StrictHostKeyChecking`；真实
集群通常还要 `ProxyJump`、`IdentityAgent` 之类，所以留了原样透传的 `options`。

### 本轮新发现的自身缺陷

跨族评审记录内部不一致：`cross-review.json` 顶层是 `review_tier=gate-capable`、`provider=openrouter`，但它列出的 4 条阻塞里有一条写着 `review-advisory-only` 并引用 **上一版 local-qwen** 的 advisory-only 结论。该条由评审模型自己写出（harness 注入格式是 `review-advisory-only: <model>`，此处没有冒号后缀），属于**过期论断混入阻塞清单**。后果是即使 tier 问题已解决，这条仍会长期出现在 blocking 列表里，削弱报告可信度。

建议：在 `cross_review` 的输入里明确告诉评审方"本次评审将取代之前的评审"，或在校验时拒绝引用其他评审记录的 tier 结论。

**该建议已实现**：`cross_review` 现在会报 `review-stale-finding`，拒绝复述只由工作流给出的结论（上一版评审的 tier / verdict 不得搬用）。详见第八节。

### 仍然存在的非对比类缺点（与 ARIS 无关）

1. 六项人工复核未完成（proof 8 条、citation-support 6 条、figure-support 1 条、cross-review、claim-candidates、research-plans）——这是 `ready=false` 的直接原因。
2. `governance.yaml` 的 COI、查重、披露联系人仍是 pending 文本，`ccfa.governance` 报 3 个 problem。
3. Zenodo / OSF 链路未通（本机 `zenodo.org` 解析异常），`artifact-badge.yaml` 与 `scientific-acceptance.yaml` 仍未创建。
4. 安装包缺干净机器验收。
5. 两个来源的 GitHub 插件与两个 computer-use 插件重复启用。

### 结论

对比关系没有改变：**ARIS 宽在执行与产出，你深在证据与可验证性**。本轮之后，"多后端评审"这条差距已经关闭，"工具自评"部分关闭；真正剩下的结构差距是**算力接入面**、**对抗评审角色细度**与**自演化落地门**这三条。

## 八、第三轮更新（2026-10-06 修订二）

### 已关闭

| 项 | 证据 |
| --- | --- |
| 对抗评审角色细度（差距 2） | 新增 `tools/ccfa/adversarial_review.py`（579 行 + 249 行测试，6 项通过）：`claim-audit` 零上下文数值复核（机械排除作者推导文件并把排除集写入记录，评审进程的 staging 目录不含这些文件）+ `kill-argument` 双线对抗（两次互不可见的独立子进程分别写最强拒稿备忘与逐点辩护），只产出不开释 |
| 新角色接入完整 | 已进 `dispatch`（`adversarial-review`）、`tests.yml` 编译清单、`readiness` 的 `adversarial-review` gate；未解决的 finding 无法靠不读它消化 |
| 过期结论混入阻塞清单 | `cross_review` 现在报 `review-stale-finding`：「blocking[3] 'review-advisory-only' 复述了只由工作流给出的结论；本次评审不得搬用上一版评审的 tier/verdict」。即不再静默接受，而是显式标出 |
| 免费跨族评审来源识别 | 识别独立实验室提供的免费评审模型；已用 OpenRouter 的 `nvidia/nemotron-3-super-120b-a12b:free` 跑通 gate-capable + cross-family 评审 |
| CI 成本 | MiKTeX 改为仅在受影响测试需要编译文档时安装（fail closed） |

### 旗舰论文当前状态

`readiness` 仍为 `ready=false`，两项阻塞：

```text
argument-audit: proof-review-not-verified ×8
cross-review:   review-prompt-drift, review-blocking, review-stale-finding
```

三点值得注意：

1. `review-prompt-drift` 表示评审指令已变（记录 `209465a9…` vs 当前 `683fe633…`），**必须重跑评审**——这与「本轮加了新 gate、改了评审指令」一致。
2. `review-stale-finding` 是修复生效的直接证据：上一版 local-qwen 那条 `review-advisory-only` 已被识别为不可搬运的过期结论。
3. `reviews/adversarial-review.json` **尚未生成**——新角色已建但旗舰论文还没跑过，因此它目前不构成阻塞（gate 只在记录存在时检查）。

### 仍然落后 ARIS 的地方

| 序号 | 差距 | 现状 | 说明 |
| --- | --- | --- | --- |
| 1 | 算力接入面 | `data/compute.yaml` 仍为 `backends: []` | 唯一的能力级缺口。ARIS 有本机/SSH/Vast/Modal/启智 + 队列（OOM 重试、wave gating、crash-safe state）+ W&B 训练监控 + `/system-profile` |
| 2 | 自演化落地门 | 只有 `meta_optimize` | ARIS 是 `/meta-optimize`（只读）→ `/meta-apply`（唯一特权落地点 + staged diff 跨模型 jury） |
| 3 | 图件生成 | `svg` / `figure_spec` 命中 0 | ARIS 有 `/figure-spec` 确定性 JSON→SVG（形状感知裁边、自环、CJK 宽度） |
| 4 | 投稿后产出深度 | 只有 `talk_pipeline.py` | ARIS 有 slides + slides-polish + poster-html（带度量硬门） |
| 5 | 专利链路 | 无专利模块 | ARIS 有 9 个 skill 的完整链路 |
| 6 | 领域适配器 | 无 | ARIS 有 communications / robotics / architecture-EDA |
| 7 | 知识库自动化 | `library/wiki/` 仍 3 个文件 | ARIS 有生命周期 hook 自动 ingest + `/wiki-enrich` |
| 8 | 外部基准评价 | `tool_eval` 10 例自设计用例 | 双方都没有 MLGym 式外部基准 |

对抗评审这条已从「4 个角色 vs 8 个」收窄为「6 个角色 vs 8 个」。没对齐的两个是 `/experiment-audit`（假 ground truth、分数归一化作弊、幽灵结果、范围膨胀等作弊模式）与 `/integrity-forensics`（46 模式取证）；`/proof-checker` 的 20 类分型部分由 `formal_check` + 9 个形式化引擎覆盖，且你多了一条 ARIS 没有的机器校验证明。

### 与 ARIS 无关的剩余缺点

1. 六项人工复核未完成（proof 8 条、citation-support 6 条、figure-support 1 条、cross-review、claim-candidates、research-plans）。
2. `governance.yaml` 的 COI、查重、披露联系人仍是 pending（`ccfa.governance` 报 3 个 problem）。
3. Zenodo / OSF 链路未通，`artifact-badge.yaml` 与 `scientific-acceptance.yaml` 仍未创建。
4. 安装包缺干净机器验收。
5. 两个来源的 GitHub 插件与两个 computer-use 插件重复启用。

### 结论

差距 2 已按建议收窄，过期结论问题也已修掉并被 gate 捕获。与 ARIS 相比，结构差距只剩三条：**算力接入面**（唯一能力级缺口）、**自演化落地门**、**图件与投稿后产出深度**。其余（专利、领域适配器、wiki 自动化）属于可选方向。
