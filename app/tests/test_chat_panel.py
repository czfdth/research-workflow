"""Offscreen tests for the chat panel and its background engine thread."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ccfa_core.engines.base import ChatMessage, EngineError, EngineReply
from ccfa_core.secrets import SecretStoreUnavailable
from ccfa_core.settings import ProviderSettings, Settings, save_settings
from ccfa_gui.chat_panel import ChatPanel
from ccfa_gui.window import MainWindow, image_non_background_ratio

from . import write_project

APP = QApplication.instance() or QApplication([])
FAKE_KEY = "sk-chat-FAKE-KEY-2468013579"
BASE_URL = "https://api.example.test/v1"


class RecordingSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


class UnavailableSecretStore(RecordingSecretStore):
    def get(self, key_name):
        raise SecretStoreUnavailable("no backend")


class FakeEngine:
    """Deterministic engine used to observe panel behavior."""

    def __init__(self, *, reply_text="pong", error=None, delay=0.0, name="fake"):
        self.name = name
        self.reply_text = reply_text
        self.error = error
        self.delay = delay
        self.calls = []
        self.started = threading.Event()
        self.cancelled = False

    def send(self, messages, *, tools=None, timeout_s=None, cancel=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "timeout_s": timeout_s,
                "cancel": cancel,
            }
        )
        self.started.set()
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                self.cancelled = True
                raise EngineError("请求已取消")
            time.sleep(0.005)
        if cancel is not None and cancel.is_set():
            self.cancelled = True
            raise EngineError("请求已取消")
        if self.error is not None:
            raise self.error
        return EngineReply(text=self.reply_text)


class ChatPanelTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.settings_path = self.root / "settings.json"
        self.secrets = RecordingSecretStore()
        self.factories = []
        self._panels = []

    def tearDown(self):
        for panel in self._panels:
            panel.stop()
            self._wait_until(lambda: panel._thread is None)
            panel.close()
            panel.deleteLater()
        APP.processEvents()

    def _configure_provider(self, key_name="local", key=FAKE_KEY):
        save_settings(
            self.settings_path,
            Settings(
                provider=ProviderSettings(
                    name="local",
                    base_url=BASE_URL,
                    model="gpt-test",
                    key_name=key_name,
                    timeout_s=30.0,
                )
            ),
        )
        if key is not None:
            self.secrets.set(key_name, key)

    def _factory(self, engines=None):
        created = {}

        def factory(*, kind, model, settings, secret_store):
            created["kind"] = kind
            created["model"] = model
            created["settings"] = settings
            if engines is not None and kind in engines:
                return engines[kind]
            engine = FakeEngine(name=f"fake-{kind}")
            created.setdefault("engines", {})[kind] = engine
            return engine

        self.factories.append(factory)
        self.created = created
        return factory

    def _panel(self, *, factory=None, store=None, engines=None, kind="openai"):
        panel = ChatPanel(
            self.settings_path,
            secret_store=store or self.secrets,
            engine_factory=factory or self._factory(engines),
        )
        panel.resize(760, 620)
        panel.show()
        APP.processEvents()
        if kind != "openai":
            panel.engine_combo.setCurrentIndex(
                panel.engine_combo.findData(kind)
            )
            APP.processEvents()
        self._panels.append(panel)
        return panel

    @staticmethod
    def _wait_until(predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            APP.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        APP.processEvents()
        return predicate()

    @staticmethod
    def _items(panel):
        return [
            (
                panel.message_list.item(row).data(Qt.ItemDataRole.UserRole),
                panel.message_list.item(row).text(),
                panel.message_list.item(row).foreground().color(),
            )
            for row in range(panel.message_list.count())
        ]

    def _send(self, panel, text):
        panel.input_edit.setPlainText(text)
        APP.processEvents()
        panel.send_button.click()

    def test_send_shows_user_and_assistant_messages(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="pong")
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "ping")
        self.assertTrue(
            self._wait_until(lambda: len(engine.calls) == 1 and panel._thread is None)
        )

        items = self._items(panel)
        self.assertEqual([role for role, _, _ in items], ["user", "assistant"])
        self.assertIn("ping", items[0][1])
        self.assertIn("pong", items[1][1])
        self.assertEqual(engine.calls[0]["messages"][0].content, "ping")
        self.assertEqual(panel.input_edit.toPlainText(), "")
        self.assertFalse(panel.send_button.isEnabled())
        self.assertTrue(panel.stop_button.isHidden())
        self.assertTrue(panel.input_edit.isEnabled())

    def test_ctrl_enter_shortcut_sends_the_message(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="shortcut")
        panel = self._panel(engines={"openai": engine})
        panel.input_edit.setPlainText("via keyboard")
        APP.processEvents()

        QTest.keyClick(
            panel.input_edit,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )

        self.assertTrue(self._wait_until(lambda: len(engine.calls) == 1))
        self.assertEqual(engine.calls[0]["messages"][0].content, "via keyboard")

    def test_running_state_disables_send_and_shows_stop(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="slow", delay=5.0)
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "long job")
        self.assertTrue(engine.started.wait(2.0))
        APP.processEvents()

        self.assertFalse(panel.send_button.isEnabled())
        self.assertFalse(panel.input_edit.isEnabled())
        self.assertFalse(panel.stop_button.isHidden())
        self.assertIn("停止", panel.stop_button.text())

    def test_stop_cancels_slow_engine_and_restores_ui(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="slow", delay=5.0)
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "long job")
        self.assertTrue(engine.started.wait(2.0))
        panel.stop_button.click()

        self.assertTrue(
            self._wait_until(lambda: engine.cancelled and panel._thread is None)
        )
        self.assertTrue(panel.stop_button.isHidden())
        self.assertTrue(panel.input_edit.isEnabled())
        panel.input_edit.setPlainText("next question")
        APP.processEvents()
        self.assertTrue(panel.send_button.isEnabled())
        self.assertTrue(
            any("已停止" in text for _, text, _ in self._items(panel))
        )

    def test_engine_error_shows_error_style_and_keeps_input(self):
        self._configure_provider()
        engine = FakeEngine(error=EngineError("backend exploded"))
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "retry me")
        self.assertTrue(self._wait_until(lambda: panel._thread is None))

        items = self._items(panel)
        self.assertEqual([role for role, _, _ in items], ["user", "error"])
        self.assertIn("backend exploded", items[1][1])
        self.assertEqual(items[1][2], QColor("#b00020"))
        self.assertEqual(panel.input_edit.toPlainText(), "retry me")

    def test_engine_switch_uses_the_selected_engine(self):
        self._configure_provider()
        openai_engine = FakeEngine(reply_text="from openai")
        codex_engine = FakeEngine(reply_text="from codex")
        panel = self._panel(
            engines={"openai": openai_engine, "codex": codex_engine}
        )

        self._send(panel, "first")
        self.assertTrue(self._wait_until(lambda: len(openai_engine.calls) == 1))
        panel.engine_combo.setCurrentIndex(panel.engine_combo.findData("codex"))
        panel.model_edit.setText("gpt-5-codex")
        APP.processEvents()
        self._send(panel, "second")
        self.assertTrue(self._wait_until(lambda: len(codex_engine.calls) == 1))

        self.assertEqual(len(openai_engine.calls), 1)
        self.assertEqual(self.created["kind"], "codex")
        self.assertEqual(self.created["model"], "gpt-5-codex")
        self.assertIsNone(self.created["settings"])

    def test_unconfigured_provider_blocks_send_without_calling_engine(self):
        factory = self._factory()
        panel = self._panel(factory=factory)

        self._send(panel, "hello")
        APP.processEvents()

        self.assertIn("未配置 provider", panel.hint_label.text())
        self.assertNotIn("engines", self.created)

    def test_missing_key_blocks_send_without_calling_engine(self):
        self._configure_provider(key=None)
        factory = self._factory()
        panel = self._panel(factory=factory)

        self._send(panel, "hello")
        APP.processEvents()

        self.assertIn("未配置 API key", panel.hint_label.text())
        self.assertNotIn("engines", self.created)

    def test_unavailable_keyring_shows_hint_without_crashing(self):
        self._configure_provider()
        panel = self._panel(
            factory=self._factory(),
            store=UnavailableSecretStore(),
        )

        self._send(panel, "hello")
        APP.processEvents()

        self.assertIn("凭据后端不可用", panel.hint_label.text())
        self.assertNotIn("engines", self.created)

    def test_codex_engine_does_not_require_provider(self):
        engine = FakeEngine(reply_text="codex ok")
        factory = self._factory(engines={"codex": engine})
        panel = self._panel(factory=factory, kind="codex")
        panel.model_edit.setText("gpt-5-codex")

        self._send(panel, "hello")
        self.assertTrue(self._wait_until(lambda: len(engine.calls) == 1))

        self.assertEqual(self.created["kind"], "codex")
        self.assertIsNone(self.created["settings"])
        self.assertIn("codex ok", self._items(panel)[-1][1])

    def test_send_stays_disabled_while_input_is_empty(self):
        panel = self._panel(engines={"openai": FakeEngine()})

        self.assertFalse(panel.send_button.isEnabled())
        panel.input_edit.setPlainText("text")
        APP.processEvents()
        self.assertTrue(panel.send_button.isEnabled())

    def test_send_does_not_block_the_ui_thread(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="slow", delay=0.6)
        panel = self._panel(engines={"openai": engine})
        panel.input_edit.setPlainText("responsiveness")
        APP.processEvents()

        started = time.monotonic()
        panel.send_button.click()
        elapsed = time.monotonic() - started
        APP.processEvents()

        self.assertLess(
            elapsed,
            0.1,
            f"send blocked the UI thread for {elapsed:.3f}s",
        )
        panel.stop_button.click()
        self.assertTrue(self._wait_until(lambda: panel._thread is None))

    def test_render_is_non_blank_with_visible_controls(self):
        panel = self._panel(engines={"openai": FakeEngine()})

        image = panel.grab().toImage()
        path = self.root / "chat-panel.png"
        self.assertTrue(image.save(str(path), "PNG"))

        self.assertGreater(image.width(), 500)
        self.assertGreater(image.height(), 400)
        ratio = image_non_background_ratio(image)
        self.assertGreater(
            ratio,
            0.02,
            f"non-background ratio too low: {ratio}",
        )
        for widget in (
            panel.engine_combo,
            panel.message_list,
            panel.input_edit,
            panel.send_button,
            panel.hint_label,
        ):
            with self.subTest(widget=type(widget).__name__):
                self.assertTrue(widget.isVisible())
                self.assertGreater(widget.width(), 0)
                self.assertGreater(widget.height(), 0)
        size = path.stat().st_size
        self.assertGreater(size, 0)
        print(f"CHAT_SCREENSHOT_RATIO={ratio:.4f}")
        print(f"CHAT_SCREENSHOT_PATH={path}")
        print(f"CHAT_SCREENSHOT_BYTES={size}")

    def test_window_mounts_the_chat_panel(self):
        write_project(self.root, "chat-demo", mode="conference", stage="idea")
        window = MainWindow(
            repo_root=self.root,
            secret_store=self.secrets,
            settings_path=self.settings_path,
        )
        window.resize(1100, 760)
        window.show()
        APP.processEvents()
        self.addCleanup(self._dispose_window, window)

        self.assertTrue(hasattr(window, "chat_panel"))
        self.assertEqual(window.chat_panel.engine_combo.count(), 2)
        self.assertTrue(window.chat_panel.isVisible())
        self.assertGreater(window.chat_panel.width(), 0)
        self.assertGreater(window.chat_panel.height(), 0)

    @staticmethod
    def _dispose_window(window):
        window.close()
        window.deleteLater()
        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
