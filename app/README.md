# 论文工作台 app

`ccfa_core` 是零 Qt 依赖的核心层：项目发现、设置、密钥与检查编排。
GUI 将放在后续的 `app/ccfa_gui/`。

## 环境

需要 Python 3.12（本仓库用 3.12.14 实测）。在仓库根执行：

```powershell
& 'C:/Users/best/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -m venv app/.venv
& app/.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

`app/.venv` 已被 gitignore。`ccfa_core` 直接 import 现有 `ccfa.*` 工具模块，
因此测试时需要 `PYTHONPATH=tools`；app venv 中的 PyYAML 供这些模块使用。

## 跑测试

```powershell
cd <仓库根>
$env:PYTHONPATH = (Resolve-Path tools).Path
& app/.venv/Scripts/python.exe -m unittest discover -s app/tests -t app
```

## 红线

- `ccfa_core` 不 import PySide6（E58）。
- `settings.json` 只写 `key_name` 引用，不写 key 明文；密钥只进
  `KeyringSecretStore`（E57）。
- keyring 不可用时抛 `SecretStoreUnavailable`，不降级明文。
