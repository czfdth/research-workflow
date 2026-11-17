# 让生成型 agent 调用本工作流的门禁

- 日期：2026-11-17

生成型科研 agent（AutoResearchClaw / EvoScientist / ARIS / Codex 等）擅长把 idea 推到论文初稿，但它们**不能自己判定"做完了没有"**——它们的"完成"是流程走完，不是证据齐备。本工作流正好相反：只检查、不生成。两者拼起来才是完整的科研闭环：

```text
生成型 agent（idea → 实验 → 初稿）  ──产出──>  论文仓库
                                                  │
                                          本工作流只读门禁
                                                  │
                                    readiness / worklist / argument_audit
                                                  │
                                          人签字后才推进 stage
```

## 契约：能问，不能改

`ccfa.mcp_gates` 是一个**只读** MCP server（stdio，换行分隔 JSON-RPC 2.0，零新依赖）。它刻意只有六个查询工具：

| 工具 | 回答什么 |
| --- | --- |
| `brief` | 这篇论文的当前阶段、阻塞、下一动作的一页摘要 |
| `readiness` | 六维 readiness、哪些 gate 没过、阻塞原因 |
| `worklist` | 按优先级排序的人工待办（含 packet、要写哪个台账、完成判据） |
| `argument_audit` | proof / citation / figure 三类复核状态 |
| `e2e_check` | 整篇论文的单页快照 |
| `doctor` | 工具链是否健康 |

三条不变量，接入方必须理解：

1. **没有写入工具**。不存在 advance stage、写台账、把复核标成 verified 或落地 patch 的 MCP tool。生成 agent 只能问"gate 怎么说"，不能要求"让 gate 通过"。
2. **答案与人类一致**。每个工具调用的是 CLI 用的同一个函数——agent 读到的 readiness 和研究者自己跑 `ccfa readiness` 逐字相同，不存在"给 agent 看的宽松版本"。
3. **判定权在人**。推进 stage、接受 gate、声明 claim supported 只能由人在论文仓库里签字完成（`docs/autonomy-policy.md`）。

## 启动 server

先装好本仓库的 `tools/.venv`（见 README「从零搭建」），然后：

```bash
export PYTHONPATH="<本仓库绝对路径>/tools"
python -m ccfa.mcp_gates serve        # stdio JSON-RPC，等客户端连接
python -m ccfa.mcp_gates list-tools   # 列出六个工具及其 schema
python -m ccfa.mcp_gates call --tool readiness --arg paper_root=<论文目录>
```

Windows 等价：`scripts/mcp-gates.ps1 serve` / `list-tools` / `call`。

## 接到生成型 agent

### Codex / Claude Code / 通用 MCP 客户端

在客户端的 MCP 配置里注册（把路径换成你本机的实际位置，**不要用别人机器上的绝对路径**）：

```toml
[mcp_servers.ccfa-gates]
command = "/absolute/path/to/research-workflow/tools/.venv/Scripts/python.exe"
args = ["-m", "ccfa.mcp_gates", "serve"]
cwd = "/absolute/path/to/research-workflow"
env = { PYTHONPATH = "/absolute/path/to/research-workflow/tools" }
```

POSIX 上把 `python.exe` 换成 `.venv/bin/python`，`Scripts` 换成 `bin`。

### AutoResearchClaw

ARC 产出 `paper_draft.md` / `paper.tex` / `references.bib` / `verification_report.json` 之后，不要把它自己的 `QUALITY_GATE` pass 当成投稿就绪——那是生成流程的内部检查，不是本工作流的证据门禁。正确接法：

1. ARC 的 `deliverables/` 作为论文仓库的 `manuscript/` 与 `data/` 输入；
2. 用本工作流的 `ccfa bibliography` / `library` 把 ARC 的 BibTeX 纳入共享库；
3. 通过 MCP 调 `readiness` 和 `argument_audit`，把返回的问题交给 ARC 作为下一轮 refine 的输入（ARC 的 REFINE 循环正好吃这种反馈）；
4. 只有本工作流 `ready=true` 且人工签字完成，才算可投稿。

ARC 的 `VerifiedRegistry` 保证论文数字来自真实实验——这与本工作流的 `trace-claims` 是同一理念的两种实现，两者可以叠加：**ARC 在生成时防伪造，本工作流在投稿前复核**。

### EvoScientist / ARIS

这两者的 `verify` / cross-model review 是流程内的质量环节，同样不能替代本工作流的独立门禁。接法同上：让它们的 verify 阶段通过 MCP 读取本工作流的 `readiness`，把阻塞项当作下一轮迭代目标，而不是自己判断"通过"。

## 推荐的闭环调用

生成 agent 每完成一轮，按这个顺序问：

```text
doctor      → 工具链健康吗？（不健康先修环境，别急着判论文）
readiness   → 现在 ready 吗？阻塞是什么？
worklist    → 下一件该做的事是什么？（人做还是 agent 补证据）
argument_audit → proof/citation/figure 三类复核到位了吗？
```

`worklist` 的每条都带"完成判据"，且判据逐字取自台账校验器真正要求的字段。生成 agent 可以用它来知道"还差哪些证据"，但**不能代替人签字**。

## 不做什么

- 不通过 MCP 修改论文、bib、台账或 stage——server 里根本没有这类工具。
- 不把生成工具的"流程完成"当"投稿就绪"——只有 `readiness.ready=true` 才算。
- 不给 agent 开第二个宽松的门禁实现——所有答案都走同一套 CLI 函数。
