# 科研工作流缺口与完善清单

日期：2026-10-05（第五轮修复）

## 一句话结论

第四轮发现的 2 个工程 bug 本轮均已修复：两个 E2E 测试已补显式模型与隔离
Codex config，CI 已覆盖对应模块；doctor 已兼容 provider 的 `models[].slug`
响应结构。真实 provider 现在为 `functional`，全量工具测试 1211 项通过。剩余阻塞
集中在人工证明/引用/图表复核、真人双编码、旧 cross-review 记录和容器级复现。

## 第五轮已修复

| 问题 | 修复与证据 |
| --- | --- |
| BUG-NEW-1 全量测试红、CI 子集看不到 | 两个 E2E 补 `model=deepseek-v4-pro` 与临时 `codex_config`；CI 加入 `test_automation_e2e`、`test_evidence_integrity_e2e` |
| BUG-NEW-2 doctor provider 假警报 | `_probe_http_service` 同时解析 `data[].id` 与 `models[].id/slug`；真实 doctor 返回 `functional provider 配置模型可用` |
| 全量测试可信度 | `python -m unittest discover -s tools/tests -t tools` -> `Ran 1211 tests, OK` |

## 一、本轮已修复

| 上轮问题 | 状态 | 证据 |
| --- | --- | --- |
| BUG-1 CI 参数错配 | 已修复 | 两个 workflow 的 `citation_guard` 与 `trace_claims` 都改成正确参数 |
| `trace_claims` 不支持目录 | 已修复 | 新增 `--manuscript`，等价于对目录下所有 `.tex` 传 `--doc` |
| BUG-2 缺少 workflow↔CLI 守护测试 | 已修复 | 新增 `test_main_paper_commands_are_parseable` / `test_paper_repository_commands_are_parseable` |
| BUG-3 governance 接受 pending 文本 | 已修复 | 现在报 3 个 `governance-placeholder`，exit 1 |
| BUG-7 复现包不声明依赖 | 已修复 | `MANIFEST.json.requirements` 已回填，lockfile 哈希已对齐 |
| `repro_env` 哈希漂移 | 已修复 | `problem_count=0`，exit 0 |

CI 命令逐条复现结果（论文仓库根目录）：

```text
validate        0
citation_guard  0
trace_claims    0
novelty         0
stats_plan      0
governance      1   <- 真实问题：COI / 查重 / 披露联系人仍是 pending
repro_env       0
argument_audit  1   <- 真实问题：proof 0/8、citation 0/6、figure 0/1
latex_check     0
final_check     0
run_log         0
```

## 二、本轮新发现的 bug

### BUG-NEW-1（P0，已修复）：全量测试变红但 CI 检测不到

```text
python -m unittest discover -s tools/tests -t tools
-> Ran 1209 tests, FAILED (errors=2)
```

两个 error 同源：`cross_review.run_review` 现在要求显式 `--model`（工作流不再替调用方选模型），但两个 E2E 测试仍在无 `model` 的情况下调用它：

```text
tools/tests/test_automation_e2e.py:378
  AutomationEndToEndTests.test_cross_review_blocking_record_is_reported_by_check

tools/tests/test_evidence_integrity_e2e.py:252
  EvidenceIntegrityEndToEnd.test_fabricated_cross_review_quote_is_uncited

ValueError: 跨模型评审必须显式提供 --model
```

更值得注意：`.github/workflows/tests.yml` 的 targeted 列表只包含
`test_cross_review / test_doctor / test_readiness / test_repro_package /
test_run_log_e2e / test_docs_consistency / test_github_workflows / test_scripts`，
**不包含** `test_automation_e2e` 与 `test_evidence_integrity_e2e`。所以 CI 会保持绿色，而本地全量测试是红的。

修复：两个测试显式传 `model=deepseek-v4-pro` 和隔离的 `codex_config`；CI
targeted 列表加入 `test_automation_e2e`、`test_evidence_integrity_e2e`。
workflow 守护测试同时要求这两个模块保留在 CI。

### BUG-NEW-2（P1，已修复）：doctor 对本地 provider 的模型列表判断错误

`tools/ccfa/doctor.py::_probe_http_service` 只读 OpenAI 风格的响应结构：

```python
data = payload.get("data")
model_ids = {item.get("id") for item in data ...}
```

但本机 provider（`127.0.0.1:15721`）返回的是另一种结构：

```text
顶层键: models
条目字段: slug
实际列表: deepseek-v4-flash, deepseek-v4-pro, deepseek-flash
```

配置模型 `deepseek-v4-flash` 确实在列表里，但因为代码只找 `data[].id`，`model_ids` 为空集合，于是误报：

```text
authenticated provider  配置模型不在模型列表中
provider: doctor-service-not-functional
```

这是与上一轮相反方向的缺陷：不是假绿，而是**假警报**。修复后
`_probe_http_service` 同时兼容 `data[].id` 与 `models[].id/slug`；真实 doctor
已确认 `functional provider 配置模型可用`。剩余 service advisories 只有 Docker
daemon、WorkBuddy 和 Zotero。

## 三、仍然阻塞科研结论的问题（不是 bug，是未完成）

| 项 | 状态 |
| --- | --- |
| `proof-audit.yaml` | 8 条全部 pending，人工复核 0/8 |
| `citation-support.yaml` | `supports: []`，0/6 |
| `figure-support.yaml` | `figures: []`，0/1 |
| `human-coding-report.json` | `pending-human-dual-coding` |
| `scientific-acceptance.yaml` | 不存在，`scientifically-accepted: not-claimed` |
| `governance.yaml` | COI / 查重 / 披露联系人均为 pending |
| `reviews/cross-review.json` | `provider=null`、`same-family`、`verdict=pass`，且 `review-stale ×4`、`review-provenance-incomplete`、`review-prompt-unknown` |

`readiness` 当前 `ready=false`，blocking 正是：

```text
argument-audit gate failed: proof-review-not-verified ×5
cross-review gate failed: review-provenance-incomplete, review-stale ×4
```

这说明 readiness 现在能反映真实状态，是可用的。

## 四、环境与运维

| 项 | 状态 |
| --- | --- |
| Docker daemon | 不可达 |
| WorkBuddy `:8787` | 连接被拒 |
| Zotero `:23119` | 连接被拒 |
| `doctor` 退出码 | 0（以上均为 advisory；投稿前应用 `--strict`） |
| `PAPER_REPOSITORY_TOKEN` / `RESEARCH_WORKFLOW_TOKEN` | 未验证（本机无 `gh` CLI） |
| 跨仓库 workflow 触发方式 | 手动，不是每次 push 自动验证论文 |
| Zenodo / OSF / ORCID | 未接入 |

## 五、优先行动清单

### P0

1. 完成 proof（0/8）、citation（0/6）、figure（0/1）人工复核与真人双编码。

### P1

1. 重新生成 `cross-review.json`，使用显式跨族模型并写入完整 provenance。
2. 把 `governance.yaml` 的 COI、查重工具、披露联系人换成真实值。
3. 配置并验证两个 PAT secret，让跨仓库 CI 真正跑一次。

### P2

1. 启动 Docker、WorkBuddy、Zotero，使 `doctor --strict` 归零。
2. 补容器或第二环境复现证据。
3. 接入 ORCID，录用后接入 Zenodo/OSF。

## 六、当前最短路径

1. 完成人工证明复核与真人双编码，让 argument-audit 从 blocking 转 pass。
2. 用真实跨族模型重跑 cross-review，让 provenance 完整、评审不再 stale。
