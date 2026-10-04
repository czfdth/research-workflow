# 论文工作台 app

`ccfa_core` 是零 Qt 依赖的核心层：项目发现、设置、密钥与检查编排。
GUI 在 `app/ccfa_gui/`。

## 环境

需要 Python 3.12（本仓库用 3.12.14 实测）。在仓库根执行：

```powershell
py -3.12 -m venv app/.venv
& app/.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

若本机没有 `py`，改用你机器上的 Python 3.12 解释器完整路径，例如：
`<你机器上的 Python 3.12> -m venv app/.venv`。

`app/.venv` 已被 gitignore。`ccfa_core` 直接 import 现有 `ccfa.*` 工具模块，
因此测试时需要 `PYTHONPATH=tools`；app venv 中的 PyYAML 供这些模块使用。

## 跑测试

```powershell
cd <仓库根>
$env:PYTHONPATH = (Resolve-Path tools).Path
& app/.venv/Scripts/python.exe -m unittest discover -s app/tests -t app
```

## 启动 GUI

```powershell
cd app
$env:PYTHONPATH = (Resolve-Path ../tools).Path
& .venv/Scripts/python.exe -m ccfa_gui.main
```

## 红线

- `ccfa_core` 不 import PySide6（E58）。
- `settings.json` 只写 `key_name` 引用，不写 key 明文；密钥只进
  `KeyringSecretStore`（E57）。
- keyring 不可用时抛 `SecretStoreUnavailable`，不降级明文。

## 引擎与取消

- `OpenAICompatibleEngine` 的取消是协作式的：只在请求边界生效，最坏等待当前
  HTTP 请求完成或超时（`timeout_s` 兜底）；正在飞行中的请求不会被中途打断。
- `CodexExecEngine` 的取消会立即 kill 子进程。
- 引擎错误消息不包含 `SecretStore.get()` 的原始异常文本（可能嵌入 key），
  只带异常类型名。

## 自定义 HTTP 工具

`ccfa_core/http_tools.py` 提供声明式 HTTP 工具注册表。它只读 YAML，不执行任意
代码：v1 只支持 GET/POST；`http://` 需显式 `allow_http: true`；敏感头必须写成
`secret:<key_name>` 并由 keyring 取值——判定按名字，任何含
token/key/auth/secret/credential/password 的头都算敏感，明文凭据是加载错误；
占位符必须在 `parameters` 中声明；压缩响应默认拒绝（解压会在限流前吃内存），
确需时写 `allow_compressed: true`；任一工具非法则整份注册表不加载。格式与示例见
仓库根 `README.md` 的「论文工作台（P2）」一节。

`ToolBridge(project_root, http_tools=HttpToolRegistry(...))` 会把注册的工具与内置
工具合并：同一套参数校验、写操作确认与审计（只记参数摘要）。
