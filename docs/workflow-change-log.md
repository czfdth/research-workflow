# Workflow Change Log

Generated from `docs/workflow-change-log.jsonl`. Append-only; do not
rewrite historical entries.

## WC-20261005T163310Z-a005adfa58 - Design the workbench UI as a three-pane operations surface on a Modex-MH-Agent style theme.

- timestamp: `2026-10-05T16:33:10Z`
- status: `complete`
- author: `codex`
- reason: 用户要求参考 Modex-MH-Agent 设计工作台 UI：原界面把项目列表、阶段标签和结果表放在同一视觉层级，坏项目与好项目难以区分，YAML 报错还会溢出到标题区。
- files:
  - `app/ccfa_gui/settings_dialog.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
- tests:
  - `ruff check app`
  - `unittest discover -s app/tests -t app (205 tests)`
- notes: papers/ 未改动；未触碰工作区中其他未提交文件。

## WC-20261005T163719Z-cc4d566f97 - Fix app tests that broke on GitHub runners and make the workflow probe verify its directory

- timestamp: `2026-10-05T16:37:19Z`
- status: `complete`
- author: `codex`
- reason: App E2E tests scaffolded projects from the host ccf-latex-templates library, which does not exist on a clean runner, and WorkflowClient.probe() reported a bogus directory as reachable because it never checked tools/ccfa.
- files:
  - `app/ccfa_core/workflow.py`
  - `app/tests/__init__.py`
- tests:
  - `app.tests.test_chat_e2e`
  - `app.tests.test_tools_bridge`
  - `app.tests.test_workbench_e2e`
  - `app.tests.test_workflow`

## WC-20261005T164056Z-234290264d - Normalize temp paths before comparing in the chat E2E test

- timestamp: `2026-10-05T16:40:56Z`
- status: `complete`
- author: `codex`
- reason: The GitHub Windows runner exposes 8.3 short names (RUNNER~1), so the assertion compared a short path against the canonical long path and failed only on CI.
- files:
  - `app/tests/test_chat_e2e.py`
- tests:
  - `app.tests.test_chat_e2e`

## WC-20261005T164251Z-c08422da28 - Adopt Modex-MH-Agent's checkpoint shape: expand each pending human ledger into a question with an explicit answer location.

- timestamp: `2026-10-05T16:42:51Z`
- status: `complete`
- author: `codex`
- reason: 参考 Modex-MH-Agent 工作流设计：他们把人工决定建模成 checkpoint（类型/展示数据/回复）。我们的 readiness 只输出 pending key 列表，人看不出到底要被问什么、答案写哪里。
- files:
  - `docs/reference-modex-mh-agent-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `ruff check tools/ccfa/readiness.py tools/tests/test_readiness.py`
  - `tools.tests.test_dashboard + test_docs_consistency (53 tests)`
  - `tools.tests.test_readiness (33 tests)`
- notes: worktree 缺 tools/.venv，test_scripts 在本目录跑不动；已在主仓库验证 tests.test_scripts 116 项通过。

## WC-20261005T164518Z-207ae33734 - Add portable CLI entry, deterministic ARA extraction, and worktree drift audit.

- timestamp: `2026-10-05T16:45:18Z`
- status: `complete`
- author: `codex`
- reason: Address the portability, automatic semantic-extraction, and uncommitted-worktree drift gaps identified in the live comparison.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-guide.md`
  - `pyproject.toml`
  - `scripts/ara-extract.ps1`
  - `scripts/worktree-audit.ps1`
  - `tools/ccfa/ara_extract.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/worktree_audit.py`
  - `tools/tests/test_ara_extract.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_packaging.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_worktree_audit.py`
- tests:
  - `tools.tests.test_ara_extract`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_packaging`
  - `tools.tests.test_scripts`
  - `tools.tests.test_worktree_audit`

## WC-20261005T164728Z-0a75308587 - Publish fake-pass detection notes and the P0/P1/P2 deficiency checklist.

- timestamp: `2026-10-05T16:47:28Z`
- status: `complete`
- author: `codex`
- reason: Keep the evidence-first moat visible and separate code-resolved items from human or external blockers.
- files:
  - `docs/fake-pass-detection.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
- tests:
  - `tools.tests.test_change_log`

## WC-20261005T165038Z-048c83d06d - Let the public mirror drop the private workflow change-log gate

- timestamp: `2026-10-05T16:50:38Z`
- status: `complete`
- author: `codex`
- reason: The mirror diff is not the private commit diff, so the change-log gate cannot be satisfied there; publish-public.ps1 now removes named workflow steps on the mirror via config.
- files:
  - `scripts/publish-public.ps1`
- tests:
  - `tools.tests.test_scripts`

## WC-20261005T165038Z-c0f50383ce - Make host-only tool end-to-end tests skip on a clean CI runner

- timestamp: `2026-10-05T16:50:38Z`
- status: `complete`
- author: `codex`
- reason: The venue derivation and compile suites run against the host ccf-latex-templates library and MiKTeX, neither of which exists on a GitHub runner or the public mirror. Skipping with an explicit reason keeps the full-suite CI job honest instead of red. Also resolve paths before comparing in the cross-review argv test so 8.3 short names do not fail it.
- files:
  - `tools/tests/__init__.py`
  - `tools/tests/test_compile.py`
  - `tools/tests/test_cross_review.py`
  - `tools/tests/test_derivation_e2e.py`
  - `tools/tests/test_e2e.py`
  - `tools/tests/test_evidence_integrity_e2e.py`
  - `tools/tests/test_productization_e2e.py`
  - `tools/tests/test_venues.py`
  - `tools/tests/test_workflow_e2e.py`
- tests:
  - `tools.tests.test_compile`
  - `tools.tests.test_cross_review`
  - `tools.tests.test_derivation_e2e`
  - `tools.tests.test_e2e`
  - `tools.tests.test_evidence_integrity_e2e`
  - `tools.tests.test_productization_e2e`
  - `tools.tests.test_venues`
  - `tools.tests.test_workflow_e2e`

## WC-20261005T165530Z-89b92885fa - Add budgeted pilot execution and periodic upstream reference audit

- timestamp: `2026-10-05T16:55:30Z`
- status: `complete`
- author: `codex`
- reason: Close the remaining mechanically addressable comparison gaps: the experiment loop now hands a declared pilot to the budgeted executor, and pinned source-audit references are checked monthly instead of relying on a prose promise.
- files:
  - `.github/workflows/reference-audit.yml`
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/reference-drift-2026-10-06.md`
  - `docs/reference-registry.yaml`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/reference-audit.ps1`
  - `tools/ccfa/experiment_loop.py`
  - `tools/ccfa/reference_audit.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_experiment_loop.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_reference_audit.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_experiment_loop`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_reference_audit`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T165648Z-8cf3d9d75a - Skip the private change-log gate assertion on the public mirror

- timestamp: `2026-10-05T16:56:48Z`
- status: `complete`
- author: `codex`
- reason: The mirror drops the workflow change-log step because its diff is not the private commit diff, so the fail-closed assertion is private-only. A .public-mirror marker makes the test skip there while it still runs in the private repository.
- files:
  - `automation/public-docs/PUBLIC-MIRROR.md`
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T165734Z-12b19b01d3 - Split audit strictness from depth: add an optional workflow.assurance axis (draft | submission) to ccfa.yaml.

- timestamp: `2026-10-05T16:57:34Z`
- status: `complete`
- author: `codex`
- reason: 参考上游 ARIS 的 effort x assurance 设计：把深度和审计严格度混在一个 profile 里，会让高预算的论文在探测器未命中时静默跳过投稿审计。这也是我们踩过的 present=pass 同类事故。
- files:
  - `docs/reference-aris-2026-10-06.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_dashboard + test_docs_consistency (61 tests)`
  - `tools.tests.test_readiness (41 tests)`
- notes: 默认行为不变：不写 assurance 时与之前完全一致；high-assurance 默认 submission。workflow-guide 段落待并发编辑落地后再补。

## WC-20261005T170010Z-cea660be07 - Normalize README workflow-row line endings

- timestamp: `2026-10-05T17:00:10Z`
- status: `complete`
- author: `codex`
- reason: Remove CRLF trailing whitespace flagged by git diff --check on the newly added workflow rows.
- files:
  - `README.md`
- tests:
  - `git diff --check`

## WC-20261005T170326Z-ae6a6b566f - Add a verifiable .skillpack format (sha256 manifest, deterministic zip, optional AES-256-GCM) after reviewing Modex-MH-Agent's encrypted skill pack.

- timestamp: `2026-10-05T17:03:26Z`
- status: `complete`
- author: `codex`
- reason: 用户要求参考他的加密技能包。实测其 283 个 .enc 用 AES-256-GCM + zlib 字典伪装、密钥服务端下发并绑定机器指纹：能挡住读提示词，但目录名/模板/脚本名全明文，骨架照样可见，且离线不可用、换硬件即失效、收到包的一方无法校验。抄可校验那一半，丢掉伪装与绑定。
- files:
  - `README.md`
  - `docs/reference-modex-mh-agent-2026-10-06.md`
  - `docs/skillpack-format.md`
  - `scripts/skillpack.ps1`
  - `tools/ccfa/skillpack.py`
  - `tools/requirements.txt`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_skillpack.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_skillpack (12 tests, including the encrypted round-trip)`
- notes: 实测打包 ccf-common（16 文件）并在明文与加密两种模式下 verify 通过；加密包无口令返回 skillpack-locked。

## WC-20261005T170408Z-0990e86d3a - Install the public venue template library and MiKTeX in CI

- timestamp: `2026-10-05T17:04:08Z`
- status: `complete`
- author: `codex`
- reason: The derivation and compile end-to-end suites were skipping on runners because the host ccf-latex-templates library and pdflatex were absent. Both are publicly installable (mikubaka88/CCFA-Skills, MiKTeX), so the tools job now installs them with continue-on-error; a failed install degrades to the existing explicit skips instead of a red job.
- files:
  - `.github/workflows/tests.yml`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T170719Z-db032c0d3b - Add pinned container reproduction receipts

- timestamp: `2026-10-05T17:07:19Z`
- status: `complete`
- author: `codex`
- reason: Close the second-environment reproduction gap with a deterministic, network-disabled Docker runner and make repro-env validate the receipt instead of accepting prose.
- files:
  - `.github/workflows/repro-smoke.yml`
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/repro-container.ps1`
  - `tools/ccfa/repro_container.py`
  - `tools/ccfa/repro_env.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_repro_container.py`
  - `tools/tests/test_repro_env.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_repro_container`
  - `tools.tests.test_repro_env`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T170947Z-5be2220993 - Expose gate-driven human checkpoints in standard readiness

- timestamp: `2026-10-05T17:09:47Z`
- status: `complete`
- author: `codex`
- reason: Standard-profile readiness reported human review as not-required even while proof/citation/figure gates were blocking; it now derives answerable human checkpoints from the actual gate failures without converting them to pass.
- files:
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_readiness`

## WC-20261005T171205Z-d13b046223 - Ignore generated readiness reports when checking git dirtiness

- timestamp: `2026-10-05T17:12:05Z`
- status: `complete`
- author: `codex`
- reason: A readiness run writes its own JSON/Markdown/error files under reviews/, which made the same report claim the paper tree was dirty. The generated report files are now excluded from the dirtiness calculation.
- files:
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_readiness`

## WC-20261005T171238Z-c91e5f2823 - Design the workbench app: five Figma-importable SVG screens generated from the shipped theme tokens, plus a UI spec.

- timestamp: `2026-10-05T17:12:38Z`
- status: `complete`
- author: `codex`
- reason: 用户要求用 Figma 设计 app。本机 Figma 插件已启用但没有配置 Figma MCP server，无法直接读写 Figma 文件；改为产出可导入 Figma 的 SVG 屏幕与设计说明，并把生成器接在同一份 theme.py 令牌上，保证设计稿不会与实现漂移。
- files:
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/01-workbench-empty.svg`
  - `docs/design/exports/02-workbench-project.svg`
  - `docs/design/exports/03-workbench-blocked.svg`
  - `docs/design/exports/04-human-checkpoints.svg`
  - `docs/design/exports/05-settings-dialog.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `tools.tests.test_docs_consistency`
- notes: 04-human-checkpoints 是新提的界面：数据来自 readiness.human_review.checkpoints，尚未在 Qt 里实现。

## WC-20261005T171603Z-0bb348e1bc - Fail closed on an empty citation calibration gold set

- timestamp: `2026-10-05T17:16:03Z`
- status: `complete`
- author: `codex`
- reason: The calibration report treated zero gold rows as a threshold pass, which let missing live evidence masquerade as calibrated citation support.
- files:
  - `tools/ccfa/citation_calibration.py`
  - `tools/tests/test_citation_calibration.py`
- tests:
  - `tools.tests.test_citation_calibration`

## WC-20261005T171719Z-462141832f - Turn cross-review failures into an actionable checkpoint

- timestamp: `2026-10-05T17:17:19Z`
- status: `complete`
- author: `codex`
- reason: Readiness reported cross-review as a bare gate failure; it now names the required action: configure a verifiable gate-capable cross-family provider or complete an external human review with evidence.
- files:
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_readiness`

## WC-20261005T171750Z-7feb7aa905 - Wire the human-checkpoint queue into the workbench: readiness gains --checkpoints-only and the app gets a 待人工复核 button with a status banner.

- timestamp: `2026-10-05T17:17:50Z`
- status: `complete`
- author: `codex`
- reason: 设计稿 04-human-checkpoints 只停留在模拟图。工作台要能回答'现在有哪些事只有人能决定、答案写哪里'，但完整 readiness 会跑 20+ 个 gate，不适合点一下就等。
- files:
  - `app/README.md`
  - `app/ccfa_core/checks.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_checks.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `app unittest discover (207 tests)`
  - `ruff check app tools`
  - `tools.tests.test_readiness (47 tests)`
- notes: 实测：真实 app 点按钮走 ccfa.readiness --checkpoints-only，表格列出 4 条 checkpoint，横幅显示待人工复核。

## WC-20261005T171917Z-ce5fc363e9 - Reject duplicate citation calibration ids

- timestamp: `2026-10-05T17:19:17Z`
- status: `complete`
- author: `codex`
- reason: Duplicate JSONL ids silently overwrote earlier rows, allowing a calibration set to lose samples without any visible failure.
- files:
  - `tools/ccfa/citation_calibration.py`
  - `tools/tests/test_citation_calibration.py`
- tests:
  - `tools.tests.test_citation_calibration`

## WC-20261005T172224Z-b23ba49ddd - Render the human-checkpoint queue as cards with an 打开台账 action instead of table rows.

- timestamp: `2026-10-05T17:22:24Z`
- status: `complete`
- author: `codex`
- reason: 表格形态放不下问题原文与台账说明，也没有直接跳到要写的文件的入口；设计稿 04 本来就是卡片。
- files:
  - `app/README.md`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (208 tests)`
  - `ruff check app`
- notes: 打开台账做了路径约束：解析后的目标必须留在项目目录内，文件不存在时打开最近的已存在祖先目录。

## WC-20261005T173212Z-932a491227 - Align artifact dependency edges with advisory and verified semantics

- timestamp: `2026-10-05T17:32:12Z`
- status: `complete`
- author: `codex`
- reason: Adopt the useful part of open-science's provenance graph without overclaiming: static dependencies stay advisory, verified edges require existing evidence, dangling links fail, and cycles are rejected.
- files:
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/tests/test_research_ledgers.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_research_ledgers`

## WC-20261005T173552Z-2c2b7f6189 - Polish the workbench chrome: shared vector icon set, product mark, empty state, selected-row accent, transparent icon pixmaps.

- timestamp: `2026-10-05T17:35:52Z`
- status: `complete`
- author: `codex`
- reason: 用户要求设计好看的 UI。原来的 chrome 用 Qt 自带图标（蓝色文件夹/刷新箭头），和整套配色不搭；空列表时中栏是一张空表；图标 pixmap 用 QPixmap.fill() 默认填了白色，在主按钮上显示成白方块。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/icons.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/01-workbench-empty.svg`
  - `docs/design/exports/02-workbench-project.svg`
  - `docs/design/exports/03-workbench-blocked.svg`
  - `docs/design/exports/04-human-checkpoints.svg`
  - `docs/design/exports/05-settings-dialog.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (209 tests)`
  - `ruff check app`
- notes: 实测截图确认：工具栏标记+图标、侧栏选中主色条、状态栏圆点、空白状态占位。

## WC-20261005T173725Z-5f27688374 - Require the CI compile list and its modules to move in one commit

- timestamp: `2026-10-05T17:37:25Z`
- status: `complete`
- author: `codex`
- reason: A parallel commit listed tools/ccfa/repro_container.py in tests.yml py_compile before the file existed, which failed CI at Compile core modules. The engineering contract now states the rule and a guard test asserts every listed path exists.
- files:
  - `AGENTS.md`
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T173802Z-5d4940b771 - Record the Figma design file in the workbench UI spec.

- timestamp: `2026-10-05T17:38:02Z`
- status: `complete`
- author: `codex`
- reason: 五屏已通过 Figma MCP 导入为可编辑矢量图层并按列排布；原文说'没有配置 Figma MCP'已经过期，会把读者带偏。
- files:
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `docs consistency (tools.tests.test_docs_consistency)`
- notes: Figma 文件 XpIadzobOUEEPimh31y0TC，导入后 get_screenshot 复核过。

## WC-20261005T174350Z-d5442bc931 - Add system-following dark mode and a width-based chat column collapse to the workbench.

- timestamp: `2026-10-05T17:43:50Z`
- status: `complete`
- author: `codex`
- reason: 深色模式与窄窗口折叠是 UI 设计清单里剩下的两项：界面只有浅色一套，窗口变窄时对话栏死占 420px，把项目详情挤没。
- files:
  - `app/README.md`
  - `app/ccfa_gui/appearance.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/icons.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_theme.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (218 tests)`
  - `ruff check app`
- notes: 深色截图确认色板生效；900px 截图确认对话栏收起；三栏显式最小宽度是折叠能生效的前提。

## WC-20261005T174851Z-9430eff04f - Render chat messages as role bubbles (user/assistant/tool/error/stopped) and add the matching design screen.

- timestamp: `2026-10-05T17:48:51Z`
- status: `complete`
- author: `codex`
- reason: 对话面板之前是纯文本列表项，工具调用和错误只能靠前缀区分，也没出过设计稿。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/theme.py`
  - `app/tests/test_chat_panel.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/06-chat-bubbles.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (220 tests)`
  - `ruff check app`
- notes: 列表项仍保留纯文本，item.text() 消费方不受影响；第一次 sizeHint 在样式生效前算出会截断一行气泡，已改为 adjustSize + 事件循环后再量一次。

## WC-20261005T175017Z-12d710bf90 - Extract candidate claims from PDFs and repository text

- timestamp: `2026-10-05T17:50:17Z`
- status: `complete`
- author: `codex`
- reason: Close the PDF/repo-to-claim gap without allowing model auto-acceptance: candidates carry source hashes, page/line locations and verbatim quotes, are written to claim-candidates.yaml, and are checked before human promotion.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/claim-extract.ps1`
  - `tools/ccfa/claim_extract.py`
  - `tools/ccfa/pdftext.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_claim_extract.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_pdftext.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_claim_extract`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_pdftext`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175113Z-ef2e542c53 - Extract candidate claims from PDFs and repository text

- timestamp: `2026-10-05T17:51:13Z`
- status: `complete`
- author: `codex`
- reason: Close the PDF/repo-to-claim gap without allowing model auto-acceptance: candidates carry source hashes, page/line locations and verbatim quotes, are written to claim-candidates.yaml, and are checked before human promotion.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/claim-extract.ps1`
  - `tools/ccfa/claim_extract.py`
  - `tools/ccfa/pdftext.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_claim_extract.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_pdftext.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_claim_extract`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_pdftext`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175202Z-3335c7e38c - Generate the design exports in both themes: the mockup generator now takes the palette from CCFA_MOCKUP_MODE and writes exports/dark.

- timestamp: `2026-10-05T17:52:02Z`
- status: `complete`
- author: `codex`
- reason: 设计说明里'只有浅色一套'是最后一块没对齐的地方；深色模式已经在 app 里跑起来了，设计稿不跟上就没法用来核对。
- files:
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/02-workbench-project.svg`
  - `docs/design/exports/03-workbench-blocked.svg`
  - `docs/design/exports/04-human-checkpoints.svg`
  - `docs/design/exports/06-chat-bubbles.svg`
  - `docs/design/exports/dark/01-workbench-empty.svg`
  - `docs/design/exports/dark/02-workbench-project.svg`
  - `docs/design/exports/dark/03-workbench-blocked.svg`
  - `docs/design/exports/dark/04-human-checkpoints.svg`
  - `docs/design/exports/dark/05-settings-dialog.svg`
  - `docs/design/exports/dark/06-chat-bubbles.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `generator byte-stability (both modes)`
- notes: 浅色四屏也变了：选中行改用主题里的 row_selected(#eef1ff)，与 app 对齐；同一份生成器对同一棵树是确定性的。

## WC-20261005T175759Z-ad850411eb - Add a budgeted inner-loop parameter optimizer

- timestamp: `2026-10-05T17:57:59Z`
- status: `complete`
- author: `codex`
- reason: Replace the single-pilot executor gap with grid/random trial search, objective extraction, best tracking, patience/budget stops, append-only trial logs and a keep/revert proposal; claims and code remain human-reviewed.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/experiment-optimize.ps1`
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175824Z-6bb05263a8 - Add a budgeted inner-loop parameter optimizer

- timestamp: `2026-10-05T17:58:24Z`
- status: `complete`
- author: `codex`
- reason: Replace the single-pilot executor gap with grid/random trial search, objective extraction, best tracking, patience/budget stops, append-only trial logs and a keep/revert proposal; claims and code remain human-reviewed.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/experiment-optimize.ps1`
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T175903Z-6e9b621bb2 - Render chat bubble bodies as Markdown (lists, code fences in monospace, wrapping code lines).

- timestamp: `2026-10-05T17:59:03Z`
- status: `complete`
- author: `codex`
- reason: 气泡正文之前是纯文本，模型回复里的列表和代码块都成了带标记的散文；代码行还会被 420px 的栏宽裁掉。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/theme.py`
  - `app/tests/test_chat_panel.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/06-chat-bubbles.svg`
  - `docs/design/exports/dark/06-chat-bubbles.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (221 tests)`
  - `ruff check app`
- notes: 气泡改用 QTextBrowser.setMarkdown；代码围栏默认不折行，已逐块关掉 nonBreakableLines，并按文档实际高度反算气泡高度。

## WC-20261005T180305Z-1535278c9d - Add motion to the workbench: 180ms conversation-column slide and 140ms detail-page fade, with an off switch.

- timestamp: `2026-10-05T18:03:05Z`
- status: `complete`
- author: `codex`
- reason: 设计清单里的最后一项：折叠是瞬间跳变，切页也是硬切，空间关系读不出来；同时需要有 reduced-motion 的关闭路径。
- files:
  - `app/README.md`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (222 tests)`
  - `ruff check app`
- notes: 动画只动最大宽度与不透明度，结束回调恢复常态；animations=False / CCFA_NO_ANIM=1 / 窗口未显示时全部即时生效。

## WC-20261005T180645Z-b2db15c4bc - Add sandboxed automatic code mutation and research plan generation

- timestamp: `2026-10-05T18:06:45Z`
- status: `complete`
- author: `codex`
- reason: Implement the remaining autoresearch gap safely: model-generated plans and file replacements are written as candidates, code mutations run only in a disposable sandbox with tests and diffs, and neither claims nor the source repo are auto-accepted or modified.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/autoresearch.ps1`
  - `tools/ccfa/autoresearch.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_autoresearch.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_autoresearch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T180709Z-90a6359694 - Add sandboxed automatic code mutation and research plan generation

- timestamp: `2026-10-05T18:07:09Z`
- status: `complete`
- author: `codex`
- reason: Implement the remaining autoresearch gap safely: model-generated plans and file replacements are written as candidates, code mutations run only in a disposable sandbox with tests and diffs, and neither claims nor the source repo are auto-accepted or modified.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/autoresearch.ps1`
  - `tools/ccfa/autoresearch.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_autoresearch.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_readiness.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_autoresearch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T180937Z-40463a8128 - Give code blocks a mode-aware background and add the narrow/collapsed design screen (07) in both themes.

- timestamp: `2026-10-05T18:09:37Z`
- status: `complete`
- author: `codex`
- reason: 两处尾巴：代码块只有等宽字体没有底色；设计稿没有折叠态，无法核对窄窗口那一屏。
- files:
  - `app/README.md`
  - `app/ccfa_gui/chat_panel.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_chat_panel.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `docs/design/exports/07-narrow-collapsed.svg`
  - `docs/design/exports/dark/07-narrow-collapsed.svg`
  - `docs/design/generate_mockups.py`
- tests:
  - `app unittest discover (223 tests)`
  - `ruff check app`
- notes: Qt 的 markdown 导入器忽略样式表里的块背景，改用 nonBreakableLines 标记识别代码块并直接设置 block 背景；深浅色采样确认 #eef0f3 / #2b2b34 生效。

## WC-20261005T181502Z-728c97291b - Add cross-session task replay and independently installable skills

- timestamp: `2026-10-05T18:15:02Z`
- status: `complete`
- author: `codex`
- reason: Close the remaining orchestration and packaging gaps: long tasks now replay a hash-chained event log from disk, and core capabilities are split into dependency-resolved skill packages that can be verified and installed independently.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/long-task.ps1`
  - `scripts/skill-registry.ps1`
  - `skills/ccfa-autoresearch/SKILL.md`
  - `skills/ccfa-autoresearch/skill.yaml`
  - `skills/ccfa-claims/SKILL.md`
  - `skills/ccfa-claims/skill.yaml`
  - `skills/ccfa-core/SKILL.md`
  - `skills/ccfa-core/skill.yaml`
  - `skills/ccfa-evidence/SKILL.md`
  - `skills/ccfa-evidence/skill.yaml`
  - `skills/ccfa-experiments/SKILL.md`
  - `skills/ccfa-experiments/skill.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/long_task.py`
  - `tools/ccfa/skill_registry.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_long_task.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_long_task`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T181536Z-0606c5a773 - Add cross-session task replay and independently installable skills

- timestamp: `2026-10-05T18:15:36Z`
- status: `complete`
- author: `codex`
- reason: Close the remaining orchestration and packaging gaps: long tasks now replay a hash-chained event log from disk, and core capabilities are split into dependency-resolved skill packages that can be verified and installed independently.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/long-task.ps1`
  - `scripts/skill-registry.ps1`
  - `skills/ccfa-autoresearch/SKILL.md`
  - `skills/ccfa-autoresearch/skill.yaml`
  - `skills/ccfa-claims/SKILL.md`
  - `skills/ccfa-claims/skill.yaml`
  - `skills/ccfa-core/SKILL.md`
  - `skills/ccfa-core/skill.yaml`
  - `skills/ccfa-evidence/SKILL.md`
  - `skills/ccfa-evidence/skill.yaml`
  - `skills/ccfa-experiments/SKILL.md`
  - `skills/ccfa-experiments/skill.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/long_task.py`
  - `tools/ccfa/skill_registry.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_long_task.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_long_task`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T181834Z-f6e3da5ec9 - Bind human proof attestations to the reviewed bytes: proof-audit verified reviews need audited_inputs, and argument-audit gains --stamp.

- timestamp: `2026-10-05T18:18:34Z`
- status: `complete`
- author: `codex`
- reason: 人工复核只记录'谁评过'，不记录'评的是哪一版字节'；改稿之后旧签字仍然有效，这是人工验证链条上最后一个静默失效点。
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/argument_audit.py`
  - `tools/tests/test_argument_audit.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_argument_audit (25 tests)`
  - `tools.tests.test_readiness + test_proof_orchestrator + test_research_ledgers + test_dashboard + test_artifact_badge (95 tests)`
- notes: 新增错误码 proof-review-unbound / proof-review-stale；--stamp 只打印片段，不写文件。

## WC-20261005T182231Z-68d52db630 - Extend the audited_inputs binding to citation-support and figure-support attestations.

- timestamp: `2026-10-05T18:22:31Z`
- status: `complete`
- author: `codex`
- reason: 上一轮只把人工签字绑到了证明文件；引用语义与图表语义两本台账仍然只记'谁评过'，改稿后同样会静默保持有效。
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/argument_audit.py`
  - `tools/tests/test_argument_audit.py`
  - `tools/tests/test_figure_audit.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_argument_audit + test_figure_audit + test_readiness + test_proof_orchestrator (134 tests)`
- notes: 必录文件：引用=记录里的 source_path，图表=manifest 里的 file；新增 citation-support-unbound/-stale 与 figure-support-unbound/-stale。

## WC-20261005T182608Z-cb45d21fd1 - Give every readiness gate a verdict (pass / fail / blocked / error) so missing inputs no longer look like rejected content.

- timestamp: `2026-10-05T18:26:08Z`
- status: `complete`
- author: `codex`
- reason: ARIS 审计里我们还没抄的最后一条：过去 gate 只有 pass/problem，缺前置台账和内容不过显示成一样，人看不出下一步该补输入还是改内容。顺带核实 resume 已经由 tools/ccfa/long_task.py 实现。
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_readiness (61 tests)`
- notes: verdicts 由缺失台账映射（LEDGER_GATE_NAMES）+ gate 自身 status 推导；markdown 里每个 gate 行带 verdict，未执行的 blocked gate 单独列一行。

## WC-20261005T182805Z-4eee662850 - Let the installed workbench discover a workflow checkout instead of requiring manual configuration.

- timestamp: `2026-10-05T18:28:05Z`
- status: `complete`
- author: `codex`
- reason: 给合作者用时最大的摩擦是装完必须自己找仓库并填路径；安装包已经支持把 workflow/ 放在 exe 旁边，客户端却只认显式配置。
- files:
  - `app/README.md`
  - `app/ccfa_core/workflow.py`
  - `app/tests/test_workflow.py`
- tests:
  - `app unittest (tests.test_workflow + test_settings, 33 tests)`
  - `ruff check app`
- notes: 搜索顺序：显式配置/环境变量 → 安装目录 workflow\\ → LOCALAPPDATA Programs → 用户目录两个位置；开发时仓库本身仍优先。捆绑 embeddable Python 的代价写进 README。

## WC-20261005T183936Z-ff72f75d7b - Ship a self-contained workflow runtime for the installer: bundle-workflow.ps1 stages an embeddable CPython + tools sources + pip --target dependencies, and build-workbench.ps1 gains -BundleWorkflow.

- timestamp: `2026-10-05T18:39:36Z`
- status: `complete`
- author: `codex`
- reason: 给合作者用时安装包里只有 app，装完还得自己找并配置工作流目录；venv 不能随包分发（pyvenv.cfg 指向构建机解释器），所以用 embeddable CPython。
- files:
  - `app/README.md`
  - `app/ccfa_core/workflow.py`
  - `app/tests/test_workflow.py`
  - `scripts/build-workbench.ps1`
  - `scripts/bundle-workflow.ps1`
  - `tools/ccfa/repro_package.py`
- tests:
  - `app unittest discover (226 tests)`
  - `real bundle + embedded CLI run: 169.8 MB, 84 modules import, readiness/validate exit 0 from cwd=C:\`
  - `tools.tests.test_repro_package (27 tests)`
  - `tools.tests.test_scripts in the main checkout (136 tests)`
- notes: 实测发现嵌入版 CPython 不含 venv，repro_package 顶层 import 会让 readiness 崩；已改为惰性 import，并在打包脚本里逐模块 import 自检。

## WC-20261005T184206Z-db62f9953f - Add ccfa-workbench.exe --self-check so an installed copy can be smoke-tested without launching the GUI.

- timestamp: `2026-10-05T18:42:06Z`
- status: `complete`
- author: `codex`
- reason: 安装包没法用脚本验证：GUI 一跑就占用界面，看不出冻结后的 app 到底有没有发现自带的工作流运行时。
- files:
  - `app/README.md`
  - `app/ccfa_gui/main.py`
  - `app/tests/test_gui_smoke.py`
- tests:
  - `app unittest discover (227 tests)`
  - `ruff check app`
- notes: self-check 复用窗口同一条发现路径并调用工作流的 probe；输出 JSON 含 probe_ok/probe_detail。

## WC-20261005T184733Z-9a456ec0c5 - Register external P0 skills and support multiple source roots

- timestamp: `2026-10-05T18:47:33Z`
- status: `complete`
- author: `codex`
- reason: Promote already-referenced global CCF skills into the workflow registry without copying their source, and derive content-hash versions for unversioned external skills while keeping missing external sources non-fatal unless strict validation is requested.
- files:
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
  - `tools/ccfa/skill_registry.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T184756Z-5e249ff15e - Register external P0 skills and support multiple source roots

- timestamp: `2026-10-05T18:47:56Z`
- status: `complete`
- author: `codex`
- reason: Promote already-referenced global CCF skills into the workflow registry without copying their source, and derive content-hash versions for unversioned external skills while keeping missing external sources non-fatal unless strict validation is requested.
- files:
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
  - `tools/ccfa/skill_registry.py`
  - `tools/tests/test_skill_registry.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185201Z-74478856dd - Register P1 Nature and Cell methodology skills

- timestamp: `2026-10-05T18:52:01Z`
- status: `complete`
- author: `codex`
- reason: Expand the external-source registry with the selected Nature/Cell skill set now that source roots, content hashes, dependency resolution, packing and installation are in place.
- files:
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185232Z-27436dd029 - Register P1 Nature and Cell methodology skills

- timestamp: `2026-10-05T18:52:32Z`
- status: `complete`
- author: `codex`
- reason: Expand the external-source registry with the selected Nature/Cell skill set now that source roots, content hashes, dependency resolution, packing and installation are in place.
- files:
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185818Z-1b96b722e0 - Add external-service adapter capability checks

- timestamp: `2026-10-05T18:58:18Z`
- status: `complete`
- author: `codex`
- reason: Separate installed skills from configured and functional external services, record only env-var names, and expose adapter probes without reading or printing secrets.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/external-adapters.ps1`
  - `skills/adapters.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/external_adapters.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_external_adapters.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_external_adapters`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T185842Z-29a8ef8bc1 - Add external-service adapter capability checks

- timestamp: `2026-10-05T18:58:42Z`
- status: `complete`
- author: `codex`
- reason: Separate installed skills from configured and functional external services, record only env-var names, and expose adapter probes without reading or printing secrets.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-deficiency-checklist-2026-10-06.md`
  - `docs/workflow-guide.md`
  - `scripts/external-adapters.ps1`
  - `skills/adapters.yaml`
  - `skills/registry.yaml`
  - `tools/ccfa/external_adapters.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_external_adapters.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_external_adapters`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T190205Z-8e86b0dd3f - Add a readiness view to the workbench: a 运行 readiness action that renders the six dimensions, the non-pass gate verdicts and the blocking list in one table.

- timestamp: `2026-10-05T19:02:05Z`
- status: `complete`
- author: `codex`
- reason: 工作台只驱动 validate/milestones/checkpoints 三条命令，而日常循环的核心是 readiness；报告里的维度、gate 结论和阻塞清单此前只能在终端看。
- files:
  - `app/README.md`
  - `app/ccfa_core/checks.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/theme.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_checks.py`
  - `app/tests/test_gui_smoke.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (229 tests)`
  - `ruff check app`
- notes: 表格三段：维度 / 非 pass 的 gate 结论 / 阻塞项；横幅给第一条阻塞与结论计数。

## WC-20261005T190513Z-4b9c885c93 - Register drawio-skill as a local visual-composition capability

- timestamp: `2026-10-05T19:05:13Z`
- status: `complete`
- author: `codex`
- reason: The registry had CCF and Nature figure skills but no editable diagram authoring; drawio-skill produces editable .drawio architecture/UML/BPMN diagrams on Windows with no API key, so it is registered as a codex-root capability skill with a ccf-common dependency.
- files:
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T190625Z-dcd0351ab5 - Register drawio-skill as a local visual-composition capability

- timestamp: `2026-10-05T19:06:25Z`
- status: `complete`
- author: `codex`
- reason: The registry had CCF and Nature figure skills but no editable diagram authoring; drawio-skill produces editable .drawio architecture/UML/BPMN diagrams on Windows with no API key, so it is registered as a codex-root capability skill with a ccf-common dependency.
- files:
  - `docs/workflow-guide.md`
  - `skills/registry.yaml`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
  - `tools.tests.test_skill_registry`

## WC-20261005T190724Z-2f02f72ec5 - Show the stage gate criterion in the workbench project panel, sourced from the workflow gate definition.

- timestamp: `2026-10-05T19:07:24Z`
- status: `complete`
- author: `codex`
- reason: The panel showed the gate state badge but never what the gate requires; the criterion was only reachable by running ccfa.stages in a terminal.
- files:
  - `app/ccfa_core/projects.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_projects.py`
- tests:
  - `app unittest discover (231 tests)`
  - `ruff check app`
- notes: Decorative lookup: an unreadable gate yields an empty hint instead of blocking the project from loading.

## WC-20261005T191403Z-8e81189b54 - Drive stage advance and rollback from the workbench, and wrap the action row instead of eliding its labels.

- timestamp: `2026-10-05T19:14:03Z`
- status: `complete`
- author: `codex`
- reason: Stage transitions were CLI-only (scripts/state.ps1), so the panel could show the stage but not move it; and adding a fifth action squeezed the row until Qt elided button text even at 1280px.
- files:
  - `app/README.md`
  - `app/ccfa_core/state.py`
  - `app/ccfa_gui/flow_layout.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/stage_dialog.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_state.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
- tests:
  - `app unittest discover (246 tests)`
  - `ruff check app`
- notes: The transition dialog only offers targets from the workflow stage table, requires a reason, and calls ccfa.state --confirm; the window then re-scans papers/ so the badges show what the workflow wrote. The action row uses a small FlowLayout so narrow panes wrap to a second line.

## WC-20261005T192704Z-8bb03b2cbc - Show each paper git/GitHub collaboration state in the project list, via a new ccfa.readiness --collaboration-only report.

- timestamp: `2026-10-05T19:27:04Z`
- status: `complete`
- author: `codex`
- reason: A dirty tree or a missing remote is a readiness blocker that only showed up deep inside the readiness report, so the list could not tell a wired-up paper from one whose version history and CI do not exist.
- files:
  - `app/README.md`
  - `app/ccfa_core/collaboration.py`
  - `app/ccfa_gui/collaboration_probe.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_chat_e2e.py`
  - `app/tests/test_chat_panel.py`
  - `app/tests/test_collaboration.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_workbench_e2e.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `app unittest discover (256 tests)`
  - `ruff check app tools`
  - `tools.tests.test_readiness + test_docs_consistency (80 tests)`
- notes: The slim report reuses the full report own git probe and dirty rule (generated readiness records do not count), pinned by a test that compares both blockers lists. Rows show a marker instead of an inline reason because the 180px sidebar elides any suffix; the probe runs on a shared QThreadPool with a generation guard, and tests disable it except one real subprocess case.

## WC-20261005T193531Z-60ed2618fc - Turn the readiness report into a countdown-first one-page report, and let the workbench export and show it.

- timestamp: `2026-10-05T19:35:31Z`
- status: `complete`
- author: `codex`
- reason: The report listed dimensions first and never named the deadline, so the one number that changes behaviour (days to submission) was only visible by running milestones separately; the app could also not produce the file at all.
- files:
  - `app/README.md`
  - `app/ccfa_core/checks.py`
  - `app/ccfa_core/projects.py`
  - `app/ccfa_gui/icon_paths.py`
  - `app/ccfa_gui/window.py`
  - `app/tests/test_checks.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_projects.py`
  - `docs/design/2026-10-06-workbench-ui-spec.md`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `app unittest discover (264 tests)`
  - `ruff check app tools`
  - `tools.tests.test_readiness + test_docs_consistency (88 tests)`
- notes: readiness JSON gains deadline/mode/days_left/overdue and the Markdown leads with ## Summary (countdown, blocker count and first blocker, human checkpoint count) plus a ## Deadline section. The workbench badge shows the countdown and keeps the date in its tooltip, and a header icon button exports reviews/readiness-<date>.md through the workflow render and opens it; the report is never re-summarised by the app.

## WC-20261005T194216Z-581900cade - Make the workbench probe verify that the resolved interpreter can actually import the gates dependencies, via a new ccfa.doctor --imports-only.

- timestamp: `2026-10-05T19:42:16Z`
- status: `complete`
- author: `codex`
- reason: Running readiness under an interpreter without pymupdf/z3/cvc5 turned formal-check and claim-candidates into failures, and a failed gate reads exactly like a blocked paper: a misconfigured interpreter silently inflated the blocking list from 2 to 4 with no hint that the machine was at fault.
- files:
  - `app/README.md`
  - `app/ccfa_core/workflow.py`
  - `app/tests/test_gui_smoke.py`
  - `app/tests/test_workflow.py`
  - `tools/ccfa/doctor.py`
  - `tools/tests/test_doctor.py`
- tests:
  - `app unittest discover (268 tests)`
  - `ruff check app tools`
  - `tools.tests.test_doctor + test_readiness + test_docs_consistency (123 tests)`
- notes: doctor --imports-only imports each dependency in the running interpreter and prints JSON (module, capability, error), green in tools/.venv and naming pymupdf/z3/cvc5/cryptography under app/.venv. probe() runs it and fails closed with the module list; an older workflow without the flag degrades to "self-check unavailable" instead of failing. Two tests that asserted a fixed verdict against "the real workflow" now assert the contract, since whether that interpreter has the deps is a property of the machine.

## WC-20261005T194731Z-3ebdb46b6e - Cap a decimal dataval claim rounding tolerance at a fraction of the source magnitude, so dropping precision stops making a mismatch easier to pass.

- timestamp: `2026-10-05T19:47:31Z`
- status: `complete`
- author: `codex`
- reason: The tolerance came only from the claim own decimals, so writing 0.1 (half unit 0.05) was accepted against a source of 0.143 while writing 0.143 (half unit 0.0005) was not: the rule rewarded losing precision, and a coarse claim stops constraining the value it claims to trace.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/datavalue.py`
  - `tools/ccfa/trace_claims.py`
  - `tools/tests/test_datavalue.py`
  - `tools/tests/test_trace_claims.py`
- tests:
  - `ruff check tools`
  - `tools.tests.test_datavalue + test_trace_claims + test_trace_claims_e2e + test_dataval + test_claims_policy + test_readiness + test_docs_consistency (161 tests)`
- notes: values_match gains max_rounding_error (default 0.05 = about two significant figures); the implied half-unit may not exceed it, integer claims are untouched (they were already exact). trace_claims.check and the CLI forward it, and a failure caused only by the cap says 小数位不足 plus the --max-rounding-error 0 escape. Verified against the live paper: all 58 dataval tags there are integers, readiness still reports 2 blockers and trace-claims still passes.

## WC-20261005T195052Z-7535723af0 - Add a claim polarity field to the claim registry, require it for supported empirical/theoretical claims, and require an experiment behind a supported null claim.

- timestamp: `2026-10-05T19:50:52Z`
- status: `complete`
- author: `codex`
- reason: A claim registry entry recorded what a claim was about (type) and how strong it was (status) but never what it asserted, so a "no difference" result could be marked supported on the strength of a citation or a figure, and nothing distinguished an effect claim from a null one when judging whether the evidence matched the sentence.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/tests/test_research_ledgers.py`
- tests:
  - `ccfa.research_ledgers --paper-root papers/rag-attack-defense --require-core (0 problems)`
  - `ruff check tools`
  - `tools.tests.test_research_ledgers + test_docs_consistency (43 tests)`
- notes: polarity is optional (effect/null/descriptive) and validated when present; descriptive claims are exempt because a count asserts no direction, which is why the live paper 5 supported descriptive claims are untouched. A supported empirical/theoretical claim without polarity is claim-registry-polarity-missing, and polarity=null without an experiment is claim-registry-null-experiment-missing. Verified the live registry still reports 0 problems and the readiness research-ledgers gate still passes.

## WC-20261005T195348Z-3793a7ad41 - Make the post-submission tail fail closed and give citation calibration a live gold set

- timestamp: `2026-10-05T19:53:48Z`
- status: `complete`
- author: `codex`
- reason: Two gaps from the GitHub comparison: the writing/rebuttal/resubmit/talk tail had contracts but no live run, and calibration had a harness but no data. readiness registered the tail gates only when their input files already existed, so a missing file silently deleted its own gate; and citation calibration had no producer of labels or predictions.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/citation_calibration.py`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/resubmit_pipeline.py`
  - `tools/ccfa/talk_pipeline.py`
  - `tools/tests/test_citation_calibration.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_citation_calibration`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_resubmit_pipeline`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_pipeline`

## WC-20261005T195416Z-824712e3ea - Make the post-submission tail fail closed and give citation calibration a live gold set

- timestamp: `2026-10-05T19:54:16Z`
- status: `complete`
- author: `codex`
- reason: Two gaps from the GitHub comparison: the writing/rebuttal/resubmit/talk tail had contracts but no live run, and calibration had a harness but no data. readiness registered the tail gates only when their input files already existed, so a missing file silently deleted its own gate; and citation calibration had no producer of labels or predictions.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/citation_calibration.py`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/resubmit_pipeline.py`
  - `tools/ccfa/talk_pipeline.py`
  - `tools/tests/test_citation_calibration.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_citation_calibration`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_resubmit_pipeline`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_pipeline`

## WC-20261005T195621Z-9b382d19ae - Give a run a scientific role (treatment/negative-control/ablation/baseline) and require a supported effect claim to cite a control run.

- timestamp: `2026-10-05T19:56:21Z`
- status: `complete`
- author: `codex`
- reason: A run log said whether a run was an experiment and how it ended, but never which side of the experiment it was, so an effect claim could be marked supported on a log that only ever contained the treatment: nothing in the record ruled out the obvious confound.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/ccfa/run_log.py`
  - `tools/tests/test_research_ledgers.py`
  - `tools/tests/test_run_log.py`
- tests:
  - `ccfa.research_ledgers + ccfa.run_log check on papers/rag-attack-defense (0 problems)`
  - `ruff check tools`
  - `tools.tests.test_run_log + test_research_ledgers + test_docs_consistency + test_experiment_loop + test_readiness (201 tests)`
- notes: record_run validates role against VALID_ROLES and refuses a role on a purpose=build run; run-log check reports run-log-role-invalid and run-log-role-on-build for hand-edited records. research_ledgers now reads run roles and reports claim-registry-control-run-missing for a supported empirical polarity=effect claim whose referenced runs contain no negative-control/ablation. Backfill note: the live paper has no experiment-purpose runs at all (all 7 run-log records are builds), and its 5 supported claims are descriptive, so there was nothing to label and the new rule does not fire on it.

## WC-20261005T200124Z-8ebfd7ce94 - Add post-submission init and make a tail stage require its own section

- timestamp: `2026-10-05T20:01:24Z`
- status: `complete`
- author: `codex`
- reason: The tail still passed while empty: a skeleton file satisfied the missing-file check and every section stayed not-started. init now derives a schema-correct ledger from the paper's real run/claim/figure ids without overwriting, and readiness requires the section a stage is named after to be complete.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_post_submission.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T200139Z-c6134746ad - Add post-submission init and make a tail stage require its own section

- timestamp: `2026-10-05T20:01:39Z`
- status: `complete`
- author: `codex`
- reason: The tail still passed while empty: a skeleton file satisfied the missing-file check and every section stayed not-started. init now derives a schema-correct ledger from the paper's real run/claim/figure ids without overwriting, and readiness requires the section a stage is named after to be complete.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/post_submission.py`
  - `tools/ccfa/readiness.py`
  - `tools/tests/test_post_submission.py`
  - `tools/tests/test_readiness.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_post_submission`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`

## WC-20261005T200146Z-8387e0bd7e - Add an optional held-out evaluation plan ledger whose freeze date, access budget and every access are validated, and require a supported effect claim to cite one.

- timestamp: `2026-10-05T20:01:46Z`
- status: `complete`
- author: `codex`
- reason: Nothing recorded which data was never used for tuning, so an effect could be reported after unbounded looks at the same evaluation set; the run log said what ran but not whether the number came from a split that was frozen before it was read.
- files:
  - `docs/workflow-guide.md`
  - `tools/ccfa/research_ledgers.py`
  - `tools/tests/test_research_ledgers.py`
- tests:
  - `ccfa.research_ledgers (worktree code) on papers/rag-attack-defense: 0 problems`
  - `ruff check tools`
  - `tools.tests.test_research_ledgers + test_docs_consistency + test_readiness (125 tests)`
- notes: data/held-out-plan.yaml splits declare role (held-out/development), artifact and, for held-out, frozen_at plus a positive access_budget; each access records run_id/at/reason and must resolve to a real run. Fail-closed codes: held-out-budget-exceeded, held-out-access-before-freeze, held-out-unknown-run, held-out-artifact-missing, held-out-invalid. An effect empirical supported claim must cite a held-out access or the plan must carry a >=40 character non-placeholder no_held_out_reason (claim-registry-held-out-missing). Live paper unaffected: no effect claims and no plan file.

## WC-20261005T201207Z-2ee565ab0b - Make the tool layer runnable without PowerShell

- timestamp: `2026-10-05T20:12:07Z`
- status: `complete`
- author: `codex`
- reason: Portability was the weakest axis: python -m ccfa did not exist, the ccfa.dispatch entry point was untested and its aliases were wrong for statistics/rigor-rubric/archive/experiment-optimize, and every tool was reachable only through 71 .ps1 wrappers. A portable dispatcher, a POSIX launcher and a fail-closed parity test make the same tools run on Linux and macOS, with a Linux CI job as evidence.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-guide.md`
  - `pyproject.toml`
  - `scripts/ccfa`
  - `scripts/install-toolchain.ps1`
  - `tools/ccfa/__main__.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_dispatch.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_packaging.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_packaging`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T201305Z-1f8150ba42 - Make the tool layer runnable without PowerShell

- timestamp: `2026-10-05T20:13:05Z`
- status: `complete`
- author: `codex`
- reason: Portability was the weakest axis: python -m ccfa did not exist, the ccfa.dispatch entry point was untested and its aliases were wrong for statistics/rigor-rubric/archive/experiment-optimize, and every tool was reachable only through 71 .ps1 wrappers. A portable dispatcher, a POSIX launcher and a fail-closed parity test make the same tools run on Linux and macOS, with a Linux CI job as evidence.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/workflow-guide.md`
  - `pyproject.toml`
  - `scripts/ccfa`
  - `scripts/install-toolchain.ps1`
  - `tools/ccfa/__main__.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_dispatch.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_packaging.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_packaging`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261005T201620Z-a6490aa603 - Keep the paper CI deterministic gates identical on Windows and Linux

- timestamp: `2026-10-05T20:16:20Z`
- status: `complete`
- author: `codex`
- reason: The paper repository now runs the deterministic gates on ubuntu-latest through .github/scripts/deterministic-gates.sh as well as inline with pwsh on windows-latest. A fail-closed test asserts both runners exercise exactly the same ccfa tool set, so the Linux job cannot silently become a weaker check.
- files:
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T201635Z-0025570e27 - Keep the paper CI deterministic gates identical on Windows and Linux

- timestamp: `2026-10-05T20:16:35Z`
- status: `complete`
- author: `codex`
- reason: The paper repository now runs the deterministic gates on ubuntu-latest through .github/scripts/deterministic-gates.sh as well as inline with pwsh on windows-latest. A fail-closed test asserts both runners exercise exactly the same ccfa tool set, so the Linux job cannot silently become a weaker check.
- files:
  - `tools/tests/test_github_workflows.py`
- tests:
  - `tools.tests.test_github_workflows`

## WC-20261005T202518Z-4523c9af47 - Fix the three machine-dependent tools-test failures that kept CI red

- timestamp: `2026-10-05T20:25:18Z`
- status: `complete`
- author: `codex`
- reason: The GitHub Windows runner failed tools-impact on every recent push. experiment_optimizer compared a spec path spelling (8.3 short name RUNNER~1) against a resolved paper_root and raised ValueError on a file inside the paper; two external-adapter tests asserted installed against whatever skills the developer machine had, so they failed on a clean runner. Confirmed against real Actions logs for runs 37360029400 and 37361015600, which failed identically before this branch existed.
- files:
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_external_adapters.py`
- tests:
  - `scripts/test-impact.ps1 run --suite tools --full (1812 tests)`
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_external_adapters`

## WC-20261005T202534Z-67bb3895f9 - Fix the three machine-dependent tools-test failures that kept CI red

- timestamp: `2026-10-05T20:25:34Z`
- status: `complete`
- author: `codex`
- reason: The GitHub Windows runner failed tools-impact on every recent push. experiment_optimizer compared a spec path spelling (8.3 short name RUNNER~1) against a resolved paper_root and raised ValueError on a file inside the paper; two external-adapter tests asserted installed against whatever skills the developer machine had, so they failed on a clean runner. Confirmed against real Actions logs for runs 37360029400 and 37361015600, which failed identically before this branch existed.
- files:
  - `tools/ccfa/experiment_optimizer.py`
  - `tools/tests/test_experiment_optimizer.py`
  - `tools/tests/test_external_adapters.py`
- tests:
  - `tools.tests.test_experiment_optimizer`
  - `tools.tests.test_external_adapters`

## WC-20261005T213608Z-637574217a - Record an end-to-end snapshot of the flagship paper: gate verdicts, the six human checkpoints, environment health and the workbench-side links actually rerun.

- timestamp: `2026-10-05T21:36:08Z`
- status: `complete`
- author: `codex`
- reason: The layered checks each answered one question, but nothing stated the current whole-paper state in one place, so it was impossible to see at a glance that every remaining blocker is human or external rather than mechanical.
- files:
  - `docs/e2e-check-2026-10-06.md`
- tests:
  - `app export_readiness -> 6200 bytes with ## Summary`
  - `ccfa.doctor --repo-root repo (0 problems, 1 advisory: zotero 23119)`
  - `ccfa.readiness --collaboration-only (collaboration_ready=true, commit 5253728)`
  - `ccfa.readiness on papers/rag-attack-defense (exit 1, 2 blockers, 18/20 gates pass)`
  - `ccfa_gui.main --self-check (probe_ok=true, exit 0)`
- notes: Paper repo untouched: every report was written to %TEMP%, and the snapshot records that. 20 gates: 18 pass; argument-audit fails with 8 proof-review-not-verified + 6 citation-support-missing + 1 figure-support-missing, cross-review fails with review-blocking.

## WC-20261005T215008Z-7760a8b83d - Add ccfa.e2e_check / scripts/e2e-check.ps1: one command that composes the full gate set and the platform preflight into a single Markdown snapshot.

- timestamp: `2026-10-05T21:50:08Z`
- status: `complete`
- author: `codex`
- reason: The state of a paper was spread over five commands and five outputs, so seeing that every remaining blocker is human rather than mechanical required running readiness, doctor, self-check, collaboration and milestones by hand and reading all of them.
- files:
  - `README.md`
  - `scripts/e2e-check.ps1`
  - `tools/ccfa/e2e_check.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `ccfa.e2e_check on the flagship paper: ready=false, 2 blocking, 20 gates (18 pass), 6 human checkpoints, 0 environment problems / 1 advisory`
  - `ruff check tools scripts`
  - `tools.tests.test_scripts inventory/contract + test_docs_consistency (19 tests)`
- notes: Read-only: without --out it prints and writes nothing, and it never touches the paper tracked files. Output leads with an auto-generated headline (ready/blocking/gate pass count) then the gate table with de-duplicated problem codes, the human checkpoint table with its destination ledger, the doctor problems/advisories plus the installed/reachable inventory, git/CI and the countdown. discover_paper refuses to guess when papers/ holds more than one project. Exit code reports whether the snapshot was produced, not whether the paper is ready.

## WC-20261005T215837Z-36be525a3c - Update the e2e snapshot with the Zotero verification results and the fact that the environment is now fully green.

- timestamp: `2026-10-05T21:58:37Z`
- status: `complete`
- author: `codex`
- reason: The committed snapshot listed Zotero 23119 as the one remaining environment gap; leaving it that way after the link was verified and doctor went to 0 advisories would make a dated record quietly wrong.
- files:
  - `docs/e2e-check-2026-10-06.md`
- tests:
  - `ccfa.doctor --repo-root repo (0 problems, 0 advisories, functional zotero HTTP 200)`
  - `zotero-mcp.exe serve initialize + 41 tools + import/search/bibtex/delete round trip`
- notes: Records the dedupe result precisely: if_exists=skip de-duplicates when the record carries an identifier (DOI), and does not fall back to fuzzy title matching. Three probe items were trashed and live items are back to zero; no Zotero account sync is configured, so nothing left the machine.

## WC-20261006T000000Z-mandatory-log - Add an append-only, fail-closed workflow change log contract.

- timestamp: `2026-10-06T00:00:00Z`
- status: `complete`
- author: `codex`
- reason: 用户要求规定每次工作流修改都必须记录日志，不能用聊天记录代替可审计变更日志。
- files:
  - `.github/pull_request_template.md`
  - `.github/workflows/tests.yml`
  - `AGENTS.md`
  - `README.md`
  - `docs/workflow-change-log.jsonl`
  - `docs/workflow-change-log.md`
  - `docs/workflow-guide.md`
  - `scripts/change-log.ps1`
  - `tools/ccfa/change_log.py`
  - `tools/tests/test_change_log.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_change_log`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_scripts`
- notes: The log itself and its generated Markdown are excluded from coverage checks, but listed here for traceability.

## WC-20261005T221321Z-a43688691e - Reconcile the local workflow branch with origin/master and register e2e-check in the dispatch map and compile list.

- timestamp: `2026-10-05T22:13:21Z`
- status: `complete`
- author: `codex`
- reason: Local master and origin/master had diverged (42 ahead / 13 behind) with intersecting work, and the newly added e2e-check wrapper was missing from dispatch.COMMANDS and the CI py_compile list, which broke the dispatch parity tests.
- files:
  - `.github/workflows/tests.yml`
  - `docs/workflow-change-log.jsonl`
  - `docs/workflow-change-log.md`
  - `docs/workflow-guide.md`
  - `tools/ccfa/dispatch.py`
- tests:
  - `tools.tests.test_dispatch (7 tests)`
- notes: Merge commit 8ecb3bf. Conflicts in the change log were resolved by union of entry ids; workflow-guide.md kept the local side after verifying it is a strict superset of origin/master (0 remote-only lines).

## WC-20261005T221325Z-baf9040305 - Backfill the change-log entry for semantic and hybrid retrieval in the shared literature library.

- timestamp: `2026-10-05T22:13:25Z`
- status: `complete`
- author: `codex`
- reason: Commit 76566b0 added semantic and hybrid retrieval to tools/ccfa/library.py plus 349 lines of tests, but landed without a change-log entry, so change-log check flagged both files as uncovered.
- files:
  - `tools/ccfa/library.py`
  - `tools/tests/test_library.py`
- tests:
  - `tools.tests.test_library (65 tests)`
- notes: Entry written after the fact to satisfy the append-only change-log contract; the tests were re-run before recording this entry.

## WC-20261005T221338Z-03721b5e75 - Add the workflow assessment reports and refresh the gap summary.

- timestamp: `2026-10-05T22:13:38Z`
- status: `complete`
- author: `codex`
- reason: These analysis documents record the tooling inventory, the top-venue evaluation, the big-check and cleanup findings, the disk relocation, the toolchain install and the workflow fit audit; they were written to docs/ without accompanying change-log entries.
- files:
  - `docs/big-check-and-cleanup-2026-10-05.md`
  - `docs/disk-relocation-2026-10-05.md`
  - `docs/research-workflow-topvenue-evaluation-2026-10-05.md`
  - `docs/toolchain-workflow-fit-2026-10-05.md`
  - `docs/tooling-gaps-2026-10-05.md`
  - `docs/tooling-install-2026-10-05.md`
  - `docs/workflow-gap-summary.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Documentation only; no workflow code changed.

## WC-20261005T222126Z-9983a0e142 - Correct the workflow introduction: the Windows workbench installer is delivered, not pending.

- timestamp: `2026-10-05T22:21:26Z`
- status: `complete`
- author: `codex`
- reason: docs/research-workflow-intro.md still claimed the Windows launcher, shortcut and PyInstaller installer were not delivered, but dist/ccfa-workbench-setup-0.1.0.exe exists and the installed ccfa-workbench.exe --self-check passes; the remaining gap is a clean-machine acceptance run, not the build.
- files:
  - `docs/research-workflow-intro.md`
- tests:
  - `ccfa-workbench.exe --self-check (probe_ok=true, exit 0)`
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Documentation corrected against the built artifact; the product-readiness table and the next-step list now say the installer is built and only the clean-machine acceptance remains.

## WC-20261005T223117Z-b272b3d157 - Inventory the workflow's plugins, tools and skills, and analyse the remaining gaps against open-source research agents.

- timestamp: `2026-10-05T22:31:17Z`
- status: `complete`
- author: `codex`
- reason: The tool and plugin layer changed substantially (second provider, nine formal engines, installer, archive and compute adapters), so the earlier tooling-gaps document was stale and no single document listed the current inventory plus the remaining methodological gaps.
- files:
  - `docs/research-workflow-tooling-and-gaps-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Documentation only. Records 87 modules, 72 entries, 9 MCP servers, 28 plugins, 305 skills and the verified adoption of polarity / held-out / negative-control / gate drills; the remaining gaps are metrics (null-model baseline, attempt throughput), external links (remote compute, Zenodo DOI, clean-machine installer acceptance) and the six human checkpoints.

## WC-20261005T223656Z-834aa52586 - Add the missing cryptography pin to the tools lock and guard against lock drift

- timestamp: `2026-10-05T22:36:56Z`
- status: `complete`
- author: `codex`
- reason: CI installs tools/requirements.lock, not requirements.txt, and cryptography existed only in the latter. A clean runner therefore had no cryptography, so test_doctor's fully-provisioned assertion failed there while passing on a developer machine. Observed in Actions run 37381530489 (7890a6e): missing [cryptography], ok=false. The failure is masked on docs-only pushes because impact selection runs about 17 tests, so only the nightly full run would have caught it.
- files:
  - `tools/requirements.lock`
  - `tools/tests/test_packaging.py`
- tests:
  - `clean venv + uv pip install -r tools/requirements.lock + doctor --imports-only`
  - `tools.tests.test_doctor`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_packaging`

## WC-20261005T223811Z-7da4601920 - Pin the rule that dependency files force the full test suite

- timestamp: `2026-10-05T22:38:11Z`
- status: `complete`
- author: `codex`
- reason: No behaviour change. While fixing the lock drift I claimed the impact selector also missed tools/requirements.lock; testing the original code showed both lock files already returned full=True through the generic 'unmapped path under tools/ or app/' fall-through. The two explicit entries plus a new test make an implicit, load-bearing rule explicit, so a future early return cannot silently downgrade a dependency change to a partial run.
- files:
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_test_impact`

## WC-20261006T045538Z-15d834961a - Require a zero-skill baseline and per-attempt economics

- timestamp: `2026-10-06T04:55:38Z`
- status: `complete`
- author: `codex`
- reason: Two measurement gaps: nothing forced a paper to say what a zero-skill method would score, and nothing recorded how long the first attempt took or what an attempt cost. statistics-plan now requires a null_baseline per claim (recorded value+source, or not-applicable+reason) and the cost ledger requires time_to_first_attempt and cost_per_attempt. Also fixed compute check hardcoding Path('.') so it accepts --paper-root, and corrected the archive_client docstring: zenodo.org resolves again and the API answered HTTP 200 on 2026-10-06.
- files:
  - `tools/ccfa/archive_client.py`
  - `tools/ccfa/compute.py`
  - `tools/ccfa/research_ledgers.py`
  - `tools/ccfa/stats_plan.py`
  - `tools/tests/test_compute.py`
  - `tools/tests/test_research_ledgers.py`
  - `tools/tests/test_statistics.py`
- tests:
  - `tools.tests.test_archive_client`
  - `tools.tests.test_compute`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_readiness`
  - `tools.tests.test_research_ledgers`
  - `tools.tests.test_statistics`

## WC-20261006T051037Z-ff81b58303 - Turn the one-page snapshot into a metrics trend

- timestamp: `2026-10-06T05:10:37Z`
- status: `complete`
- author: `codex`
- reason: The attempt metrics were recorded and enforced but only ever shown as one reading. e2e_check now appends one sample (attempt economics plus the blocking count) to data/metrics-history.jsonl whenever a snapshot is deliberately written with --out, and renders the recent samples with the blocking delta; --no-record keeps a one-off snapshot from touching history, and the paper CI passes it because its checkout is throwaway.
- files:
  - `tools/ccfa/e2e_check.py`
  - `tools/tests/test_e2e_check.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_e2e_check`
  - `tools.tests.test_github_workflows`

## WC-20261006T051449Z-caedbe1de5 - Compare the workflow with ARIS skill-by-skill and record where each is stronger.

- timestamp: `2026-10-06T05:14:49Z`
- status: `complete`
- author: `codex`
- reason: ARIS is the closest open-source neighbour but is a prompt-skill corpus rather than a verification layer; the comparison separates the two so the remaining gaps (compute access, adversarial-review roles, self-evolution gate) are not confused with skill count.
- files:
  - `docs/aris-comparison-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Read ARIS docs/SKILLS_CATALOG.md at its current revision (83 skills, 10 categories) and compared against this repo's 87 modules and 20 gates. Documentation only.

## WC-20261006T051610Z-1092f39662 - Correct the tooling and gaps report: zero-skill baseline, attempt economics and remote-compute declaration are already implemented.

- timestamp: `2026-10-06T05:16:10Z`
- status: `complete`
- author: `codex`
- reason: The first revision listed three gaps that commits 5e84186 and 39706eb closed while the report was being written: stats_plan now requires a zero-skill baseline, research_ledgers requires time_to_first_attempt and cost_per_attempt, and data/compute.yaml exists with an explicit empty backend list.
- files:
  - `docs/research-workflow-tooling-and-gaps-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Verified against the code: stats_plan.py zero-skill requirement, research_ledgers.COST_METRIC_FIELDS, e2e_check metric rendering, and the paper's cost-ledger.yaml metrics block.

## WC-20261006T052843Z-3de3db1c8f - Measure the workflow's own gates instead of only wiring them

- timestamp: `2026-10-06T05:28:43Z`
- status: `complete`
- author: `codex`
- reason: The last remaining engineering gap in the gaps analysis was that the tool layer was never evaluated: gates were wired and drilled by hand, but nothing measured whether a gate rejects what it claims to reject. ccfa.tool_eval injects known defects into throwaway fixtures and reports per-gate detection and false-alarm rates. Deliberately aligned with ARIS tools/meta_opt/trigger_eval.py: measure-only, errors graded separately and excluded from the denominators, rates rounded to three decimals, exit 0 on a completed run and 2 only on a setup error.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/tool-eval-2026-10-06.json`
  - `docs/tool-eval-2026-10-06.md`
  - `scripts/tool-eval.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/test_impact.py`
  - `tools/ccfa/tool_eval.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_tool_eval.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_test_impact`
  - `tools.tests.test_tool_eval`

## WC-20261006T062142Z-4ac65227c5 - Derive model families for vendor-prefixed aggregator ids

- timestamp: `2026-10-06T06:21:42Z`
- status: `complete`
- author: `codex`
- reason: Free cross-family reviewers are only reachable through aggregators, whose ids are vendor-prefixed (nvidia/nemotron-3-ultra-550b-a55b:free, z-ai/glm-5.3, qwen/qwen3.8-flash). Matching only the full string classified every one of them as unknown, so family_judgement returned unknown and the gate failed closed on a reviewer it could otherwise accept. The bare name after the slash is now matched too, and nvidia/nemotron map to the nvidia family.
- files:
  - `tools/ccfa/cross_review.py`
  - `tools/tests/test_cross_review.py`
- tests:
  - `tools.tests.test_cross_review`

## WC-20261006T063331Z-57f6587ee6 - Update the ARIS comparison: the multi-backend reviewer gap closed, tool self-evaluation added, and one stale blocking item found.

- timestamp: `2026-10-06T06:33:31Z`
- status: `complete`
- author: `codex`
- reason: Since the first comparison the repo gained four model providers and ran a gate-capable cross-family review through OpenRouter, and it added ccfa.tool_eval to measure its own gate detection rates; the comparison's multi-backend row was stale and the new self-inconsistency in the cross-review record needed recording.
- files:
  - `docs/aris-comparison-2026-10-06.md`
- tests:
  - `ccfa.tool_eval (10 cases: 6 caught, 4 clean, 0 missed, 0 false alarms)`
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Records that the remaining structural gaps against ARIS are compute access, adversarial-review role granularity and the self-evolution landing gate; also notes a model-authored stale review-advisory-only item inside the otherwise gate-capable cross-review record.

## WC-20261006T063624Z-5fbeb8a85e - Recognise the independent labs that serve free reviewers

- timestamp: `2026-10-06T06:36:24Z`
- status: `complete`
- author: `codex`
- reason: The free tier that makes a cross-family review affordable is served by new labs (thinkingmachines/inkling, dots-studio/dots-3, poolside/laguna, cohere/north, inclusionai/ling, liquid/lfm, apodex). None were in the family table, so every one of them derived as unknown and the gate failed closed on the strongest free reviewers available. Each is a distinct family from the DeepSeek executor, which is the only question this table answers; capability stays with _review_tier.
- files:
  - `tools/ccfa/cross_review.py`
  - `tools/tests/test_cross_review.py`
- tests:
  - `tools.tests.test_cross_review`

## WC-20261006T064706Z-2240fa3ea3 - Reject a review that restates a superseded review's conclusion

- timestamp: `2026-10-06T06:47:06Z`
- status: `complete`
- author: `codex`
- reason: The regenerated cross-review.json was internally inconsistent: its own review_tier was gate-capable, yet its blocking list carried a bare 'review-advisory-only' item quoting the previous local-qwen review. The item slipped through because the evidence really was quoted from an input file (the old record). The prompt now states that this review supersedes the previous record and reserves the three workflow finding prefixes, and the auditor rejects any model-authored blocking title whose stem is one of those reserved codes. Verified on the real record: it now reports review-stale-finding against blocking[3].
- files:
  - `tools/ccfa/cross_review.py`
  - `tools/tests/test_cross_review.py`
- tests:
  - `tools.tests.test_cross_review`

## WC-20261006T065448Z-f5734df1b5 - Add zero-context numeric audit and two-line kill-argument roles

- timestamp: `2026-10-06T06:54:48Z`
- status: `complete`
- author: `codex`
- reason: ARIS separates 'drive' from 'acquit'; this port adds the two adversarial producers from docs/aris-comparison-2026-10-06.md 5.3. claim-audit recomputes the manuscript's numbers with the author's derivations mechanically removed (the excluded set is recorded and the reviewer is pointed at a staging tree that does not contain them). kill-argument runs two independent subprocesses, one writing the strongest rejection memo and one the point-by-point defence, neither able to see the other's prompt. Both roles write reviews/adversarial-review.json only; an unresolved finding is a blocking problem, a thin resolution is flagged, and an advisory-only reviewer cannot close the record. The gate is registered in readiness so the tool is load-bearing rather than a library.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `scripts/adversarial-review.ps1`
  - `tools/ccfa/adversarial_review.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_adversarial_review.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_adversarial_review`
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T070835Z-c38bbcfaaa - Close the adversarial-review gap row in the ARIS comparison

- timestamp: `2026-10-06T07:08:35Z`
- status: `complete`
- author: `codex`
- reason: The gap table still listed four review roles after this session added ccfa.adversarial_review, so the doc understated the repository's own state. Row 2 now counts six roles and the note records what the two new producers do and that unresolved findings enter the readiness gate.
- files:
  - `docs/aris-comparison-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency`

## WC-20261006T071809Z-ca1f4b7d39 - Install MiKTeX in CI only when the impacted tests compile documents

- timestamp: `2026-10-06T07:18:09Z`
- status: `complete`
- author: `codex`
- reason: The tools job installed MiKTeX unconditionally, and the Chocolatey step took about 12.5 minutes even for a docs-only change. Only three test modules hand a real document to a real engine (test_compile, test_derivation_e2e, test_e2e); every other LaTeX test injects a fake runner or stubs find_engine. The impact selector now exposes a needs-latex action that answers the boolean from the same git diff it already resolves, the workflow gates the install on it, and a probe that cannot decide falls back to installing so a broken check cannot silently weaken the run. A test derives the engine-dependent set from the tests' own request_latex_engine calls so the constant cannot drift.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_github_workflows.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T072550Z-450459b47d - Record the third round of the ARIS comparison: adversarial-review roles added, stale findings now rejected.

- timestamp: `2026-10-06T07:25:50Z`
- status: `complete`
- author: `codex`
- reason: Since the previous comparison the repo added ccfa.adversarial_review (zero-context claim audit plus two-line kill-argument), made cross_review reject conclusions restated from a superseded review, and recognised free cross-family reviewers; the comparison's adversarial-role row and stale-finding subsection were both out of date.
- files:
  - `docs/aris-comparison-2026-10-06.md`
- tests:
  - `tools.tests.test_adversarial_review (6 tests)`
  - `tools.tests.test_docs_consistency (17 tests)`
- notes: Also records the flagship paper's current blocking set (review-prompt-drift, review-blocking, review-stale-finding) and that reviews/adversarial-review.json has not been produced yet.

## WC-20261006T075458Z-ee38167af5 - Add an executable ssh compute backend and fail-closed config validation

- timestamp: `2026-10-06T07:54:58Z`
- status: `complete`
- author: `codex`
- reason: ARIS reaches five compute backends; this workflow had probes for Slurm/PBS but no way to actually run anything remotely, so the only real capacity was the local box. compute.py now accepts kind: ssh with port/identity_file/workdir/options, executes over SSH under the same wall-clock budget as the local path, and records backend/wall_seconds/gpu_minutes in the compute ledger. probe_remote for ssh returns a ccfa-ok receipt plus the visible GPU count instead of treating a TCP connect as reachability. Slurm/PBS stay probe-only and run --backend refuses them rather than pretending a job was submitted. load_backends stays lenient so one typo cannot take down plan, while a new validate_config surfaces unknown kinds, missing hosts, bad port/gpus/options and duplicate names as blocking problems in check and a compute validate subcommand. Verified live against a containerised sshd: probe reached=true/ccfa_ok=true, a remote command left a marker inside the container, and a 3s budget killed a sleep 120 at 3.03s with timed_out=true.
- files:
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `tools/ccfa/compute.py`
  - `tools/tests/test_compute.py`
- tests:
  - `tools.tests.test_compute`
  - `tools.tests.test_docs_consistency`

## WC-20261006T075817Z-257467402f - Correct the compute-interface live note to the real root cause

- timestamp: `2026-10-06T07:58:17Z`
- status: `complete`
- author: `codex`
- reason: The first write-up implied the identity_file/options fields existed because of ssh protocol interop. The actual live blocker was a passphrase-protected key generated by ssh-keygen -N with PowerShell single quotes, which BatchMode cannot unlock and which looks like an Accepted-key-then-close server failure. The note now records the correct diagnostic order (verify the key opens without a passphrase first) and states the truthful reason the fields exist: non-default port, explicit key, temp known_hosts, ProxyJump-style setups.
- files:
  - `docs/aris-comparison-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency`

## WC-20261006T080459Z-6f14d48ade - Let the experiment queue dispatch a whole run to a remote ssh backend

- timestamp: `2026-10-06T08:04:59Z`
- status: `complete`
- author: `codex`
- reason: compute.py could execute over ssh but the queue could only run locally, so a multi-item experiment still had to be babysat item by item. A queue manifest now takes backend: <name> plus an optional compute_config path, and run_queue swaps each item's argv for the ssh argv built by the new compute.remote_argv, keeping timeout, stall watchdog, retry and streamed output identical. The backend is persisted in every run-log record as policy.backend/kind/target/workdir, so 'where it ran' is a checkable field rather than a claim. Fail-closed choices: a missing or non-executable backend is rejected before anything runs, sandbox=docker and a remote backend are mutually exclusive, and gpu_budget_s with a remote backend is refused because local nvidia-smi cannot measure remote GPU time. compute also gains load_backend_file so the queue reads the exact file its manifest names instead of the paper-root convention. Verified live against a containerised sshd: a 3-item queue ran wholly on the remote, the retry item went FIRST(exit 7) then SECOND(exit 0), and the 3s timeout item was killed at exit 124.
- files:
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `tools/ccfa/compute.py`
  - `tools/ccfa/queue.py`
  - `tools/tests/test_compute.py`
  - `tools/tests/test_queue.py`
- tests:
  - `tools.tests.test_compute`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_queue`

## WC-20261006T081236Z-99184b2624 - Make the experiment queue resumable after a crash

- timestamp: `2026-10-06T08:12:36Z`
- status: `complete`
- author: `codex`
- reason: The queue re-ran every item from the top after an interruption, so a long multi-item sweep lost all finished work. run_queue now persists progress to <log-dir>/.queue-state after each recorded outcome (atomically, and only after the run-log record exists) and --resume skips items whose last status is complete; failed or skipped items still run. The state is bound to a digest of the normalized items plus queue options, so resuming against an edited manifest is a hard exit 2 instead of silently skipping or re-running the wrong work. The file deliberately has no .json extension because run_log.check_runs globs *.json in the same directory and would try to parse it as a run record. Default behaviour without --resume is unchanged (fresh run, state overwritten). Verified live: killed the queue process during item 2, state kept only item 1 complete, --resume then ran items 2 and 3 and the remote marker file held ONE/TWO/THREE exactly once, and an edited manifest was refused with exit 2.
- files:
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `tools/ccfa/queue.py`
  - `tools/tests/test_queue.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_queue`

## WC-20261006T081941Z-367980d605 - Add wave gating to the experiment queue

- timestamp: `2026-10-06T08:19:41Z`
- status: `complete`
- author: `codex`
- reason: ARIS runs the queue in waves with a gate between them; this queue could only run one flat list. A manifest can now use waves instead of queue, each wave carrying an optional gate whose command must exit 0 before that wave opens, and any item that does not complete blocks the following wave unless that wave sets continue_on_failure. Gate outcomes (command, exit code, duration, pass/fail) go into <log-dir>/.queue-state, and blocked items are recorded as skipped-gate or skipped-wave without ever reaching the runner, so no run-log record is fabricated for work that did not happen. Flat manifests still load as one implicit wave, and the digest now covers the wave layout and gates so resume refuses a manifest whose gating changed. Only a wave with pending items re-derives its gate on resume; a fully finished wave and its gate are skipped. Item validation was extracted into _normalize_item so waves and the flat list share one contract. Verified locally end to end: recall 0.4 blocked the second wave (exit 1, skipped-gate, run-log held only the screen record), recall 0.8 ran both waves with gate exit_code 0, and a killed run resumed correctly across waves with the gate re-evaluated.
- files:
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `tools/ccfa/queue.py`
  - `tools/tests/test_queue.py`
- tests:
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_queue`

## WC-20261006T083121Z-9c0a1d56b3 - Add the self-evolution landing gate (meta-apply)

- timestamp: `2026-10-06T08:31:21Z`
- status: `complete`
- author: `codex`
- reason: ARIS pairs a read-only /meta-optimize producer with a single privileged /meta-apply that lands a staged diff only after a cross-model jury passes it; this repo had only the producer. tools/ccfa/meta_apply.py adds the other half. stage writes the candidate under ccfa-workfiles/meta-apply/<id>/ with before/after hashes and a unified diff and never touches the working tree. review runs one model per --model over that diff, with an optional per-model provider so a cross-aggregator jury is possible, and records each verdict with its family and capability tier. apply refuses unless the staged bytes, the live target and the reviewed diff all still hash to what was recorded, at least two gate-capable reviewers passed, they span at least two model families and at least one is cross-family relative to the executor; it then writes a byte-identical backup (read_bytes/write_bytes, because the text helpers would rewrite CRLF) and appends an audit record to an append-only ledger. The default allowlist is the guidance corpus (docs/checklists/automation/skills/library); landing into tools/scripts/app needs an explicit --allow-code that is recorded. check verifies the ledger still matches its backups. Live attempt surfaced a real reviewer defect: glm-4-flash answered 'verdict=block' in a key=value format, and the old fallback would have parsed the nested finding as if it were the verdict; the parser now requires a verdict-bearing object and reports the raw output, so a broken contract fails closed with exit 2 instead of half-parsing.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `scripts/meta-apply.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/meta_apply.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_meta_apply.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_meta_apply`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T084417Z-9d2cbe8267 - Add a deterministic figure-spec to SVG renderer

- timestamp: `2026-10-06T08:44:17Z`
- status: `complete`
- author: `codex`
- reason: ARIS has /figure-spec, a deterministic JSON->SVG renderer with shape-aware edge trimming, self-loops and CJK width handling; this repo only had figure_manifest (which hashes figures) and figurebytes (which sniffs image types), so a figure could not be re-rendered or diffed from data. tools/ccfa/figure_spec.py takes a declarative JSON/YAML spec and emits SVG bytes: the same spec always produces identical bytes, which is asserted in the tests. Shape-aware trimming stops an edge on the boundary of the rectangle, ellipse or diamond it points at instead of at the node centre; from == to draws a real loop with its own arrowhead; text width uses unicodedata.east_asian_width so a Chinese label does not overflow its box (and check reports the overflow as an advisory instead of clipping silently). A straight edge that would run through an unrelated node is detected with a Liang-Barsky clip test and bowed around it, because a line crossing a box reads as a pipeline that does not exist. Nodes without coordinates are placed by longest-path rank so a pipeline reads left to right. Determinism means no timestamps, no random ids and a fixed float format. Verified by rendering the committed docs/examples/figure-spec-example.yaml, checking the sha is identical across two runs, and inspecting the PNG conversion visually.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/examples/figure-spec-example.yaml`
  - `scripts/figure-spec.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/figure_spec.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_figure_spec.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_figure_spec`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T085614Z-ae69b56ed7 - Add the measured talk/poster gate orchestrator

- timestamp: `2026-10-06T08:56:14Z`
- status: `complete`
- author: `codex`
- reason: The ARIS comparison listed post-submission output depth as a gap: this repo had a talk plan contract but nothing that measured the deck. Read the reference source directly (skills/paper-poster-html/scripts/run_gates.py, poster_check.py, _posterly/measure.py, _posterly/verify_final.py at commit 3b19a22) and rebuilt its architecture in tools/ccfa/talk_gates.py: a fixed canonical order preflight -> asset -> measure -> polish, per-gate hard/soft severity with polish soft and --strict-polish promoting it, accumulate-by-default with --fail-fast opt-in for CI, one data/talk-gate-report.json, and exit 0/1/2 for pass/hard-failure/usage-error. measure renders each slide's text into the canvas typography declared by the plan (CJK-aware width from figure_spec) and reports a fill ratio; overflow is a hard failure. verify-final mirrors the reference contract: page count, page size within 0.05in (with rotated-page swap) and file size, and it refuses to run without an explicit --canvas or --from-plan because a guessed default is worse than an error. Deliberate deviations are recorded in the report and the docs: the reference measures its own HTML templates in headless Chromium, which this repo has no equivalent of, and its style gate checks a shipped design-token system we do not have, so style is not implemented and is named in not_implemented_gates. The asset gate checks what a figure is rather than how many bytes it has - a live run flagged a legitimate 370-byte flat-colour PNG, so it now reads the real pixel dimensions from the PNG/JPEG/GIF header and skips pixel checks for SVG/PDF. Verified live by compiling a 3-page Beamer 16:9 deck with pdflatex: healthy deck overall=pass and verify-final 0 problems, a 25-bullet slide fails with fill 2.24 (needs 6.831in of 3.043in), and --pages 5 against a 3-page PDF reports talk-pdf-page-count.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/reference-aris-2026-10-06.md`
  - `scripts/talk-gates.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/talk_gates.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_talk_gates.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_gates`
  - `tools.tests.test_test_impact`

## WC-20261006T090706Z-2a155ca003 - Generate a Beamer deck from the talk plan

- timestamp: `2026-10-06T09:07:06Z`
- status: `complete`
- author: `codex`
- reason: talk_pipeline checked the plan and talk_gates measured the result, but nothing turned the plan into slides, so 'the plan is complete' and 'a deck exists' were separate facts. Read ARIS's skills/paper-slides/SKILL.md for its output contract (beamer+PDF+PPTX, per-frame notes, standalone speaker_notes.md, SLIDES_STATE.json, a five-entry venue colour table, title >=28pt, body >=20pt) and implemented tools/ccfa/talk_deck.py: venue colours, title frame plus one frame per slide plus a thank-you frame, note{} from speaker_notes, the standalone notes file, a state file that names the unimplemented PPTX export, figures resolved from the figure manifest and copied in (ARIS symlinks, which needs privileges on Windows), CJK auto-switching to xelatex+ctex, and byte-identical output for the same plan. One deliberate deviation, forced by a live defect: ARIS's point sizes assume a 13.33in canvas while Beamer's 16:9 page is 16cm wide, so the generated document pins paperwidth/paperheight with geometry to the plan's canvas and uses the declared sizes literally; otherwise measure would check different typography than the deck renders and verify-final --from-plan could never agree with the PDF. talk_gates.measure also now counts a figure's drawn height using the real pixel dimensions, because the first live render showed width-only includegraphics pushing the bullets off a wide slide; the template now uses width+height+keepaspectratio. verify-final's pdfinfo call gained an explicit UTF-8 decode after it crashed with GBK on a PDF carrying a Chinese title. Verified live: a three-slide Chinese plan with an ICML venue and a figure rendered, compiled with xelatex to five frames of 959.98x540pt, passed verify-final --from-plan, and the PNG render was inspected.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/reference-aris-2026-10-06.md`
  - `scripts/talk-deck.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/talk_deck.py`
  - `tools/ccfa/talk_gates.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_talk_deck.py`
  - `tools/tests/test_talk_gates.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_deck`
  - `tools.tests.test_talk_gates`
  - `tools.tests.test_test_impact`

## WC-20261006T092948Z-d6d8b098f4 - Add a content-preserving slides polish pass

- timestamp: `2026-10-06T09:29:48Z`
- status: `complete`
- author: `codex`
- reason: ARIS's slides-polish is the layout-only pass over a finished deck; this repo generated a deck but had no post-generation pass. Read skills/slides-polish/SKILL.md and kept its two load-bearing rules: hard scope (never touch claims, numbers, citations, URLs, authors, affiliations or results; never add, remove or reorder slides; never change figures or equations) and OUTPUT_VERSIONING (snapshot the original, land edits in <stem>_polished, never overwrite). tools/ccfa/slides_polish.py implements the deterministic half: it snapshots to _pre_polish.tex without clobbering an existing snapshot, writes a versioned _polished.tex (then _v2, _v3), renders every PDF page to PNG through pdftoppm/mutool/magick so a review can look at pixels, and writes POLISH_STATE.json, INSPECT_*.json, POLISH_CHANGELOG.md and per-page traces under .ccfa/slides-polish/. It applies exactly one mechanical rewrite - a width-only includegraphics gets height=0.6\textheight,keepaspectratio, which is the overflow the previous slice found by eye - and only reports what needs judgement (font below the projector floor, missing geometry pin, navigation symbols left on) instead of rewriting it; the reference uses a per-page model review for those. The no-content-change claim is checkable rather than asserted: slides-polish check diffs snapshot against output line by line and accepts a change only when it matches an allowed rule and the line count is unchanged. Verified live on a generated deck whose height bound was removed by hand: run fixed the line, snapshotted, versioned the output, rendered 4 pages and logged the before/after diff, and tampering with the output produced slides-polish-unauthorised-change. PPTX is not implemented and is named in the state file.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/reference-aris-2026-10-06.md`
  - `scripts/slides-polish.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/slides_polish.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_slides_polish.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_scripts`
  - `tools.tests.test_slides_polish`
  - `tools.tests.test_test_impact`

## WC-20261006T093453Z-347d141464 - Report an unusable PDF renderer instead of assuming it worked

- timestamp: `2026-10-06T09:34:53Z`
- status: `complete`
- author: `codex`
- reason: CI caught this: the Windows runner has magick on PATH, so the page-render test did not skip, but ImageMagick's default policy blocks the PDF coder, so rendering produced nothing and the test failed with 0 rendered pages. A binary on PATH is not a working renderer. slides_polish.polish now records page_render (rendered / unavailable / disabled / not-run) in POLISH_STATE.json and writes an explicit '逐页像素复核：未完成' section into POLISH_CHANGELOG.md when a PDF exists but nothing rendered, so a missing pixel pass is visible rather than implied. The test now probes the real render path and skips only when no renderer actually produces an image, and a new test covers the unavailable path with a patched renderer.
- files:
  - `tools/ccfa/slides_polish.py`
  - `tools/tests/test_slides_polish.py`
- tests:
  - `tools.tests.test_slides_polish`

## WC-20261006T094347Z-fcd32880db - Generate and verify a print-ready HTML poster

- timestamp: `2026-10-06T09:43:47Z`
- status: `complete`
- author: `codex`
- reason: The last structural gap in the post-submission column was the poster. Read ARIS's paper-poster-html sources: templates/README.md, the three scaffold canvases, the six templates/tokens/*.json packs, and the _posterly/verify_final.py --from-html mechanism. The template README is explicit that the @page size and the poster container width/height must stay in sync and that every layout-critical element must keep its data-measure-role, because the measurement gate finds regions through those attributes. tools/ccfa/poster_html.py generates that HTML from data/poster-plan.yaml so the two sizes come from one computation and cannot drift; it ships the six token packs verbatim, supports the three documented layouts, marks poster/column/footer regions, and check re-derives the two sizes and requires all three roles. talk_gates verify-final gained --from-html: it parses the poster's own @page rule and checks the PDF against it, which is the reference's anti-drift rule (no default canvas that could be wrong by itself). The pdf subcommand prints through Edge/Chrome headless and reports rendered=false when no browser can print instead of pretending. Verified live on a Chinese ICML four-column poster: build produced 60x36in HTML with the figure copied, check was clean, Edge printed it, and verify-final --from-html measured the PDF at 4320x2592pt = 60x36in, exactly the declared canvas; the rendered PNG was inspected. Still not implemented: PPTX export, and the headless-Chromium column-alignment/fill measurement this host has no chain for.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/reference-aris-2026-10-06.md`
  - `scripts/poster-html.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/poster_html.py`
  - `tools/ccfa/talk_gates.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_poster_html.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_talk_gates.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_poster_html`
  - `tools.tests.test_scripts`
  - `tools.tests.test_talk_gates`
  - `tools.tests.test_test_impact`

## WC-20261006T095159Z-2c55709e32 - Measure a printed poster's column balance and fill

- timestamp: `2026-10-06T09:51:59Z`
- status: `complete`
- author: `codex`
- reason: The poster slice left one gate unimplemented: ARIS's _posterly/measure.py, the hard gate for column-bottom spread and gap to the footer. Its authoritative route is headless Chromium plus CDP Runtime.evaluate over getBoundingClientRect, and this host has no WebSocket client (websocket, websockets and pychrome all missing), so tools/ccfa/poster_measure.py measures the same contract on the printed PDF with PyMuPDF instead: white filled rectangles are the cards, horizontal overlap groups them into columns, and the lowest text block is the footer. The reference bands are kept in their own units by converting points to CSS-pixel equivalents at 96/72: spread aim below 3px with 5px a hard failure, footer gap aim 30-50px with anything outside 12-80px a hard failure, canvas fill 90-101% advisory. Nine tests verify the arithmetic against synthetic PDFs whose geometry is exact rather than against whatever a render happens to produce. Verified on a real ICLR portrait poster: measure reported spread 16.0px, gap 3178.5px and fill 7.3%, and check exited 1 with two problems and one advisory - the correct verdict, because poster_html generates structurally correct posters and column balance depends on how much content is placed; the reference README says an unfilled scaffold is expected to fail measure. Honest cost of the engine swap: measuring the print omits the DOM-only overflow check (scrollHeight vs clientHeight), so this slice covers column balance, footer gap and fill and nothing else.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/reference-aris-2026-10-06.md`
  - `scripts/poster-measure.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/poster_measure.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_poster_measure.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_poster_measure`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T095938Z-5cbdd3f706 - Add the static style gate for poster HTML

- timestamp: `2026-10-06T09:59:38Z`
- status: `complete`
- author: `codex`
- reason: ARIS's paper-poster-html splits its 12 design rules into a source gate (1,2,3,5,6,7,8,9,10,11: pure static analysis, no browser) and a render gate (4 and 12: computed style from Playwright), with 0/1/2 exit codes and warnings never failing the gate. tools/ccfa/poster_style.py implements that source gate for the posters this repository generates, keeping the reference rule numbering, severities, result shape and exit codes: colour literals only inside the design-token block located by its canonical comment pair, no inline style=, component colours via var(--...), font pairing and whitelist read from the token block, font-size only from the --fs-* scale (calc allowed only in a variant-suffix selector), a warning when more than nine --fs tokens are defined, and the radial tint alpha bound. Rules 4 and 12 and the component-library contracts 10/11 are reported as skip with a reason instead of being pretended. poster_html was adjusted so its output passes: it now emits the canonical DESIGN TOKENS comment pair and defines --font-serif/--font-sans/--font-mono from the reference whitelists (CJK falls back through the generic sans-serif rather than naming a family the gate bans). Verified live: a generated NeurIPS poster reports overall=pass with 0 hard failures and the four skipped rules listed on stderr, and tampering tests confirm rule 1 fails on a colour literal outside the token block, rule 2 on an inline style, rule 3 on a component rgb() literal, rule 7 on a non-whitelisted family and rule 8 on a raw font-size.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `scripts/poster-style.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/poster_html.py`
  - `tools/ccfa/poster_style.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_poster_style.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_poster_html`
  - `tools.tests.test_poster_style`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T101129Z-41807c94df - Export the talk plan as an editable PPTX

- timestamp: `2026-10-06T10:11:29Z`
- status: `complete`
- author: `codex`
- reason: The reference paper-slides contract ships both halves of a deck: a Beamer PDF and an editable PPTX with the speaker notes moved into the PowerPoint notes field, at the standard 16:9 (13.333x7.5in) or 4:3 (10x7.5in) canvas. talk_deck produced the PDF half; this adds tools/ccfa/pptx_export.py so the editable half comes from the same data/talk-plan.yaml and cannot disagree about which slides exist or what the notes say. It maps a Beamer-sized plan onto the standard canvas for its aspect, derives the point sizes from the canvas ratio instead of guessing (the reference uses a flat 1.6x hint; the achieved ratio is reported), writes speaker_notes into the PPT notes field, applies the venue accent colour, and sizes pictures by both width and the vertical room left after the title and bullets - the first live render showed a width-only picture running off the slide, which is the same failure mode the Beamer template had. This adds python-pptx 1.0.2 to tools/requirements.txt and regenerates tools/requirements.lock with the documented uv pip compile command. Verified live: the four-slide deck (title + two content + closing) converted through LibreOffice to a PDF measured at 959.981x540pt = 13.333x7.5in with verify-final reporting zero problems, and the rendered slide was inspected after the picture fix. Determinism caveat recorded in the module: core properties are pinned so core.xml is stable, but zip member timestamps come from the filesystem, so the PPTX is semantically rather than byte-by-byte reproducible.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `scripts/pptx-export.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/pptx_export.py`
  - `tools/ccfa/test_impact.py`
  - `tools/requirements.lock`
  - `tools/requirements.txt`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_pptx_export.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_pptx_export`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T101930Z-9178d12181 - Document the queue's resumed and gates output fields

- timestamp: `2026-10-06T10:19:30Z`
- status: `complete`
- author: `codex`
- reason: The full tool suite (which only runs when the lockfile changes) caught a latent doc/code drift from the earlier queue work: automation/experiment-queue.md promises the fields an automation may read, and test_automation_e2e compares that promise against a real run_queue result. Adding wave gating and resume added resumed and gates to the output and gate/wave-failed/gpu-budget to stopped, but the field list was never updated, so the documented set no longer matched the produced set. The list now names both new keys and the full set of stop reasons.
- files:
  - `automation/experiment-queue.md`
- tests:
  - `tools.tests.test_automation_e2e`

## WC-20261006T104727Z-2e4b3000f6 - Add the rendered poster style gate for rules 4 and 12

- timestamp: `2026-10-06T10:47:27Z`
- status: `complete`
- author: `codex`
- reason: The reference ARIS style_check.py splits its 12 poster design rules into a source gate (rules 1,2,3,5,6,7,8,9,10,11: pure static analysis, no browser) and a render gate (rules 4 and 12: needs computed style via Playwright), with --no-render keeping the source gate live while printing a notice that two rules were not evaluated, exit codes 0/1/2, and warnings that never fail the gate. This change implements the missing render half in tools/ccfa/poster_style.py. Rules 4 and 12 print-emulate the poster with Playwright at the poster's own @page viewport (W in * 96 CSS px), call page.emulate_media(media='print'), walk every element's computed style through the reference's _RENDER_JS (exempting <img>, [data-color-exempt], [data-source=paper] and QR subtrees), and then evaluate through a pure function: hue clustering with a greedy seed-anchored 18 degree circular sweep plus a wrap-around merge, a 0.10 alpha floor, perceptual chroma = HSL saturation * (1 - |2L-1|) with a 0.10 floor so near-white and near-black tints stay neutral, a hard fail above 2 clusters, a 22 degree tolerance against the --accent/--gold hue centres resolved from the token block or a --tokens JSON, and a 0.08 poster-area warn for dark backgrounds (bg lightness < 0.18 at alpha >= 0.5). Constants and the colorsys.rgb_to_hls (h, l, s) unpack order are transcribed verbatim from the reference. One correction: the reference declares rule 12 and rule 9 as severity 'warn', not hard/soft, so RULE_SEVERITY was fixed to warn for both. Browser resolution avoids a fresh download: the gate tries channel msedge then chrome then the bundled chromium, so an installed Edge on Windows and on the windows-latest CI runner is enough; when no browser is usable the CLI returns exit 2 instead of pretending to pass, and --no-render is the documented way to run the source gate alone. check() keeps render=False as its programmatic default and the CLI defaults to rendering; the JSON report gained a render block recording requested/evaluated/engine/viewport_px/hue_centers. poster_style is the second new dependency (playwright==1.63.0, previously python-pptx) and the lock file was regenerated with hashes; only playwright, greenlet and pyee were added, no existing pin moved. Verified live on a generated ICLR portrait poster at a 2304x3456 px viewport with engine msedge: overall=pass, rule 4 reports '1 hue cluster within the 22 degree palette tolerance', rule 12 reports 'dark area = 0.0% of poster'. Three constructive experiments: adding a third hue family (accent 151 + gold 42 + probe 336) makes rule 4 hard-fail with '3 non-neutral hue clusters'; switching --bg-page to #0B0B0B warns rule 12 while overall stays pass; the same green probe inside a data-color-exempt=logo subtree passes rule 4 and fails once the attribute is removed, proving the exemption is honoured. 35 tests in tools/tests/test_poster_style.py cover the source rules, the pure hue/chroma/cluster maths, the rule 4 and 12 thresholds without a browser, the CLI --no-render and exit-2 paths, and (skipping cleanly when no browser exists) real Playwright renders. Docs updated: docs/reference-aris-2026-10-06.md gained the fifteenth slice (poster style gate) and the sixteenth slice (the earlier PPTX export, which had shipped without documentation), and docs/aris-comparison-2026-10-06.md rows now mark the post-submission depth gap closed.
- files:
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/reference-aris-2026-10-06.md`
  - `tools/ccfa/poster_style.py`
  - `tools/requirements.lock`
  - `tools/requirements.txt`
  - `tools/tests/test_poster_style.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_packaging`
  - `tools.tests.test_poster_style`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T112044Z-9b638ef5a8 - Close the patent, domain-adapter, knowledge-base and external-benchmark gaps

- timestamp: `2026-10-06T11:20:44Z`
- status: `complete`
- author: `codex`
- reason: Closes the four remaining ARIS-alignment gaps from docs/aris-comparison-2026-10-06.md: the patent chain, domain adapters, knowledge-base automation, and external benchmark evaluation.

Patent chain (new tools/ccfa/patent.py + scripts/patent.ps1): after reading ARIS patent-pipeline, claims-drafting, invention-structuring, jurisdiction-format and patent-review, this implements the mechanically checkable half as a gate over a patent/ directory. check_state validates PATENT_STATE.json (phase/status/jurisdiction/type, utility_model must be CN, and an in_progress state older than 24h is a stale advisory for compaction recovery); INVENTION_DISCLOSURE.md must carry the core/supporting/optional decomposition; check_claims enforces sequential claim numbering with no gaps, the per-type minimum independent-claim count, dependent claims referencing an earlier claim, the jurisdiction characterising phrase on every independent claim (CN 其特征在于, US comprising, EP characterised in that), and the utility-model restriction (CN only, no method claims), with >20 claims as an advisory only; PRIOR_ART_REPORT.md needs at least three locatable URL/DOI references; patent-review.yaml must have every objection resolved with a resolution; check_output validates each compiled output/<J>/ tree for claim completeness, jurisdiction-specific abstract limits (CN 300 characters, US/EP 150 words), language matching and shared reference numerals. format re-assembles the canonical specification sections in CNIPA / USPTO / EPO Rule 42 order and deliberately does not translate, so a Chinese claim pasted into a US filing is caught by patent-output-language rather than silently translated. It also fixes a real claim parser bug found while testing: the body slice started after the claim's own first line, so a claim's characterising phrase and every dependency were invisible.

Domain adapters (new tools/ccfa/domain_adapters.py + scripts/domain-adapters.ps1): robotics, communications and architecture-EDA packs with venues, search terms, pilot mode and required elements (embodiment/task_family/observation_action/simulator/sim2real_story/evaluation, system_model/channel_model/protocol_baseline/traffic_model/evaluation_stack/metrics, workload/technology_node/simulator/area_power_model/ppa/baseline). check fails closed on a missing required element or a placeholder value and treats an off-list venue as an advisory; prompt prints a paste-ready constraint block. This is the machine-checkable form of the per-domain prose that ARIS keeps in idea-discovery-robot and comm-lit-review.

Knowledge-base automation (tools/ccfa/research_wiki.py): adds ingest (paper scaffolds from BibTeX, a PDF dir or arXiv ids, with the twelve-section body and the two protected sections), enrich-report, enrich (fills named sections from JSON, refusing protected sections and refusing text flagged by the capture-hygiene screen), screen (env-failure / transient-error / negative-tool-claim patterns, so an operational accident cannot harden into a durable research fact), and hook (ingest -> enrich -> rebuild -> log). It also fixes a real bug: rebuild_catalog, query_pack and append_log generate index.md, gap_map.md, query_pack.md and log.md, but check_wiki only skipped README.md, so a rebuild made the wiki immediately invalid with research-wiki-invalid missing frontmatter; generated catalogues are now skipped and rebuild leaves the wiki valid.

External benchmark harness (tools/ccfa/tool_eval.py --benchmark): an MLGym-style spec with per-task command, optional workdir, metric {path, key} and threshold. Grading is three-state: pass at/above threshold, fail on non-zero exit or below threshold or an unreadable metric, and unavailable when the command or working directory does not exist, with unavailable tasks excluded from the pass denominator exactly like errored probes. The metric path must stay inside the task workdir. A completed run exits 0 because this is a measurement, not a gate. docs/examples/benchmark-example.yaml ships the spec shape. Honest limitation, recorded in the docs: no external benchmark task (MLGym or otherwise) was actually executed this round, so the score remains blank.

Wiring: dispatch gains patent and domain-adapters commands; scripts/domain-adapters.ps1 and scripts/patent.ps1 are thin wrappers; CCFA_WRAPPERS in test_scripts, CLI_WRAPPERS in test_docs_consistency, the py_compile list in .github/workflows/tests.yml, and the test_impact mappings all move together with the two new modules; README documents the new tools, the patent chain, the domain packs, the wiki hook and the external benchmark. Tests: 36 in tools/tests/test_patent.py, 15 in tools/tests/test_domain_adapters.py, 16 added to tools/tests/test_tool_eval.py, plus the updated research_wiki, docs-consistency, scripts, dispatch and test-impact suites.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `docs/aris-comparison-2026-10-06.md`
  - `docs/examples/benchmark-example.yaml`
  - `docs/reference-aris-2026-10-06.md`
  - `scripts/domain-adapters.ps1`
  - `scripts/patent.ps1`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/domain_adapters.py`
  - `tools/ccfa/patent.py`
  - `tools/ccfa/research_wiki.py`
  - `tools/ccfa/test_impact.py`
  - `tools/ccfa/tool_eval.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_domain_adapters.py`
  - `tools/tests/test_patent.py`
  - `tools/tests/test_scripts.py`
  - `tools/tests/test_test_impact.py`
  - `tools/tests/test_tool_eval.py`
- tests:
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_domain_adapters`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_patent`
  - `tools.tests.test_research_wiki`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`
  - `tools.tests.test_tool_eval`

## WC-20261006T113229Z-224ab31b20 - Fourth round of the ARIS comparison: every remaining structural gap is closed; record the new priorities.

- timestamp: `2026-10-06T11:32:29Z`
- status: `complete`
- author: `codex`
- reason: The repo closed the compute, self-evolution, figure/poster/slides, patent, domain-adapter, knowledge-base and benchmark gaps (modules 89 to 100, tests 1866 to 2227), so the comparison needed to record that no structural gap remains and to shift the recommendations to the paper's own blockers.
- files:
  - `docs/aris-comparison-2026-10-06.md`
- tests:
  - `tools.tests.test_docs_consistency (17 tests)`
  - `tools.unittest discover (2227 tests)`
- notes: Also records the current environment regression (docker daemon and zotero unreachable, 2 advisories), the four cross-review blockers, and that reviews/adversarial-review.json has still not been produced.

## WC-20261006T122230Z-4525cb7c4d - Add the anonymity gate and wire it into readiness from internal-review

- timestamp: `2026-10-06T12:22:30Z`
- status: `complete`
- author: `codex`
- reason: Closes the one real capability gap found by a full re-comparison against ARIS: anonymity / double-blind was asserted by the checklists but enforced by nothing. checklists/conference.md and checklists/journal.md both list 匿名 as a pass condition of the submission-check gate, yet the only code that touched anonymity was resubmit_pipeline (which validates re-submission targets, not the submitted manuscript), and neither venue_fixtures nor final_check looked at it. For a double-blind venue that is a desk-reject risk: an author name, an acknowledgements section, self-referential phrasing, a self-owned repository URL or PDF metadata all leak identity, and the workflow only reminded the author in prose.

New tools/ccfa/anonymity.py + scripts/anonymity.ps1 implements a fail-closed gate over manuscript/*.tex and any built PDFs. Hard problems: an \author{...} block that is not an anonymous marker; a real author name or affiliation declared in data/anonymity.yaml appearing in the sources; self-referential phrasing that identifies the authors through their own citations (our previous work, we previously showed, in our prior work, and the Chinese equivalents 我们之前的工作 / 我们之前提出); an author-owned URL declared in self_urls; and PDF metadata (Author/Title/Subject/Keywords/Creator/Producer) carrying a real name, an affiliation, or a non-anonymous Author value. Judgement calls stay advisories so the gate cannot force a false statement: an acknowledgements section is an advisory by default because venues such as CSF require the AI-use disclosure there (set acknowledgements: forbidden in the config to escalate it to a problem), and an unlisted code-hosting URL is an advisory because a third-party artifact URL is legitimate. Comment-only lines are ignored so a name in a % note does not fail. Config data/anonymity.yaml is optional (blind/authors/affiliations/self_urls/allow/acknowledgements); without it the gate runs the generic double-blind checks with an empty name list.

Wiring: dispatch gains the anonymity command, scripts/anonymity.ps1 is a thin wrapper, CCFA_WRAPPERS, CLI_WRAPPERS, the py_compile list in .github/workflows/tests.yml and the test_impact mapping all move together with the new module, and README documents the gate. readiness now runs anonymity as a first-class gate from the internal-review stage onwards (minimal profile excluded) via a new _stage_at_least helper, with mode threaded through _run_gates so journal papers get the journal stage order.

Tests: 26 new in tools/tests/test_anonymity.py (config defaults and validation, author name / affiliation / self-reference in both English and Chinese, ordinary first-person prose not flagged, non-anonymous and anonymous author blocks, comment lines ignored, self-url vs unlisted-url vs allow-listed-url, acknowledgements advisory vs forbidden, missing manuscript, PDF metadata created with PyMuPDF, and CLI exit codes), plus the readiness, docs-consistency, scripts, dispatch and test-impact suites. Verified live: the flagship paper now reports the anonymity gate as pass with 0 problems and 1 advisory (the acknowledgements notice) and its blocking list is unchanged, so the gate does not invent work.
- files:
  - `.github/workflows/tests.yml`
  - `README.md`
  - `scripts/anonymity.ps1`
  - `tools/ccfa/anonymity.py`
  - `tools/ccfa/dispatch.py`
  - `tools/ccfa/readiness.py`
  - `tools/ccfa/test_impact.py`
  - `tools/tests/test_anonymity.py`
  - `tools/tests/test_docs_consistency.py`
  - `tools/tests/test_scripts.py`
- tests:
  - `tools.tests.test_anonymity`
  - `tools.tests.test_dispatch`
  - `tools.tests.test_docs_consistency`
  - `tools.tests.test_github_workflows`
  - `tools.tests.test_readiness`
  - `tools.tests.test_scripts`
  - `tools.tests.test_test_impact`

## WC-20261006T130059Z-dff4722a73 - Run review harness calls with MCP servers disabled

- timestamp: `2026-10-06T13:00:59Z`
- status: `complete`
- author: `codex`
- reason: Review harness invocations were paying a large fixed startup tax that had nothing to do with the review itself. `codex exec` stands up every MCP server in the user config before it calls the model, and several of the 14 configured servers fail their handshake or need auth (notion, linear, canva, sentry, a local 127.0.0.1:8080 endpoint), each with retries. Measured on this machine with a one-word prompt against the zhipu provider: 205.2 seconds with MCP enabled, 16.6 seconds with `-c mcp_servers={}` — a 12x difference, and the ~30.5k tokens of harness overhead is paid either way. The review roles only read files through the read-only sandbox, so MCP is not needed for a verdict.

Added HARNESS_MCP_OFF = ("-c", "mcp_servers={}") in tools/ccfa/cross_review.py and applied it to all three harness argv builders (cross_review.run, adversarial_review.run_review, meta_apply.review), so cross-model reviews, the adversarial roles and the meta-apply jury all start in seconds instead of minutes. The flag is inserted right after `exec`, before the provider/effort overrides, so a caller-supplied provider still wins.

Tests: a new assertion in test_cross_review.test_argv_has_exact_required_flags_and_stdin_prompt, a new test in test_adversarial_review (test_the_harness_runs_with_mcp_servers_disabled) and a new assertion in test_meta_apply.test_review_resolves_a_provider_per_model, each pinning `mcp_servers={}` in the captured argv. 133 tests in the three modules pass; ruff clean.
- files:
  - `tools/ccfa/adversarial_review.py`
  - `tools/ccfa/cross_review.py`
  - `tools/ccfa/meta_apply.py`
  - `tools/tests/test_adversarial_review.py`
  - `tools/tests/test_cross_review.py`
  - `tools/tests/test_meta_apply.py`
- tests:
  - `tools.tests.test_adversarial_review`
  - `tools.tests.test_cross_review`
  - `tools.tests.test_meta_apply`

## WC-20261006T130834Z-df7d41fdb6 - Align the anonymity gate with ARIS's documented 5-layer spec

- timestamp: `2026-10-06T13:08:34Z`
- status: `complete`
- author: `codex`
- reason: Aligned the anonymity gate with ARIS's actual spec after checking what ARIS really ships. ARIS has no anonymity source code: the resubmit-pipeline hygiene rules live in skills/resubmit-pipeline/SKILL.md as a prose "5-layer anonymity check" plus a couple of grep regexes, and a repo-wide search for an anonymity script finds none (the only .py that mentions the terms is extract_paper_style.py, unrelated). So the alignment here is spec-level, not a vendored file.

Two layers ARIS documents that the first implementation missed are now covered, and both matter for a double-blind venue:

- Layer 4, cross-rebuttal references: "this revision addresses reviewer 2's concern from the prior submission", "rebuttal at <venue>", "resubmission of", "addressing reviewer N", and the Chinese equivalents (上次投稿 / 之前被拒 / 审稿意见). ARIS's own note is that this is equally blocking as a leaked name, because it breaks anonymity and advertises a prior rejection. These are hard problems (anonymity-cross-rebuttal).
- Layer 5, internal codenames and workspace links: a configured codenames list is a hard problem (anonymity-codename) and generic internal-workspace signals (Slack channel/workspace, Confluence/Atlassian, "internal wiki/repo/tracker") are advisories (anonymity-internal-link), because the string alone does not prove it identifies the lab.

Also adopted from the same spec: acknowledgements are now detected as a macro (\acknowledgments{...} / \begin{acknowledgments}) and as a standalone acknowledgments.tex, not only as a \section*{Acknowledgments}; and ARIS's separate "residual coloring / margin-note scan" (leftovers such as \revise{} / \fix{} / \todo{} / \todonotes{} / \textcolor{red}{}) is reported as advisories, matching ARIS's own "list them; the user decides" stance. Config gains the optional codenames key.

Tests: 7 new cases in tools/tests/test_anonymity.py (English and Chinese cross-rebuttal, codename hit, internal-link advisory, residual-markup advisory, acknowledgements macro, standalone acknowledgments file). 33 tests in the module pass and ruff is clean. Verified live on the flagship paper: still 0 problems and the same single acknowledgements advisory, so the new layers do not invent findings.
- files:
  - `tools/ccfa/anonymity.py`
  - `tools/tests/test_anonymity.py`
- tests:
  - `tools.tests.test_anonymity`

