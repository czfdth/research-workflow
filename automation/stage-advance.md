# Stage Advance Prompt

读取论文状态、定位当前阶段，并给出下一步建议动作；不自动推进状态。

## 命令

```powershell
$ROOT = "<repo-root>"
$PAPER_ROOT = "<paper-root>"
$env:PYTHONPATH = "$ROOT/tools"
& "$ROOT/tools/.venv/Scripts/python.exe" "$ROOT/tools/ccfa/validate.py" "$PAPER_ROOT/ccfa.yaml"
& "$ROOT/tools/.venv/Scripts/python.exe" "$ROOT/tools/ccfa/milestones.py" due `
    --paper-root "$PAPER_ROOT" --today "<YYYY-MM-DD>"
```

## 读取字段

- `stage.current`：当前阶段。
- `stage.gate`：当前 gate。
- `stage.updated_at`：最近更新时间。
- milestones JSON 的 `mode`, `due`, `missing_gates`。

## 通知规则

- 阶段和 gate 没有变化时，没有实质变化就不通知。
- 只报告当前 `stage.current`、`stage.gate` 和建议动作，不自动改写状态。
- gate 缺口只引用脚本输出，不凭印象推断完成情况。

## 安全边界

不得修改论文正文与 `ccfa.yaml` 的结论字段；推进 stage 需要用户明确授权。
