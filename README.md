# paper-template

论文工作流模板库。每篇论文派生一份独立目录。

设计文档：`C:/Users/best/Documents/Codex/2026-10-03/wo/outputs/2026-10-03-research-workflow-design.md`

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `ccfa.yaml.template` | 新项目状态文件模板 |
| `checklists/` | gate 清单，由 `tools/ccfa/stages.py` 生成 |
| `library/` | 共享 BibTeX 与 PDF 原件 |
| `library/refs.bib` | 共享 BibTeX 条目；派生项目时复制为 `manuscript/references.bib` |
| `tools/` | 确定性工具（Python） |

## 派生一篇新论文

```powershell
$root = "C:/Users/best/Documents/Codex/paper-template"
$env:PYTHONPATH = "$root/tools"
$venv = "$root/tools/.venv/Scripts/python.exe"
& $venv "$root/tools/newpaper/create.py" my-paper `
    --venue NeurIPS --year 2027 --mode conference --title "My Paper"
```

## 重新生成 checklist

```powershell
& $venv "$root/tools/newpaper/checklists.py"
```

## 校验状态文件

```powershell
& $venv "$root/tools/ccfa/validate.py" path/to/ccfa.yaml
```

退出码：`0` 通过，`1` 发现问题，`2` 工具自身出错。

## 跑测试

```powershell
cd $root
& $venv -m unittest discover -s tools/tests -t tools -v
```

## 已知环境约束

- 编译不使用 `latexmk`（本机缺 Perl，实测报 `could not find the script engine 'perl'`）。编译驱动按 `pdflatex → bibtex → pdflatex → pdflatex` 显式执行。
- 中文文稿用 `xelatex` 加 `ctex`，已实测通过。
- 文献库索引用于中文时必须使用 FTS5 `trigram` 分词器；`unicode61` 对中文完全无效。
