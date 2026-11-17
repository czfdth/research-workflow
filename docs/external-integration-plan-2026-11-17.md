# 外部开源项目整合方案

- 日期：2026-11-17
- 触发：用户要求「用 GitHub 上别的开源科研工作流的代码完善本仓库」
- 调研口径：以一手源码 / LICENSE / README 为准；GitHub 匿名 API 限流，star 数取自搜索接口快照（2026-11-17）
- 执行者：WorkBuddy

## 0. 决策摘要

**不直接拷贝任何外部项目的源码进本仓库。** 理由：

1. 本仓库是 MIT；部分同类是 CC BY-NC（ARS）、自定义 Responsible-AI 许可（AI-Scientist）或无 LICENSE（HKUDS/AI-Researcher），拷贝会污染许可边界。
2. 本仓库的核心资产是「确定性证据链 + fail-closed 门禁 + 2480 个测试」，外部生成型项目大多无测试无 CI（见 `research-workflow-full-test-and-oss-comparison-2026-10-06.md`），直接搬代码会拉低工程水位。
3. 真正值得吸收的是**能力和接口设计**，而非字面代码：用本仓库既有的 CLI 契约（`Problem` / `emit` / 退出码 0-1-2）、fail-closed 惯例和 `new-module` 脚手架重新实现。

据此确定四个落点，其中三个已具备基础，两个需要新代码：

| 方向 | 现状 | 本次动作 |
| --- | --- | --- |
| A 联网文献检索 | `external_adapters.py` 只检查适配器是否配好；`library.py` 只搜本地 `refs.bib`；无任何模块调用 OpenAlex/arXiv/S2 检索端点 | **新增独立 CLI** `ccfa literature-search` |
| B 生成型前端对接 | `mcp_gates.py` 已是只读 MCP server，README 有配置示例 | **补 ARC/EvoScientist 对接示例文档**，不改代码 |
| C 引用核验升级 | `doi_lookup.py` 用 Crossref+DataCite 双源核验有 DOI 条目；无 DOI 条目无法反查 | **给 citation_guard 加按标题反查**，显式联网、证据体绑定 |
| D 方案文档 | 无 | 本文档 |

## 1. 边界（不变量，任何改动都不得破坏）

1. **默认本地、确定性**。A/C 的联网访问必须显式 opt-in（CLI flag），缺省离线行为与今天完全一致；测试全部用 `fetch` 注入，不依赖真实网络。
2. **只读收集证据，不批准科学结论**（`docs/autonomy-policy.md`）。检索与核验只产出候选和证据，绝不写 `verdict`、不推进 stage、不把 `ready` 置真。
3. **fail-closed 与证据体绑定**。核验失败、HTTP 错误、JSON 非法、标题不符一律报 problem；不能因为「服务没答」就当通过。沿用 `doi_lookup` 的 `found / http_ok / detail / evidence` 契约。
4. **核心 gate 语义不变**。`argument_audit` / `cross_review` / `readiness` 的判定逻辑本次不碰（C 只扩展 `citation_guard` 的输入来源，不改它的 problem 语义）。
5. **许可清洁**。只实现功能，不复制外部代码；新代码 MIT，与本仓库一致。

## 2. 调研发现（外部项目逐个）

### aiming-lab/AutoResearchClaw（MIT，约 15k stars）

- 23 阶段 8 phase 的生成型流水线：文献检索（OpenAlex / Semantic Scholar / arXiv 真实 API）→ 假设 → 沙箱实验 → 写作 → LaTeX。
- 值得吸收的设计：**4 层引用验证**（arXiv ID → CrossRef/DataCite DOI → S2 标题匹配 → LLM 相关性）、`VerifiedRegistry` 强制论文数字来自真实实验、3 个人工 gate（5/9/20）可回滚。
- 不移植：整套流水线、OpenCode 依赖、ACP agent 桥。与本仓库定位（验证层）重叠的是它的验证部分，而它的 DOI 验证本仓库已有更强的双源实现。
- 许可：MIT，干净。

### EvoScientist（Apache-2.0，约 5k stars）

- 自我进化记忆 + 多智能体，工作流 `Intake → plan → execute → evaluate → write → verify`。
- 判断：verify 是描述性阶段，无确定性证据门槛；`human-on-the-loop` 与本仓库的严格签字边界不同。
- 不移植：核心编排、记忆图谱、消息通道。无适合本仓库的独立模块。

### K-Dense-AI/scientific-agent-skills（仓库 MIT，约 57k stars）

- 177 个 `SKILL.md` 技能库，不是工作流引擎；自身声明「不保证科学结论正确、不做认证」。
- 许可陷阱：仓库 MIT，但**每个 skill 可能有独立 license metadata**，不能整体照搬。
- 不移植：技能内容。本仓库已有 `skills/` 体系（`ccfa-core` / `ccfa-evidence` 等），且更贴合自身 gate。

### aipoch/open-science（Apache-2.0，约 5k stars）

- 本地优先图形工作台，三平台，31 条 CI。与本仓库阶段不同（数据分析工作台 vs 投稿门禁）。
- 不移植：Electron 桌面栈。可借鉴其「可复现工件」意识——本仓库已有 `artifact_store`。

### Orchestra-Research/AI-Research-SKILLs（MIT，约 13k stars）

- 98 个 ML 工程技能，面向模型训练/微调/部署；与本仓库的论文证据链重叠极小。
- 不移植。

### 本仓库现状（交叉核验，避免重复造轮子）

- `external_adapters.py`：**只检查**适配器的 installed/configured/functional 等级，healthcheck 是 HTTP ping 而非真实检索；能力列在 `skills/adapters.yaml`（Zotero、CNKI、Exa、Parallel、Firecrawl、Paperclip、PubMed、OpenAlex、Hugging Face 等）。
- `library.py`：只索引本地 `refs.bib` + `notes/`，支持 keyword / semantic(Ollama bge-m3) / hybrid；无联网检索。
- `doi_lookup.py`：Crossref + DataCite 双源，返回 `found / http_ok / detail / evidence`。
- `citation_guard.py`：`--verify-online` 对每个有 DOI 的条目做联网核验并写入带证据体的 ledger；无 DOI 条目会报 `unverified-entry`（当前无反查手段）。
- `mcp_gates.py`：只读 MCP server，暴露 `brief/readiness/worklist/argument_audit/e2e_check/doctor`，零新依赖，每个工具调用与 CLI 相同的函数。README 第 647 行起有配置示例（路径为作者本机，需按使用者环境调整）。
- `new_module.py`：`ccfa new-module create` 一次接好模块、wrapper、测试存根、dispatch、CI、README 等六份清单，降低新增 CLI 的摩擦。

**结论**：A（联网检索）与 C（无 DOI 反查）是真空位；B（MCP 对接）代码已具备，缺的是面向 ARC 的示例；其余方向不做。

## 3. 实施方案

### A. `ccfa literature-search`（新 CLI）

目标：按标题/关键词检索 OpenAlex、arXiv、Semantic Scholar，输出结构化候选引用（ BibTeX 字段 + 来源 + URL + 证据体），可写入本地 library 待人工确认。

- 用 `ccfa new-module create` 生成骨架，复用 `cli.py` 的 `Problem`/`emit`/退出码契约。
- 三个 provider 各自一个纯函数：`search(query, fetch) -> list[Candidate]`，`fetch` 可注入，缺省 `urllib.request`（与 `doi_lookup` 一致，无新依赖）。
- 默认离线：不带 `--provider`/`--query` 或带 `--dry-run` 时只校验参数、不联网；真实请求需显式 `--online`。
- fail-closed：HTTP 非 2xx、JSON 非法、字段缺失 → problem；不把「0 结果」当错误（那是合法答案），但空结果给 advisory。
- 输出写到 stdout（JSON），`--write-bib <path>` 时才落库，且追加写、带 `retrieved_at` 与来源；绝不覆盖 `refs.bib`。
- 不进 `readiness` 的 gate 列表：它是证据收集工具，不是判定工具。
- 测试：每个 provider 用注入的假 `fetch`（成功 / HTTP 错误 / 坏 JSON / 空结果 / 字段不全），验证 problem code 与证据体；验证缺省不联网；验证 `--write-bib` 不覆盖已有条目。

### B. 生成型前端对接（文档，不改代码）

- 新增 `docs/integrating-generating-agents.md`：讲清楚分工（它们生成、本仓库把关）、MCP 配置示例（用相对路径 / 环境变量 Instead of 作者本机绝对路径）、ARC/EvoScientist 的调用流程、以及「agent 拿到的答案与人跑 CLI 相同」这一契约。
- 明确只读边界：没有 write/advance/acquit 工具。

### C. citation_guard 无 DOI 标题反查（扩展现有 CLI）

- 新增 `--verify-titles-online`：对 ledger 中 `unverified-entry` 且 bib 条目无 DOI 的键，按 `title` 走 S2 / OpenAlex 标题匹配（复用 A 的 provider 函数，避免重复实现）。
- 复用 `doi_lookup` 的证据契约：`found / http_ok / detail / evidence`；命中后写 `verified` 记录，证据体含来源 URL + 返回标题 + `retrieved_at`；标题不匹配（相似度低于阈值）记 problem 而非 verified。
- 不自动接受低置信匹配：阈值不可达时保持 `unverified-entry`，只加 advisory 提示候选。
- 测试：注入假 fetch 覆盖「标题精确匹配 / 近似但低于阈值 / HTTP 错误 / 多候选歧义」；验证 fail-closed 与证据体绑定；验证不传 flag 时行为与今天逐字一致。

## 4. 交付与验收

- 每项实现后跑相关测试；全部完成后跑全量 `python -m unittest discover -s tools/tests -t tools`（当前基线 2480 tests, OK, skipped=8）。
- 追加 `docs/workflow-change-log.jsonl` 一条，files 覆盖所有改动。
- `ccfa doctor` 保持 0 problems；`change-log check --base HEAD` 通过。
- 提交并推送（延续 `a693ed9` 之后）。

## 5. 不做的事

- 不引入 Poetry / node / Electron / LangGraph 等异质依赖栈。
- 不改 `argument_audit` / `cross_review` / `readiness` 的判定语义。
- 不拷贝任何外部仓库的源码文件；不把外部 LICENSE 带进本仓库。
- 不做生成型流水线（那是 ARC/EvoScientist 的领域，本仓库是验证层）。

## 6. 后续加固（第二轮，2026-11-17）

整合完成后再次审计，补了三处短板：

1. **arXiv ID 核验**（`tools/ccfa/arxiv_lookup.py` + `bib.py` 暴露 `eprint`）：无 DOI 条目若有 `eprint`，先用 arXiv Atom API 按 ID 核验，再回退到标题反查。按 ID 匹配比模糊标题命中更可靠，且沿用 `doi_lookup` 的证据契约（响应体 sha256 + `retrieved_at` + 匹配标题）。失败一律 fail-closed：HTTP 错误 / Atom 解析失败 / entry 的 ID 不匹配 / 标题不匹配都不写 verified。
2. **传输韧性**（`tools/ccfa/literature_transport.py`）：给文献检索默认 fetch 加指数退避 + 抖动、`Retry-After` 处理（>300s 直接放弃）、连续 429 断路器（CLOSED/OPEN/HALF_OPEN）、URL 密钥脱敏、polite-pool `mailto`。全 stdlib；状态在实例上而非模块全局；注入的 fetch 完全绕过传输层，测试仍全离线。
3. **git 身份**：仓库级配置 `WorkBuddy <workbuddy@localhost>`，后续提交不再需要临时 `-c`。

### 第三轮：闭合证据体反伪造边界（2026-11-18）

上一轮延后的缺口已闭合。原状态是「`body_sha256` 只证明发生过 fetch，响应体不落盘无法离线重算」。现在：

- `LedgerEvidence` 新增 `body_b64`：三个 lookup（DOI / arXiv / 标题反查）成功时把原始响应字节 base64 归档进台账；`save_ledger` 对旧记录省略该字段以保持字节兼容。
- `citation_ledger.verify_evidence_body()` 离线重算 sha256 并做标题绑定（响应体文本须含 `matched_title`），返回 `verified / body-absent / body-invalid / recompute-mismatch / title-unbound`。
- `citation_guard` 校验循环据此分流：手写伪台账（哈希对不上、体被替换、内容绑定失败）报阻塞 problem `evidence-body-tampered`；旧台账无 body 时只给非阻塞 advisory `evidence-body-not-stored`，不破坏既有语料。

**能力边界（如实说明）**：这是「内部一致性 + 内容绑定 + 离线可重算」，不是密码学防伪造。有人若整份伪造响应体并重算哈希仍可通过，但响应体已归档可人工审计，且伪造门槛从「编一个哈希串」提高到「构造内容自洽的整份假响应」。

- 测试：`TestEvidenceBodyVerification`（7 项，含哈希篡改 / base64 非法 / 异文绑定 / 往返 / 旧台账兼容）、`TestEvidenceBodyGate`（5 项，含手写伪哈希阻塞 / 异文阻塞 / 旧台账降级 / 在线写入持久化），以及标题与 arXiv 路径的 body_b64 断言。
