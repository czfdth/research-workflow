# Workflow Change Log

Generated from `docs/workflow-change-log.jsonl`. Append-only; do not
rewrite historical entries.

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

## WC-20261005T165038Z-048c83d06d - Let the public mirror drop the private workflow change-log gate

- timestamp: `2026-10-05T16:50:38Z`
- status: `complete`
- author: `codex`
- reason: The mirror diff is not the private commit diff, so the change-log gate cannot be satisfied there; publish-public.ps1 now removes named workflow steps on the mirror via config.
- files:
  - `scripts/publish-public.ps1`
- tests:
  - `tools.tests.test_scripts`

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

