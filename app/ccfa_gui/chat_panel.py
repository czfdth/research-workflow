"""Chat panel: engine selection, message list and background execution.

The engine itself always runs on a worker thread; replies, failures and
stop notifications come back to the GUI thread through Qt signals.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ccfa_core.engines.base import ChatMessage, EngineError
from ccfa_core.engines.codex_exec import CodexExecEngine
from ccfa_core.engines.openai_compat import OpenAICompatibleEngine
from ccfa_core.secrets import KeyringSecretStore, SecretStoreUnavailable
from ccfa_core.settings import load_settings

ENGINE_OPENAI = "openai"
ENGINE_CODEX = "codex"

ROLE_PREFIXES = {
    "user": "你",
    "assistant": "助手",
    "error": "错误",
    "stopped": "已停止",
}
ROLE_COLORS = {
    "user": QColor("#1a4d8f"),
    "assistant": QColor("#1b5e20"),
    "error": QColor("#b00020"),
    "stopped": QColor("#8a6d00"),
}


def default_engine_factory(*, kind, model, settings, secret_store):
    """Build the engine selected in the combo box.

    ``settings`` is None for codex (no provider is required); OpenAI-compatible
    engines use the active provider and resolve the key from ``secret_store``.
    """
    if kind == ENGINE_CODEX:
        return CodexExecEngine(model=model)
    if settings is None or settings.provider is None:
        raise ValueError("未配置 provider")
    provider = settings.provider
    return OpenAICompatibleEngine(
        base_url=provider.base_url,
        model=provider.model,
        secret_store=secret_store,
        key_name=provider.key_name,
        timeout_s=provider.timeout_s,
    )


class ChatPanel(QWidget):
    """Chat UI with a background engine worker."""

    reply_ready = Signal(object)
    run_failed = Signal(str)
    run_stopped = Signal(str)
    run_finished = Signal()

    def __init__(
        self,
        settings_path: Path,
        *,
        secret_store=None,
        engine_factory=None,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_path = Path(settings_path)
        self._secret_store = (
            secret_store if secret_store is not None else KeyringSecretStore()
        )
        self._engine_factory = engine_factory or default_engine_factory
        self._history = []
        self._thread = None
        self._cancel_event = None
        self._running = False
        self._in_flight_text = ""
        self._build_ui()
        self.reply_ready.connect(self._on_reply)
        self.run_failed.connect(self._on_failed)
        self.run_stopped.connect(self._on_stopped)
        self.run_finished.connect(self._on_run_finished)
        self._on_engine_changed()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("引擎"))
        self.engine_combo = QComboBox()
        self.engine_combo.setObjectName("engine_combo")
        self.engine_combo.addItem("OpenAI 兼容", ENGINE_OPENAI)
        self.engine_combo.addItem("codex exec", ENGINE_CODEX)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        top.addWidget(self.engine_combo)
        self.model_label = QLabel("Codex 模型（可选）")
        self.model_edit = QLineEdit()
        self.model_edit.setObjectName("codex_model_edit")
        self.model_edit.setPlaceholderText("留空使用 codex 默认模型")
        top.addWidget(self.model_label)
        top.addWidget(self.model_edit, stretch=1)
        layout.addLayout(top)

        self.message_list = QListWidget()
        self.message_list.setObjectName("chat_messages")
        self.message_list.setWordWrap(True)
        layout.addWidget(self.message_list, stretch=1)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("chat_hint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("chat_input")
        self.input_edit.setPlaceholderText("输入消息，Ctrl+Enter 发送")
        self.input_edit.setFixedHeight(90)
        self.input_edit.textChanged.connect(self._update_send_enabled)
        layout.addWidget(self.input_edit)

        buttons = QHBoxLayout()
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("chat_send_button")
        self.send_button.clicked.connect(self.send_message)
        buttons.addWidget(self.send_button)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("chat_stop_button")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.hide()
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.send_shortcuts = [
            QShortcut(
                QKeySequence("Ctrl+Return"),
                self,
                activated=self.send_message,
            ),
            QShortcut(
                QKeySequence("Ctrl+Enter"),
                self,
                activated=self.send_message,
            ),
        ]
        for shortcut in self.send_shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._update_send_enabled()

    def _kind(self) -> str:
        return self.engine_combo.currentData()

    def _on_engine_changed(self, *_args) -> None:
        is_codex = self._kind() == ENGINE_CODEX
        self.model_label.setVisible(is_codex)
        self.model_edit.setVisible(is_codex)
        self.refresh_status()

    def refresh_status(self) -> None:
        """Refresh the pre-send hint from the current settings and keyring."""
        if self._running:
            return
        if self._kind() == ENGINE_CODEX:
            self._set_hint("codex exec：使用本机 CLI，模型可留空")
            return
        try:
            settings = load_settings(self._settings_path)
        except ValueError as exc:
            self._set_hint(f"设置读取失败: {exc}")
            return
        provider = settings.provider
        if provider is None:
            self._set_hint("未配置 provider：请先在设置中填写 API 配置")
            return
        try:
            value = self._secret_store.get(provider.key_name)
        except SecretStoreUnavailable as exc:
            self._set_hint(f"凭据后端不可用: {exc}")
            return
        except Exception as exc:
            self._set_hint(f"无法读取凭据: {exc}")
            return
        if not isinstance(value, str) or not value.strip():
            self._set_hint("未配置 API key：请在设置中保存密钥")
            return
        self._set_hint(f"Provider: {provider.name} / {provider.model}")

    def send_message(self) -> None:
        """Send the input box content through the selected engine."""
        if self._running:
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        prepared = self._prepare_engine()
        if prepared is None:
            return
        engine, timeout_s = prepared
        self._append_message("user", text)
        self._history.append(ChatMessage("user", text))
        self._in_flight_text = text
        self.input_edit.clear()
        self._set_hint("")
        self._set_running(True, getattr(engine, "name", "engine"))
        self._start_worker(engine, list(self._history), timeout_s)

    def stop(self) -> None:
        """Ask the running engine to stop; the worker finishes the UI state."""
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._set_hint("正在停止...")

    def _prepare_engine(self):
        kind = self._kind()
        model = self.model_edit.text().strip()
        if kind == ENGINE_CODEX:
            try:
                engine = self._engine_factory(
                    kind=kind,
                    model=model,
                    settings=None,
                    secret_store=self._secret_store,
                )
            except Exception as exc:
                self._set_hint(f"无法创建引擎: {exc}")
                return None
            return engine, None
        try:
            settings = load_settings(self._settings_path)
        except ValueError as exc:
            self._set_hint(f"设置读取失败: {exc}")
            return None
        provider = settings.provider
        if provider is None:
            self._set_hint("未配置 provider：请先在设置中填写 API 配置")
            return None
        try:
            value = self._secret_store.get(provider.key_name)
        except SecretStoreUnavailable as exc:
            self._set_hint(f"凭据后端不可用: {exc}")
            return None
        except Exception as exc:
            self._set_hint(f"无法读取凭据: {exc}")
            return None
        if not isinstance(value, str) or not value.strip():
            self._set_hint("未配置 API key：请在设置中保存密钥")
            return None
        try:
            engine = self._engine_factory(
                kind=kind,
                model=model,
                settings=settings,
                secret_store=self._secret_store,
            )
        except Exception as exc:
            self._set_hint(f"无法创建引擎: {exc}")
            return None
        return engine, float(provider.timeout_s)

    def _start_worker(self, engine, messages, timeout_s) -> None:
        self._cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run_engine,
            args=(engine, messages, timeout_s, self._cancel_event),
            name="chat-engine",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def _run_engine(self, engine, messages, timeout_s, cancel_event) -> None:
        try:
            reply = engine.send(
                messages,
                timeout_s=timeout_s,
                cancel=cancel_event,
            )
        except EngineError as exc:
            if cancel_event.is_set():
                self.run_stopped.emit("已停止")
            else:
                self.run_failed.emit(str(exc))
        except Exception as exc:  # adapter boundary: never kill the UI thread
            self.run_failed.emit(f"引擎异常: {exc}")
        else:
            if cancel_event.is_set():
                self.run_stopped.emit("已停止")
            else:
                self.reply_ready.emit(reply)
        finally:
            self.run_finished.emit()

    def _on_reply(self, reply) -> None:
        text = getattr(reply, "text", str(reply))
        self._append_message("assistant", text)
        self._history.append(ChatMessage("assistant", text))

    def _on_failed(self, message: str) -> None:
        self._append_message("error", message)
        if not self.input_edit.toPlainText().strip() and self._in_flight_text:
            self.input_edit.setPlainText(self._in_flight_text)
        self._in_flight_text = ""
        self._set_hint(f"引擎错误: {message}")

    def _on_stopped(self, message: str) -> None:
        self._append_message("stopped", message)
        self._set_hint(message)

    def _on_run_finished(self) -> None:
        self._running = False
        self._thread = None
        self._cancel_event = None
        self._in_flight_text = ""
        self.input_edit.setEnabled(True)
        self.engine_combo.setEnabled(True)
        self.model_edit.setEnabled(True)
        self.stop_button.hide()
        self._update_send_enabled()

    def _set_running(self, running: bool, engine_name: str = "") -> None:
        self._running = running
        if running:
            self.send_button.setEnabled(False)
            self.stop_button.show()
            self.input_edit.setEnabled(False)
            self.engine_combo.setEnabled(False)
            self.model_edit.setEnabled(False)
            self._set_hint(f"运行中（{engine_name}）...")

    def _update_send_enabled(self) -> None:
        has_text = bool(self.input_edit.toPlainText().strip())
        self.send_button.setEnabled(has_text and not self._running)

    def _append_message(self, role: str, text: str) -> QListWidgetItem:
        item = QListWidgetItem(f"{ROLE_PREFIXES.get(role, role)}: {text}")
        item.setData(Qt.ItemDataRole.UserRole, role)
        item.setForeground(QBrush(ROLE_COLORS.get(role, QColor("#333333"))))
        item.setToolTip(str(text))
        self.message_list.addItem(item)
        self.message_list.scrollToBottom()
        return item

    def _set_hint(self, text: str) -> None:
        self.hint_label.setText(text)
