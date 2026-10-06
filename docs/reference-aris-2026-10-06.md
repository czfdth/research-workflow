# 参考审计：ARIS（Modex-MH-Agent 的上游）

日期：2026-10-06
对象：`wanshuiyin/Auto-claude-code-research-in-sleep`（ARIS，MIT）
方法：`gh api` 读仓库元数据 + `git clone --depth 1` 后直接读源码

## 一、为什么换成这个参考对象

上一份审计（`docs/reference-modex-mh-agent-2026-10-06.md`）读的是本机安装的
Modex-MH-Agent，它的技能是密文，只能推断。WorkBuddy 的分析指出了上游，
我自己在二进制里核对了它的关键论断：

| 论断 | 我自己的验证 | 结果 |
| --- | --- | --- |
| 派生自 `Auto-claude-code-research-in-sleep` | `rg -a` 二进制 | 命中 14 个文件 |
| 打包路径残留 `_tmp_backend` | `rg -a` 二进制 | 命中 13 个文件 |
| `_check_step_companions` / `_min_size_for` / `_required_companions_for` | `rg -a` 二进制 | 各命中 1 个文件 |
| `_should_skip_step_by_assets` / `_generate_claude_md` | `rg -a` 二进制 | 各命中 1 个文件 |
| `mhcoding.xyz` / `aris.db` | `rg -a` 二进制 | 各命中 1 个文件 |

注意：符号存在只证明这些名字在，不证明 WorkBuddy 对语义的推断都对。
所以真正值得读的是上游本身，它是 MIT、Markdown 明文，可以直接读。

仓库元数据（`gh api`）：17.0k stars、MIT、`pushed_at 2026-10-05`，
自述为 "Lightweight Markdown-only skills for autonomous ML research:
cross-model review loops, idea discovery, and experiment automation.
No framework, no lock-in"。

## 二、ARIS 的结构（实读）

```text
AGENT_GUIDE.md          18 KB，两个控制轴 + 工作流索引 + 跨模型协议
README_CN.md           195 KB
skills/                110+ 个明文 SKILL.md
mcp-servers/           claude-review, gemini-review, codex-exec, antigravity-exec,
                       grok-exec, manual-review, minimax-chat, llm-chat, feishu-bridge
skills/shared-references/  29 份契约文档（assurance-contract, reviewer-independence,
                       review-tracing, resumable-runs, experiment-integrity ...）
tools/, commands/, templates/, tests/
```

和 Modex 的关系：Modex 把 ARIS 的技能加密、套 Electron 壳、锁自家 API 网关；
ARIS 本体是明文 Markdown + 可选的 MCP 评审服务。

## 三、它比我们强的地方（按价值排序）

### 1. 两个独立控制轴：`effort` × `assurance`（本次采纳）

`effort: lite | balanced | max | beast` 管深度与预算；
`assurance: draft | submission` 管审计是否承载结论。

它给出的采纳理由很具体：早期把两者混在一起，结果 `effort: beast` 的论文
因为内容探测器没命中而静默跳过了三项投稿审计。这和我们踩过的
「present 等于 pass」是同一类事故。

`assurance: submission` 的语义是硬约束：

- 所有强制审计必须给出结论，禁止静默跳过；
- 缺前置条件的审计判 `BLOCKED`（阻塞），而不是当作「不适用」；
- 校验器不通过就拒绝生成 Final Report。

### 2. 六值结论状态机

`PASS / WARN / FAIL / NOT_APPLICABLE / BLOCKED / ERROR`，关键在于区分：

- `NOT_APPLICABLE`：探测器为负，但审计阶段跑过并留下产物（「查过，确实没有」）；
- `BLOCKED`：本该审计却缺前置条件（例如论文写了 89.2% 却没有 `results/`），阻塞；
- `ERROR`：审计本身失败，投稿档视为阻塞。

### 3. 审计产物 schema：把「审计过什么」变成可复算的事实

每项强制审计写 JSON，至少含 `audited_input_hashes`（被审文件的 SHA256）、
`trace_path`、`thread_id`、`executor_model` / `reviewer_model` 与各自 family、
`review_independence`、`acceptance_status`。校验器重新哈希这些输入，
不一致就标 `STALE` 并退出 1；`same-family` 的结论只能是 `provisional`，
永远不能对外说 `submission-ready: yes`。

还有一条硬规则：`deterministic` 只允许用在机器真能判定的审计上
（编译、schema、哈希、测试），四项语义审计（proof / claims / citations / attack）
只认 `cross-family`。

### 4. 分工纪律：「子审计只报告，父流程决定阻塞」

子审计永远出结论、从不自己阻塞；是否阻塞只在 `assurance` + 校验器这一处决定。
这避免了每个子工具各自发明阻塞语义。

### 5. 禁止自审自己的修复

`integrity-forensics` 里明写 "The One Forbidden Loop"：审计发现的问题，
不能由执行者改完就自评通过，必须有人类 sign-off。这与我们「人工复核」的立场一致，
但他们把它写成了禁止条款。

### 6. 其他值得记的

- `resumable-runs`：`— resume <run_id>`，长流程可断点续跑；
- `manual-review` MCP：给人用的评审界面，是把「人工复核」做成工具的样例；
- `reviewer-routing.md`（50 KB）：按难度路由评审者，`xhigh` / `ultra` 分层。

## 四、与我们工作流的对照

| 维度 | ARIS | 我们 | 判定 |
| --- | --- | --- | --- |
| 深度 vs 严格 | 两个独立轴 | 单一 `profile` | 本次采纳 |
| 结论词表 | 六值，含 BLOCKED / NOT_APPLICABLE | readiness 维度 + problems 退出码 | 我们表达力够，但没有统一词表 |
| 审计输入绑定 | `audited_input_hashes` + STALE 重算 | 证据变更作废 stale 评审 | 等价 |
| 跨族要求 | `cross-family` 才算 accepted | cross_review 同族需 override 留痕 | 等价 |
| 子工具阻塞权 | 只报告，父流程决定 | 同样的原则（advisory vs problem） | 等价 |
| 人工复核 | `manual-review` MCP + 禁止自审条款 | 台账 + checkpoint + 失败演练 | 我们台账更厚，他们交互更好 |
| 规模 | 110+ skills，明文 | 60+ CLI，可测 | 各有侧重 |

## 五、本次落地

`ccfa.yaml` 新增可选键 `workflow.assurance`：

```yaml
workflow:
  profile: minimal      # 深度/预算（不变）
  assurance: submission # 审计严格度（新增，可选）
```

- 不写：行为与之前完全一致（`high-assurance` 默认 `submission`，其余默认 `draft`）；
- `assurance: submission`：不管 profile 多轻，审计链升到 `high-assurance`，
  强制证据台账与人工复核 checkpoint；
- `assurance: draft`：给高保障项目一个显式降级出口（探索期用），
  profile 仍然标 `high-assurance`，避免假装审计已通过；
- 取值非法直接报错（fail closed），不静默按默认值跑。

`readiness` 报告新增 `assurance` 与 `audit_profile` 两个字段，
Markdown 头部同步显示，便于一眼看出「这次到底有没有跑审计」。

## 六、没有采纳的

1. 六值结论词表与审计 JSON schema：要迁移所有 gate 的输出格式，
   收益（外部可复算）我们已用 `readiness` + 哈希清单覆盖大半，先不动。
2. `mcp-servers/` 那套评审服务：我们已有 `cross_review` + 本地第二 family provider，
   再铺一层 MCP 只会增加维护面。
3. 110 个技能的目录规模：他们的定位是「任何 agent 都能用的 Markdown 技能包」，
   我们的定位是可被测试钉住的工具链，规模和形态本来就不该一样。

## 七、下一步候选

1. 把 `BLOCKED` 语义写进 readiness 维度：区分「没有这项审计」与「该审却缺前置」。
2. `resume <run_id>` 式的断点续跑，落到 `experiment-loop` 与 `queue`。
3. 把 `audited_input_hashes` 的复算扩到人工台账（proof-audit / citation-support），
   让「人在什么输入上签的字」可复算。
4. 给「证据存在」加最小体积门槛（对应 Modex 的 `_min_size_for`）：
   现在 `evidence.items[].present` 只看文件在不在，空壳文件要靠各自的 gate 兜。

## 八、第十切片：投稿后产出的度量硬门（读源码后对齐）

参考快照：`wanshuiyin/Auto-claude-code-research-in-sleep`，本地克隆
`%TEMP%\aris-src`，commit `3b19a22`。本切片只读了与本轮相关的文件：

| 读到的文件 | 读到的设计 | 我们的对应实现 |
| --- | --- | --- |
| `skills/paper-poster-html/scripts/run_gates.py` | 五段固定顺序 `preflight → style → asset → measure → polish`；单一 `GATE_REPORT.json`；每段声明 hard/soft（`polish` 默认软，`--strict-polish` 转硬）；默认累积全部问题，`--fail-fast` 是 CI 用的可选项；exit 0/1/2 分别表示通过/硬失败/用法或环境错误 | `tools/ccfa/talk_gates.py` 的 `CANONICAL_ORDER` / `GATE_SEVERITY` / `run_gates`：同样四段顺序、同一份报告、同样的分级与两种模式、同样的退出码语义（`style` 未实现，理由见下） |
| `skills/paper-poster-html/scripts/poster_check.py` | 子命令划分：`measure` / `preflight` / `polish` / `verify-final`；逻辑放在 `_posterly` 包里，CLI 只做 argparse 分发 | 我们保留两个入口：`run`（四段编排）与 `verify-final`（PDF 核对），逻辑全在模块里而不是脚本里 |
| `skills/paper-poster-html/scripts/_posterly/measure.py` | 「唯一决定列是否对齐的硬门」；打印仿真下读 `[data-measure-role]` 几何；输出两个数（列底 spread 与到页脚的 gap）；空列 / 缺页脚 / MathJax 失败一律硬失败 | 采纳「测量出数而不是凭感觉」与「测量失败就是硬失败」；**不采纳** headless Chromium 那条链路（见下） |
| `skills/paper-poster-html/scripts/_posterly/verify_final.py` | 用 `pdfinfo` 核对页数 / 页尺寸（±0.05in，含旋转交换）/ 文件体积；期望画布必须显式给 `--canvas` 或 `--from-html`，**没有默认值**，因为默认猜错比报错更糟 | `verify-final` 同样强制 `--canvas` 或 `--from-plan`；同样三项检查、同样 ±0.05in 容差与旋转交换；引擎优先 `pdfinfo`，缺失时回退 PyMuPDF（仓库已依赖，避免把环境缺口变成稿子失败） |

**为什么不用 headless Chromium 量 spread。** ARIS 量的是它自己那套 HTML
模板的相对几何：卡片列底对齐、卡片到页脚的间距。我们的产物是 Beamer/LaTeX 与
`data/talk-plan.yaml`，没有那套模板，也不该为了对齐一个数而引入浏览器依赖。
因此 `measure` 改成对 plan 的文本做确定性排版测量：读 `format` 里声明的画布
尺寸与字号，用 `figure_spec.text_width`（CJK 感知）算折行与所需高度，对每个
slide 输出 `fill`。两者的共同点正是这套 gate 的价值所在——**给出一个数，并让
它成为硬失败**，而不是「看起来还行」。

**为什么缺 `style`。** ARIS 的 `style_check.py` / `asset_check.py` 是对着它自己
随附的 design token（`templates/tokens/*.json`）做校验。我们本地没有等价体系，
硬造一套 token 只会是脚手架，所以这一轮不写，并在报告里用
`not_implemented_gates: ["style"]` 明说，而不是假装五段都齐了。

**实测**：真用 `pdflatex` 编译一份 3 页 Beamer（`aspectratio=169`，页尺寸
453.543×255.118pt）作为被测对象。健康稿 `run` 得 `overall=pass`、
`verify-final --from-plan --pages 3` 0 problem；把一页加到 25 条要点后
`talk-slide-overflow` 报 `fill 2.24`（需 6.831in / 可用 3.043in）并 exit 1；
`--pages 5` 对 3 页 PDF 报 `talk-pdf-page-count`。

过程中还修掉一个自己写出来的假阳性：`asset` 一开始用「文件 < 1024 字节就当空图」
判断，结果把一张只有 370 字节、但完全合法的纯色 PNG 判成空图。改成读图片头拿真实
像素（PNG IHDR / JPEG SOF / GIF 逻辑屏），只对「字节不是已知图片格式」「像素边
小于 64」「真·空文件」报硬失败，矢量图（SVG/PDF）跳过像素检查。

**仍未对齐**：`slides` / `slides-polish` / `poster-html` 的**生成器**（Beamer/PPTX
模板、逐页视觉打磨、HTML 海报模板）没有实现，本轮补的是它们的测量与验收那半。

## 九、第十一切片：Beamer 生成器（读源码后对齐）

同一次读取里还看了 `skills/paper-slides/SKILL.md`（22.9KB）。它给出的产出契约是：
`slides/main.tex`（beamer，`aspectratio=169`，venue 配色，每帧 `\note{}`）、
`slides/main.pdf`、`slides/speaker_notes.md`、`slides/main.pptx`、
`slides/SLIDES_STATE.json`；配色表固定五种 venue；字号下限 title ≥28pt、
body ≥20pt、footnote ≥14pt；一页一消息、≤6 行、≤8 词；不放相关工作总结页。

据此实现 `tools/ccfa/talk_deck.py`（21 项测试）：

| 契约 | 实现 |
| --- | --- |
| beamer + venue 配色 | 五种 venue 配色表照抄；未知 venue 回退 GENERIC 并在 stderr 说明，不静默 |
| 每页一帧 + `\note{}` | 标题帧 + 每 slide 一帧 + 致谢帧；`\note{}` 取 `speaker_notes` |
| 独立 speaker notes | `speaker_notes.md`，逐页标题 + 备注 + 要点 |
| 状态文件 | `SLIDES_STATE.json`：venue / aspect / engine / slide_count / frame_count / 声明字号 / 图件；**不带时间戳**，因为它同时是确定性产物 |
| 图件 | 从 `figures/manifest.yaml` 解析、复制进 `slides/figures/`（ARIS 用符号链接，Windows 需要权限） |
| CJK | 自动检测全角字符 → `xelatex` + `\usepackage{ctex}`，并写进状态 |
| PPTX | **未实现**：本地没有 python-pptx；状态文件里写 `not_implemented: ["pptx"]` |

**一处必要的偏离。** ARIS 的字号下限（28pt/20pt）是按 13.33in 画布说的，而
Beamer 的 16:9 页只有 16cm 宽。若照抄字号或按比例缩字号，`talk_gates.measure`
量到的字号和投影时实际渲染的字号就变成了两件事，`verify-final --from-plan`
也不可能和 PDF 对上。所以生成的 `main.tex` 用
`\geometry{paperwidth=…,paperheight=…}` 把页面钉到 plan 声明的画布，并直接用
声明的字号。实测编译出来的 PDF 是 959.98×540pt = 13.333×7.5in，与 plan 完全一致。

**实测**：写一份三页中文 talk plan（含 ICML venue 与一张 800×500 的图），
`talk-deck render` → `talk-deck compile`（自动选 xelatex）→
`talk-gates verify-final --from-plan --pages 5` 0 problem；把 PDF 渲染成 PNG
目视检查，中文、标题配色、页脚 `2/5` 都正常。

目视检查还抓出一个测试抓不到的问题：宽画布下 `\includegraphics[width=0.85\textwidth]`
会让图高超出内容区，把正文挤出画面。改成 `width+height+keepaspectratio` 双向约束，
并把图高（按真实像素算）计入 `measure`——那一页的 fill 从 0.23 变成 0.83，现在
量到的就是实际占位。

## 十、第十二切片：版式润色（读源码后对齐）

读了 `skills/slides-polish/SKILL.md`（28.4KB）。它最值得抄的不是修复清单，而是
两条纪律：

1. **硬范围规则**：只改版式，不改 claims / 数字 / 引用 / URL / 作者 / 单位 / 结果；
   不增删或重排 slide；不动图表与公式内容。
2. **`OUTPUT_VERSIONING`**：原件先快照成 `<stem>_pre_polish.<ext>`，改动只落在
   `<stem>_polished.<ext>`，**原件永不覆盖**。

它还要求逐页 review 前必须把 PDF 渲染成像素（`pdftoppm`/`mutool`，否则"视觉复核
没有像素就是低置信度"），状态放在独立目录（`POLISH_STATE.json`、`INSPECT_*.json`、
`POLISH_CHANGELOG.md`、`traces/slide_NN.json`）。

据此实现 `tools/ccfa/slides_polish.py` + 13 项测试：

| 契约 | 实现 |
| --- | --- |
| 原件快照 + 版本化输出 | `main_pre_polish.tex` 已存在就不覆盖；输出自动 `_polished` → `_v2` → `_v3` |
| 只改版式 | 只做一条机械改写：`\includegraphics[width=...]` 缺高度上限时补 `height=0.6\textheight,keepaspectratio`（就是上一节目视发现的溢出成因） |
| 需要判断的不越权 | 字号低于投影下限、缺 `\geometry` 钉画布、未关 beamer 导航符号 → 写进 findings，**不改写** |
| 逐页像素 | PDF 每页用 `pdftoppm`/`mutool`/`magick` 之一渲染成 PNG，并写 `traces/slide_NN.json` |
| 状态与变更日志 | `.ccfa/slides-polish/<stem>/POLISH_STATE.json` + `POLISH_CHANGELOG.md`（逐行 diff + findings） |

**与 ARIS 的诚实差异**：它的润色是 `gpt-6-astra` 逐页看像素后提出修改建议；本模块
没有模型那一层，所以把它拆成两半——**能机械证明安全**的自动改，需要判断的只报告。
`not_implemented: ["pptx"]` 同样写进状态文件。

**"不改内容"是可验证的，不是承诺。** `slides-polish check` 逐行比对快照与输出：
任何改动必须匹配允许规则，而且**行数不许变**。实测把生成 deck 里的宽高约束手工删掉
（模拟外部工具产出的 deck）→ `run` 补回约束、快照 `main_pre_polish.tex`、输出
`main_polished.tex`、渲染 4 页 PNG、changelog 记下那一行的前后 diff；把输出里的
`Intro` 改成 `Hacked` 后 `check` 报 `slides-polish-unauthorised-change`。

## 十一、第十三切片：HTML 海报（读源码后对齐）

读了 `skills/paper-poster-html/`：`templates/README.md`、三种模板的 `@page` 与
`data-measure-role` 约定、`templates/tokens/*.json` 六个 token pack，以及
`_posterly/verify_final.py` 的 `--from-html` 机制。

模板 README 里最要紧的一句话是：

> TWO places that must stay in sync -- the `@page { size: ... }` rule and the
> poster container's width/height.

以及：每个布局关键元素必须带 `data-measure-role`，**不许删**，因为测量 gate 靠它定位。

据此实现 `tools/ccfa/poster_html.py` + 16 项测试：

| 契约 | 实现 |
| --- | --- |
| 两个尺寸必须同步 | 由**同一次计算**同时生成 `@page { size: W H }` 与 `.poster { width/height }`，构造上不可能漂移；`check` 仍复算并拒绝不一致 |
| 三种版式 | `landscape_4col`(60×36)、`landscape_hero`(60×36)、`portrait_2col`(24×36)，尺寸与栏数照抄 README 表 |
| `data-measure-role` | `poster` / `column` / `footer` 齐备；`check` 缺一即 problem |
| venue token pack | 六个 pack（generic/neurips/icml/iclr/cvpr/acl）逐值照抄；未知 venue 回退 generic 并报告 |
| `--from-html` 反漂移 | `talk_gates verify-final --from-html` 解析海报自己的 `@page`，用它核对 PDF，而不是默认值 |

**实测**：一份中文 ICML 四栏海报 → `build`（60×36in + token pack + 图件）→
`check` 0 problem → `pdf`（Edge 无头打印）→ `verify-final --from-html` 得到
**4320×2592pt = 60×36in**，与海报自己的 `@page` 完全一致；PDF 转 PNG 目视检查，
标题、强调色、四栏卡片与页脚都正常。

**仍未对齐**：PPTX 导出（本地无 python-pptx）；以及 ARIS 用 headless Chromium
打印仿真量出来的「列底对齐 / 到页脚间距 / 画布填充 95–101%」那套 HTML 测量 gate——
本机没有那条链路，所以我只保证**尺寸与结构正确**，不假装已经量过填充率。
