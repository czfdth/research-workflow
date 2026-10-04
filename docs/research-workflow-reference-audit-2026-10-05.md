# 对标仓库参考审计

日期：2026-10-05

问题：这些 GitHub 项目在实现前参考了吗？

诚实回答：**之前没有逐仓库读取源码。** 之前的升级是基于
`docs/research-workflow-benchmark-2026-10-05.md` 对这些项目的摘要，采取的是
概念对齐和本地契约设计，不是源码级复刻。本文补做代码级参考核对。

参考快照：

| 项目 | 实际仓库 | commit |
| --- | --- | --- |
| AI-Research-SKILLs | `Orchestra-Research/AI-Research-SKILLs` | `773a52944ba4747a18bd4ae9ade53fff041adcbc` |
| academic-research-skills | `Imbad0202/academic-research-skills` | `6ab4b03bf70a118a1b3ee7f3263ed9f19031061b` |
| ARA paperbench | `AmberLJC/ara-paperbench` | `62e9b54b2d4efe45b97f25676a16784530dd552a` |
| open-science | `aipoch/open-science` | `e4ba390f9f797800b06aa70c5ccae51a956f4baf` |
| ARIS | `wanshuiyin/Auto-claude-code-research-in-sleep` | `2132036060e03e8d0df69a4b21e5971819c0c2d6` |

路径差异：报告里的 `wanshuiyin/ARIS` 当前不存在。实际对应项目名是
`wanshuiyin/Auto-claude-code-research-in-sleep`。

## 1. AI-Research-SKILLs

实际参考到的结构：

- `0-autoresearch-skill/SKILL.md` 明确使用 two-loop architecture。
- `0-autoresearch-skill/templates/research-state.yaml` 单独保存 literature、
  hypotheses、experiments、outer_loop、workspace。
- inner loop 有协议先行、运行、sanity check、metric、记录、保留或回退步骤。
- outer loop 有 deepen、broaden、pivot、conclude 四类方向决策。
- `findings.md` 是跨会话项目记忆，不只是日志。
- `22-agent-native-research-artifact/` 有 compiler、research-manager、
  rigor-reviewer 三件套。

我们的实现：

- `experiment-loop.yaml` 已覆盖 pilot、inner loop、outer loop 和 next action。
- 但没有等价的单一 `research-state.yaml`，没有把 literature、hypotheses、
  proxy metric、baseline、best value、run trajectory 放在一个中心状态文件。
- 没有 ARA compiler 的 `logic/`、`src/`、`evidence/`、`trace/` 五层机器可读结构。
- 没有把 claim 直接映射到可运行 code stub 的字段。
- 没有强制 `/loop` 或 heartbeat 式 wall-clock continuation。

结论：**two-loop 概念已吸收，ARA 编译器和项目级 research-state 尚未完整复刻。**

## 2. ARIS

实际参考到的结构：

- `skills/proof-orchestrator/SKILL.md` 使用 run directory：
  `task.md`、`materials.md`、`local-proof.md`、`sources/`、
  `source-manifest.md`、`browser-prompt.md`、`handoff.md`、
  `gpt-pro-output.md`、`audit.md`、`final.md`、`codex-ledger.md`。
- 有 `LOCAL_ATTEMPT`、`LOCAL_PROVED`、`LOCAL_BLOCKED`、
  `READY_FOR_MANUAL_GPT_PRO`、`AUDIT_FAILED` 等状态标签。
- 有 notation gate、derivation structure gate、manual GPT Pro handoff contract。
- `skills/auto-review-loop/SKILL.md` 是 review → fix → re-review 循环，
  reviewer memory、threadId、round state、human checkpoint、difficulty 都可配置。
- `skills/meta-optimize/SKILL.md` 分析 usage logs、失败、收敛、人工干预、
  trigger rate、bottleneck succession，并且是 read-only producer，单独由
  human-invoked apply skill 落地修改。
- `skills/research-wiki/SKILL.md` 有 paper/idea/experiment/claim 四类节点和
  `graph/edges.jsonl` 类型化关系。
- `docs/RESUBMIT_AND_TALK.md` 有 resubmit 的物理隔离、匿名检查、soft-only
  audit、whitelist microedit、adversarial gate，以及 talk 的生成和 polish 流程。

我们的实现：

- `proof_orchestrator.py` 已记录 campaign、attempt、failure、next action，并把
  `proved` 绑定到真人 verified proof-audit。
- 但没有 run directory 文件契约，没有 sources/handoff/browser prompt/raw
  GPT Pro output/audit/final 的分阶段文件。
- 没有 notation gate 和 top-down derivation structure gate。
- `cross_review.py` 只做一次结构化评审，没有 auto-review-loop 的多轮修复、
  reviewer memory、round state 和 acquittal log。
- `meta_optimize.py` 已做聚合候选，但没有 bottleneck succession、trigger-rate
  evaluation、proposal IDs 或独立 apply gate。
- `research_wiki.py` 有 id/kind/related 与索引，但没有 typed graph edges、
  query pack、index/log/gap map，也不是“每读一篇自动 ingest”的流程。
- `post_submission.py` 只校验产出物契约，没有真正执行 resubmit 的物理隔离、
  匿名清点、edit whitelist 和 adversarial gate。

结论：**proof/next action、meta-optimize、wiki、post-submission 的概念已吸收；
run directory、proof gates、multi-round review、graph wiki 和 resubmit
orchestrator 只是部分对齐。**

## 3. academic-research-skills

实际参考到的结构：

- README 明确 human-in-the-loop，AI 是 copilot，不是 pilot。
- `shared/contracts/passport/run_ledger.schema.json` 是 append-only、
  hash-chained run ledger，保存初始指令、checkpoint、用户原话、工具回执、
  progress counters 和 transient file fingerprints。
- `docs/RISK_REGISTER.md` 把风险、控制、证据状态和残余缺口放在一张表里，
  并由 `check_risk_register.py` 校验。
- `docs/DATA_FLOWS.md` 逐项列出网络触点、发送内容、凭据、关掉方式和本地存储。
- README 还明确 claim-source alignment、citation calibration、实验 provenance
  intake 和“检查不能证明程序真的执行过”的边界。

我们的实现：

- `docs/autonomy-policy.md` 已明确人在环边界。
- `run_log.py` 有每次实验的配置、种子、commit、退出码和指标。
- `risk-register.yaml` 有风险、severity、mitigation、evidence、status。
- `governance.py` 有 COI、伦理、许可、AI 使用、查重和披露。

缺口：

- 我们的 run-log 不是 hash-chained append-only ledger，也不专门保存
  checkpoint 问题和用户原话。
- 风险登记册没有“风险 → 控制 → 证据状态 → 残余缺口”的强 schema，也没有
  对应 capability matrix 的 evidence status。
- 没有 `DATA_FLOWS.md` 等价文件，逐项说明每个 provider、connector、cache
  和本地 store 的数据去向。
- Citation semantic support 仍是人工台账，没有 FNR/FPR calibration gold set。

结论：**人在环、run ledger、risk register、governance 的概念已吸收；
hash-chain、capability-evidence 绑定、data-flow map 和 citation calibration 未完成。**

## 4. ARA paperbench

实际参考到的结构：

- 每个 artifact 固定五层：`PAPER.md`、`logic/`、`src/`、`evidence/`、
  `trace/`。
- `logic/claims.md` 每条 claim 有 statement、status、falsification criteria、
  proof/evidence pointers。
- `trace/exploration_tree.yaml` 是 question、experiment、dead_end、decision、
  pivot 的 DAG，dead end 必须记录 hypothesis、failure_mode、lesson。
- `evidence/` 的 figures/tables 通过 README 和 claim pointers 绑定。
- `src/` 是可运行代码、environment、configs；`rubric/requirements.md`
  是专家复现 rubric。

我们的实现：

- `claim-registry.yaml` 已有 statement、type、status、proof、experiments、
  figures、citations、assumptions、limitations。
- `exploration-graph.yaml` 已有 pivot、dead-end、rejected、active，并绑定
  claim 与 run。
- `figures/manifest.yaml` 有字节和来源绑定，但语义支持仍靠人工台账。

缺口：

- 没有 `logic/` 的 concepts、problem、related_work、solution
  algorithm/architecture/constraints/heuristics 分文件结构。
- 没有 claim-to-code-stub 字段，也没有 `src/environment.md` 这种代码层契约。
- exploration graph 是平铺 entries，不是带 `also_depends_on` 的完整 DAG。
- 没有专家 rubric 级别的逐 leaf requirements。

结论：**claim、exploration、evidence 三层已部分对齐；code stub、完整 DAG
和 expert rubric 仍未对齐。**

## 5. open-science

实际参考到的结构：

- `.science` portable research package，包含对话分支、文件版本、Notebook
  records 和 verification evidence。
- 每个 artifact 是不可变、带校验和的版本；Provenance 暴露 producer code、
  inputs、execution history、环境 inventory、conversation branch 和 reviewer findings。
- Reviewer 在独立 context 检查 turn response、execution logs 和 file evidence。
- 本地-first，模型和 agent backend 可替换；权限、网络触点和敏感数据边界有说明。

我们的实现：

- `provenance.json`、`artifact-provenance.yaml`、run-log、repro bundle 已有。
- app workbench 有聊天、工具桥和自定义 HTTP tools。
- GitHub private repo、CI 和 release workflow 已有。

缺口：

- 没有不可变 artifact version store，也没有 session replay。
- 没有可移植 `.science` package。
- 没有 artifact-level producer code、execution history、environment inventory
  的全链 provenance graph。
- 没有独立 context 的 turn-level reviewer。

结论：**provenance 和本地工作台概念已吸收；immutable artifacts、session
replay、`.science` package 尚未实现。**

## 6. 官方方法学来源

我们的现状：

- `venue-checklist.yaml` 是通用 schema，支持状态和 evidence。
- `artifact_badge.py` 已对齐 ACM Available/Evaluated/Reusable 三档。
- `rigor.py` 已实现六维 0..4 评分和真人/模型边界。

缺口：

- 没有把 NeurIPS Paper Checklist 和 ARR Responsible NLP Checklist 的官方条目
  逐条固化进仓库。
- Venue checklist 目前是手填台账，不是每个 venue 的官方 fixture。
- ACM badge 有校验契约，但没有真实 DOI、第三方 evaluated、第三方 reusable。

结论：**方法学 gate 的机械契约已有；官方 checklist 内容和外部归档证据未完成。**

## 7. 总体判定

真实参考状态应写成：

| 来源 | 是否参考过源码 | 我们对齐的程度 |
| --- | --- | --- |
| AI-Research-SKILLs | 本轮补查 | two-loop 概念对齐；ARA 编译器和 research-state 未对齐 |
| ARIS | 本轮补查 | proof campaign/meta/wiki/post-submission 概念对齐；run-dir、proof gates、multi-round review、graph wiki 未对齐 |
| academic-research-skills | 本轮补查 | human-in-loop、run ledger、risk/governance 概念对齐；hash-chain、data-flow、calibration 未对齐 |
| ARA paperbench | 本轮补查 | claim/exploration/evidence 部分对齐；code stub、DAG、rubric 未对齐 |
| open-science | 本轮补查 | provenance/workbench 概念对齐；immutable artifacts、replay、`.science` 未实现 |
| NeurIPS/ARR/ACM | 本轮核对公开结构 | ACM badge 已实现；官方 checklist fixture 未固化 |

因此，之前说“参考了这些项目”只能成立为：

> 参考了报告对这些项目的结构化摘要，并按相同方向设计了本地实现。

不能成立为：

> 逐仓库阅读源码后等价复刻了这些系统。

下一步若继续升级，优先级最高的仍是：

1. 把 AI-Research-SKILLs 的 `research-state.yaml` 和 ARA `logic/src/evidence/trace`
   映射到现有 claim/exploration/run 体系。
2. 把 ARIS 的 proof run directory 与 notation/derivation gate 补进
   `proof_orchestrator`。
3. 把 academic-research-skills 的 hash-chained run ledger、risk capability
   matrix 和 `DATA_FLOWS.md` 纳入治理层。
4. 把 open-science 的 immutable artifact version 与 portable package 接入
   repro/release 流程。

这些才是“真正参考源码后”的下一轮工作，不是继续增加抽象 gate。
