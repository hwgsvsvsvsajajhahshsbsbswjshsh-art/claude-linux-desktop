#!/usr/bin/python3
import json
import os
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango


APP_NAME = "Claude"
APP_ID = "io.github.bakram.claudelinux"
API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = API_URL
DEFAULT_AUTH_SCHEME = "x-api-key"
DEFAULT_PROVIDER = "anthropic"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai_chat"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_SYSTEM_PROMPT = "你是 Claude，一个有帮助的中文编程助手。"

BASE_DIR = os.path.expanduser("~/.local/share/claude-linux")
CONFIG_DIR = os.path.expanduser("~/.config/claude-linux")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CONVERSATIONS_PATH = os.path.join(BASE_DIR, "conversations.json")


def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def compact_title(text):
    title = " ".join((text or "").strip().split())
    return title[:42] if title else "新对话"


def is_ascii_text(text):
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def looks_like_anthropic_key(text):
    return (text or "").strip().startswith("sk-ant-")


def looks_like_openai_key(text):
    return (text or "").strip().startswith("sk-")


def friendly_api_error(detail):
    text = (detail or "").strip()
    try:
        payload = json.loads(text)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error") or {}
        message = (error.get("message") or "").lower()
        err_type = (error.get("type") or "").lower()
        if "invalid x-api-key" in message or err_type == "authentication_error":
            return "API 密钥无效，请到 Anthropic 控制台重新生成后再填入设置。"
        if error.get("message"):
            return f"接口错误：{error.get('message')}"

    lowered = text.lower()
    if "invalid x-api-key" in lowered:
        return "API 密钥无效，请到 Anthropic 控制台重新生成后再填入设置。"
    if "authentication_error" in lowered:
        return "鉴权失败，请检查 API 密钥是否正确。"
    return text or "请求失败"


class Storage:
    def __init__(self):
        ensure_dirs()
        self.config = self._load_json(CONFIG_PATH, {
            "provider": DEFAULT_PROVIDER,
            "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "base_url": DEFAULT_BASE_URL,
            "auth_scheme": DEFAULT_AUTH_SCHEME,
            "api_version": ANTHROPIC_VERSION,
            "model": DEFAULT_MODEL,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
        })
        if self.config.get("base_url") and self.config.get("base_url") != DEFAULT_BASE_URL and not self.config.get("provider"):
            self.config["provider"] = PROVIDER_OPENAI
        api_key = self.config.get("api_key", "")
        if api_key and not is_ascii_text(api_key):
            self.config["api_key"] = ""
            self.save_config()
        self.conversations = self._load_json(CONVERSATIONS_PATH, {
            "active_id": None,
            "items": [],
        })

    def _load_json(self, path, default):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return default

    def save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(self.config, handle, ensure_ascii=False, indent=2)

    def save_conversations(self):
        with open(CONVERSATIONS_PATH, "w", encoding="utf-8") as handle:
            json.dump(self.conversations, handle, ensure_ascii=False, indent=2)


class AnthropicClient:
    def stream_message(self, *, provider, base_url, api_key, auth_scheme, api_version, model, messages, system, max_tokens):
        provider = (provider or DEFAULT_PROVIDER).strip().lower()
        if provider == PROVIDER_OPENAI:
            yield from self._stream_openai_chat(
                base_url=base_url,
                api_key=api_key,
                auth_scheme=auth_scheme,
                model=model,
                messages=messages,
                system=system,
                max_tokens=max_tokens,
            )
            return
        yield from self._stream_anthropic_messages(
            base_url=base_url,
            api_key=api_key,
            auth_scheme=auth_scheme,
            api_version=api_version,
            model=model,
            messages=messages,
            system=system,
            max_tokens=max_tokens,
        )

    def _stream_anthropic_messages(self, *, base_url, api_key, auth_scheme, api_version, model, messages, system, max_tokens):
        payload = {
            "model": model,
            "max_tokens": int(max_tokens),
            "messages": messages,
            "stream": True,
        }
        if system.strip():
            payload["system"] = system

        headers = {
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        scheme = (auth_scheme or DEFAULT_AUTH_SCHEME).strip().lower()
        key = api_key.strip()
        if scheme == "bearer":
            headers["authorization"] = f"Bearer {key}"
        elif scheme == "none":
            pass
        else:
            headers["x-api-key"] = key
            if api_version.strip():
                headers["anthropic-version"] = api_version.strip()

        request = urllib.request.Request(
            (base_url or DEFAULT_BASE_URL).strip(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=120) as response:
            yield from self._iter_sse(response)

    def _stream_openai_chat(self, *, base_url, api_key, auth_scheme, model, messages, system, max_tokens):
        payload = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "max_tokens": int(max_tokens),
        }
        if system.strip():
            payload["messages"] = [{"role": "system", "content": system}] + list(messages)

        headers = {
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        scheme = (auth_scheme or "bearer").strip().lower()
        key = api_key.strip()
        if scheme == "none":
            pass
        else:
            headers["authorization"] = f"Bearer {key}"

        endpoint = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            if endpoint.endswith("/v1"):
                endpoint = f"{endpoint}/chat/completions"
            else:
                endpoint = f"{endpoint}/v1/chat/completions"

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=120) as response:
            buffer = []
            while True:
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if not line:
                    if buffer:
                        data = "\n".join(buffer)
                        buffer = []
                        if data.strip() == "[DONE]":
                            yield "done", {}
                            break
                        try:
                            yield "chunk", json.loads(data)
                        except Exception:
                            yield "chunk", {"raw": data}
                    continue
                if line.startswith("data:"):
                    buffer.append(line[5:].lstrip())
                elif line.startswith("event:") and line[6:].strip() == "done":
                    yield "done", {}
                    break

    def _iter_sse(self, response):
        event_name = None
        data_lines = []

        while True:
            raw = response.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if event_name and data_lines:
                    yield event_name, json.loads("\n".join(data_lines))
                event_name = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if event_name and data_lines:
            yield event_name, json.loads("\n".join(data_lines))


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(
            title="设置",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(640, 520)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("保存", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(12)
        box.set_border_width(16)

        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        box.pack_start(grid, True, True, 0)

        self.api_key = Gtk.Entry()
        self.api_key.set_visibility(False)
        self.api_key.set_text(config.get("api_key", ""))

        self.provider = Gtk.ComboBoxText()
        self.provider.append(PROVIDER_ANTHROPIC, "Anthropic 原生")
        self.provider.append(PROVIDER_OPENAI, "OpenAI 兼容")
        self.provider.set_active_id(config.get("provider", DEFAULT_PROVIDER))

        self.model = Gtk.Entry()
        self.model.set_text(config.get("model", DEFAULT_MODEL))

        self.base_url = Gtk.Entry()
        self.base_url.set_text(config.get("base_url", DEFAULT_BASE_URL))

        self.auth_scheme = Gtk.ComboBoxText()
        self.auth_scheme.append("x-api-key", "Anthropic x-api-key")
        self.auth_scheme.append("bearer", "Bearer Token")
        self.auth_scheme.append("none", "无认证")
        self.auth_scheme.set_active_id(config.get("auth_scheme", DEFAULT_AUTH_SCHEME))

        self.api_version = Gtk.Entry()
        self.api_version.set_text(config.get("api_version", ANTHROPIC_VERSION))

        self.max_tokens = Gtk.SpinButton()
        self.max_tokens.set_range(256, 8192)
        self.max_tokens.set_increments(128, 512)
        self.max_tokens.set_value(int(config.get("max_tokens", DEFAULT_MAX_TOKENS)))

        self.system_prompt = Gtk.TextView()
        self.system_prompt.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.system_prompt.get_buffer().set_text(config.get("system_prompt", DEFAULT_SYSTEM_PROMPT))
        self.system_prompt.set_size_request(-1, 220)

        labels = [
            ("API 密钥", self.api_key),
            ("接口类型", self.provider),
            ("接口地址", self.base_url),
            ("认证方式", self.auth_scheme),
            ("API 版本", self.api_version),
            ("模型", self.model),
            ("最大输出", self.max_tokens),
            ("系统提示词", self.system_prompt),
        ]

        for row, (label_text, widget) in enumerate(labels):
            label = Gtk.Label(label=label_text)
            label.set_halign(Gtk.Align.START)
            if label_text == "系统提示词":
                label.set_valign(Gtk.Align.START)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)

        grid.attach(Gtk.Label(label="提示：第三方站点通常需要填写它自己的接口地址和鉴权方式。"), 1, 7, 1, 1)

        self.show_all()

    def values(self):
        buffer = self.system_prompt.get_buffer()
        start, end = buffer.get_bounds()
        prompt = buffer.get_text(start, end, True)
        return {
            "provider": self.provider.get_active_id() or DEFAULT_PROVIDER,
            "api_key": self.api_key.get_text().strip(),
            "base_url": self.base_url.get_text().strip() or DEFAULT_BASE_URL,
            "auth_scheme": self.auth_scheme.get_active_id() or DEFAULT_AUTH_SCHEME,
            "api_version": self.api_version.get_text().strip() or ANTHROPIC_VERSION,
            "model": self.model.get_text().strip() or DEFAULT_MODEL,
            "max_tokens": int(self.max_tokens.get_value()),
            "system_prompt": prompt.strip() or DEFAULT_SYSTEM_PROMPT,
        }


class ClaudeLinuxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=0)
        self.storage = Storage()
        self.client = AnthropicClient()
        self.window = None
        self.conversation_list = None
        self.message_area = None
        self.scroller = None
        self.composer = None
        self.send_button = None
        self.stop_button = None
        self.status_label = None
        self.spinner = None
        self.current_id = None
        self.current_stream = None
        self.active_message = None
        self.message_rows = {}
        self.conversation_rows = {}
        self.showing_welcome = False
        self.css_provider = Gtk.CssProvider()
        self.css_provider.load_from_data(self._css())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_activate(self):
        if self.window:
            self.window.present()
            return

        settings = Gtk.Settings.get_default()
        if settings:
            settings.props.gtk_application_prefer_dark_theme = True

        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title(APP_NAME)
        self.window.set_default_size(1320, 920)
        self.window.maximize()

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = APP_NAME

        new_button = Gtk.Button.new_from_icon_name("document-new-symbolic", Gtk.IconSize.BUTTON)
        new_button.set_tooltip_text("新对话")
        new_button.connect("clicked", lambda *_: self.new_chat())

        settings_button = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        settings_button.set_tooltip_text("设置")
        settings_button.connect("clicked", lambda *_: self.open_settings())

        header.pack_start(new_button)
        header.pack_end(settings_button)
        self.window.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.get_style_context().add_class("root")

        sidebar = self._build_sidebar()
        chat = self._build_chat()

        root.pack_start(sidebar, False, False, 0)
        root.pack_start(chat, True, True, 0)

        self.window.add(root)
        self.window.show_all()
        self._load_conversations()

        if self.storage.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"):
            self._set_status("就绪")
        else:
            self._set_status("请先在设置里填入 API 密钥。")
            GLib.idle_add(self.open_settings)

        if not self.current_id:
            self.new_chat()

    def _build_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.set_size_request(300, -1)
        sidebar.get_style_context().add_class("sidebar")
        sidebar.set_border_width(16)

        title = Gtk.Label(label="会话")
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class("sidebar-title")
        sidebar.pack_start(title, False, False, 0)

        new_btn = Gtk.Button(label="新对话")
        new_btn.get_style_context().add_class("primary-button")
        new_btn.connect("clicked", lambda *_: self.new_chat())
        sidebar.pack_start(new_btn, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.set_hexpand(False)
        scroller.set_vexpand(True)

        self.conversation_list = Gtk.ListBox()
        self.conversation_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.conversation_list.connect("row-selected", self._on_conversation_selected)
        scroller.add(self.conversation_list)
        sidebar.pack_start(scroller, True, True, 0)

        footer = Gtk.Label(label="本地历史记录保存在这台机器上。")
        footer.set_line_wrap(True)
        footer.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        footer.get_style_context().add_class("muted")
        footer.set_halign(Gtk.Align.START)
        sidebar.pack_end(footer, False, False, 0)

        return sidebar

    def _build_chat(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("chat-shell")

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_shadow_type(Gtk.ShadowType.NONE)
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)

        self.message_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.message_area.set_border_width(20)
        self.message_area.set_valign(Gtk.Align.START)
        self.scroller.add(self.message_area)

        outer.pack_start(self.scroller, True, True, 0)
        outer.pack_start(self._build_composer(), False, False, 0)
        return outer

    def _build_composer(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.set_border_width(16)
        panel.get_style_context().add_class("composer-panel")

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(label="就绪")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.status_label.get_style_context().add_class("muted")
        status_row.pack_start(self.spinner, False, False, 0)
        status_row.pack_start(self.status_label, True, True, 0)

        self.composer = Gtk.TextView()
        self.composer.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.composer.set_left_margin(10)
        self.composer.set_right_margin(10)
        self.composer.set_top_margin(10)
        self.composer.set_bottom_margin(10)
        self.composer.set_size_request(-1, 120)
        self.composer.connect("key-press-event", self._on_composer_key)
        self.composer.get_style_context().add_class("composer")

        composer_frame = Gtk.Frame()
        composer_frame.set_shadow_type(Gtk.ShadowType.IN)
        composer_frame.add(self.composer)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.stop_button = Gtk.Button(label="停止")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", lambda *_: self._stop_stream())

        self.send_button = Gtk.Button(label="发送")
        self.send_button.get_style_context().add_class("primary-button")
        self.send_button.connect("clicked", lambda *_: self.send_current_message())

        button_row.pack_start(self.stop_button, False, False, 0)
        button_row.pack_end(self.send_button, False, False, 0)

        panel.pack_start(status_row, False, False, 0)
        panel.pack_start(composer_frame, False, False, 0)
        panel.pack_start(button_row, False, False, 0)

        return panel

    def _css(self):
        return b"""
        * {
            font-family: Inter, Noto Sans, sans-serif;
        }
        window {
            background: #0f1115;
        }
        .root {
            background: #0f1115;
        }
        .sidebar {
            background: #11151d;
            border-right: 1px solid rgba(255,255,255,0.08);
        }
        .chat-shell {
            background: #0f1115;
        }
        .sidebar-title {
            font-size: 18px;
            font-weight: 700;
            color: #f5f7fb;
        }
        .muted {
            color: rgba(245,247,251,0.65);
        }
        .primary-button {
            background: #f5f7fb;
            color: #0f1115;
            border-radius: 12px;
            padding: 8px 14px;
        }
        .conversation-row {
            background: transparent;
            padding: 8px 0;
        }
        .conversation-row:selected {
            background: transparent;
        }
        .conversation-pill {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 12px 14px;
        }
        .conversation-pill.active {
            background: rgba(255,255,255,0.12);
        }
        .conversation-title {
            color: #f5f7fb;
            font-weight: 600;
        }
        .bubble {
            border-radius: 18px;
            padding: 14px 16px;
            margin: 2px 0;
        }
        .bubble-user {
            background: #2563eb;
            color: #ffffff;
        }
        .bubble-assistant {
            background: #1b2230;
            color: #f5f7fb;
        }
        .composer-panel {
            background: rgba(255,255,255,0.03);
            border-top: 1px solid rgba(255,255,255,0.08);
        }
        .composer {
            background: #121721;
            color: #f5f7fb;
        }
        headerbar {
            background: #11151d;
            color: #f5f7fb;
        }
        """

    def _load_conversations(self):
        items = self.storage.conversations.get("items", [])
        if not items:
            self.storage.conversations["items"] = []
            self.storage.conversations["active_id"] = None
            self.storage.save_conversations()
            return

        for conv in items:
            self._ensure_conversation_row(conv)

        active_id = self.storage.conversations.get("active_id") or items[-1]["id"]
        self.open_conversation(active_id)

    def _ensure_conversation_row(self, conv):
        conv_id = conv["id"]
        if conv_id in self.conversation_rows:
            self._refresh_conversation_row(conv)
            return

        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("conversation-row")
        row.conversation_id = conv_id

        pill = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pill.get_style_context().add_class("conversation-pill")

        title = Gtk.Label(label=conv.get("title", "新对话"))
        title.set_halign(Gtk.Align.START)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.get_style_context().add_class("conversation-title")
        pill.pack_start(title, False, False, 0)

        row.add(pill)
        self.conversation_list.add(row)
        self.conversation_rows[conv_id] = {
            "row": row,
            "pill": pill,
            "title": title,
        }

    def _refresh_conversation_row(self, conv):
        item = self.conversation_rows.get(conv["id"])
        if not item:
            return
        item["title"].set_text(conv.get("title", "新对话"))
        active = conv["id"] == self.current_id
        ctx = item["pill"].get_style_context()
        if active:
            ctx.add_class("active")
        else:
            ctx.remove_class("active")

    def _refresh_sidebar(self):
        for conv in self.storage.conversations.get("items", []):
            self._refresh_conversation_row(conv)

    def _on_conversation_selected(self, _listbox, row):
        if not row:
            return
        conv_id = getattr(row, "conversation_id", None)
        if conv_id:
            self.open_conversation(conv_id)

    def _find_conversation(self, conv_id):
        for conv in self.storage.conversations.get("items", []):
            if conv["id"] == conv_id:
                return conv
        return None

    def _current_conversation(self):
        if not self.current_id:
            return None
        return self._find_conversation(self.current_id)

    def new_chat(self):
        conv = {
            "id": new_id("conv"),
            "title": "新对话",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "messages": [],
        }
        self.storage.conversations.setdefault("items", []).append(conv)
        self.storage.conversations["active_id"] = conv["id"]
        self.storage.save_conversations()
        self._ensure_conversation_row(conv)
        self.conversation_list.show_all()
        self.open_conversation(conv["id"])

    def open_conversation(self, conv_id):
        conv = self._find_conversation(conv_id)
        if not conv:
            return
        self.current_id = conv_id
        self.storage.conversations["active_id"] = conv_id
        self.storage.save_conversations()

        for item in self.conversation_rows.values():
            item["pill"].get_style_context().remove_class("active")
        current = self.conversation_rows.get(conv_id)
        if current:
            current["pill"].get_style_context().add_class("active")
            if current["row"].get_parent() is self.conversation_list:
                self.conversation_list.select_row(current["row"])

        self._render_messages(conv["messages"])
        self._set_status(f"当前会话：{conv.get('title', '新对话')}")

    def _clear_messages(self):
        for child in list(self.message_area.get_children()):
            self.message_area.remove(child)
        self.message_rows.clear()

    def _render_messages(self, messages):
        self._clear_messages()
        if not messages:
            self._add_welcome()
            self._scroll_to_bottom()
            return

        for message in messages:
            self._add_message_widget(message["role"], message["content"])
        self._scroll_to_bottom()

    def _add_welcome(self):
        self.showing_welcome = True
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(48)
        box.set_margin_bottom(32)
        box.set_margin_start(32)
        box.set_margin_end(32)

        title = Gtk.Label(label="开始一个新对话")
        title.get_style_context().add_class("sidebar-title")
        title.set_halign(Gtk.Align.START)

        body = Gtk.Label(label="在下面输入消息，然后按回车与 Claude 对话。")
        body.set_halign(Gtk.Align.START)
        body.set_line_wrap(True)
        body.get_style_context().add_class("muted")

        box.pack_start(title, False, False, 0)
        box.pack_start(body, False, False, 0)
        self.message_area.pack_start(box, False, False, 0)

    def _add_message_widget(self, role, content, is_stream=False):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.set_hexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_hexpand(True)

        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bubble.get_style_context().add_class("bubble")
        bubble.get_style_context().add_class("bubble-user" if role == "user" else "bubble-assistant")
        bubble.set_border_width(0)

        label = Gtk.Label()
        label.set_selectable(True)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0.0)
        label.set_text(content or "")
        label.set_width_chars(1)
        bubble.pack_start(label, False, False, 0)

        if role == "user":
            outer.set_halign(Gtk.Align.END)
            outer.set_margin_start(120)
            outer.set_margin_end(16)
        else:
            outer.set_halign(Gtk.Align.START)
            outer.set_margin_start(16)
            outer.set_margin_end(120)

        outer.pack_start(bubble, False, False, 0)
        row.pack_start(outer, True, True, 0)
        self.message_area.pack_start(row, False, False, 0)
        self.message_area.show_all()

        if is_stream:
            self.active_message = {
                "widget": label,
                "buffer": content or "",
            }
        else:
            self.message_rows[id(label)] = label
        return label

    def _replace_stream_widget(self, text):
        if self.active_message:
            self.active_message["buffer"] = text
            self.active_message["widget"].set_text(text)
            self._scroll_to_bottom()

    def _finish_stream(self, conv_id, text):
        self._replace_stream_widget(text or " ")
        self._set_busy(False)
        self.stop_button.set_sensitive(False)
        self.send_button.set_sensitive(True)
        self.composer.set_sensitive(True)
        self.active_message = None
        self.current_stream = None
        conv = self._find_conversation(conv_id)
        if conv:
            conv["messages"].append({"role": "assistant", "content": text or ""})
            if conv["title"] == "新对话" and conv["messages"]:
                first_user = next((m["content"] for m in conv["messages"] if m["role"] == "user"), "")
                conv["title"] = compact_title(first_user)
                self._refresh_sidebar()
            conv["updated_at"] = now_iso()
            self.storage.save_conversations()
            self._set_status("就绪")

    def _fail_stream(self, conv_id, error_text):
        friendly = friendly_api_error(error_text)
        self._replace_stream_widget(f"错误：{friendly}")
        self._set_busy(False)
        self.stop_button.set_sensitive(False)
        self.send_button.set_sensitive(True)
        self.composer.set_sensitive(True)
        self.active_message = None
        self.current_stream = None
        self._set_status(friendly)
        conv = self._find_conversation(conv_id)
        if conv:
            conv["messages"].append({"role": "assistant", "content": f"错误：{friendly}"})
            conv["updated_at"] = now_iso()
            self.storage.save_conversations()

    def _set_status(self, text):
        self.status_label.set_text(text)

    def _set_busy(self, busy):
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

    def _scroll_to_bottom(self):
        adj = self.scroller.get_vadjustment()
        if adj:
            GLib.idle_add(adj.set_value, max(0.0, adj.get_upper() - adj.get_page_size()))

    def _composer_text(self):
        buffer = self.composer.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, True).strip()

    def _clear_composer(self):
        self.composer.get_buffer().set_text("")

    def _on_composer_key(self, _widget, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                return False
            self.send_current_message()
            return True
        return False

    def open_settings(self):
        dialog = SettingsDialog(self.window, self.storage.config)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.storage.config.update(dialog.values())
            self.storage.save_config()
            self._set_status("设置已保存")
        dialog.destroy()

    def _stop_stream(self):
        if self.current_stream:
            self.current_stream["stop"] = True
            self._set_status("正在停止...")

    def send_current_message(self):
        if self.current_stream:
            self._set_status("请等待当前回复结束，或点击停止。")
            return

        text = self._composer_text()
        if not text:
            return

        api_key = (self.storage.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        if not api_key:
            self._set_status("请先在设置中填写 API 密钥。")
            self.open_settings()
            return
        provider = self.storage.config.get("provider", DEFAULT_PROVIDER)
        if provider == PROVIDER_ANTHROPIC and not looks_like_anthropic_key(api_key):
            self._set_status("这个密钥看起来不像 Anthropic Console 生成的 API key。")
            return
        if provider == PROVIDER_OPENAI and not looks_like_openai_key(api_key):
            self._set_status("这个密钥看起来不像 OpenAI 兼容接口的 token。")
            return

        conv = self._current_conversation()
        if not conv:
            self.new_chat()
            conv = self._current_conversation()
        if not conv:
            return

        self._clear_messages_if_welcome()
        self._clear_composer()
        self._add_message_widget("user", text)
        conv["messages"].append({"role": "user", "content": text})
        if conv["title"] == "新对话":
            conv["title"] = compact_title(text)
            self._refresh_sidebar()
        conv["updated_at"] = now_iso()
        self.storage.save_conversations()

        assistant_label = self._add_message_widget("assistant", "", is_stream=True)
        self._set_busy(True)
        self.stop_button.set_sensitive(True)
        self.send_button.set_sensitive(False)
        self.composer.set_sensitive(False)
        self._set_status(f"正在使用 {self.storage.config.get('model', DEFAULT_MODEL)} 思考...")

        self.current_stream = {"stop": False, "label": assistant_label}
        thread = threading.Thread(
            target=self._stream_request,
            args=(conv["id"], list(conv["messages"])),
            daemon=True,
        )
        thread.start()

    def _clear_messages_if_welcome(self):
        if not self.showing_welcome:
            return
        for child in list(self.message_area.get_children()):
            self.message_area.remove(child)
        self.showing_welcome = False

    def _stream_request(self, conv_id, messages):
        try:
            api_key = (self.storage.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
            if api_key and not is_ascii_text(api_key):
                raise ValueError("API 密钥包含中文或其他非 ASCII 字符，请改为 Anthropic 提供的英文数字密钥。")
            provider = self.storage.config.get("provider", DEFAULT_PROVIDER)
            base_url = self.storage.config.get("base_url", DEFAULT_BASE_URL).strip()
            auth_scheme = self.storage.config.get("auth_scheme", DEFAULT_AUTH_SCHEME).strip()
            api_version = self.storage.config.get("api_version", ANTHROPIC_VERSION).strip()
            if provider == PROVIDER_ANTHROPIC and base_url.startswith(DEFAULT_BASE_URL) and auth_scheme == "x-api-key" and api_key and not looks_like_anthropic_key(api_key):
                raise ValueError("这个密钥看起来不像 Anthropic Console 生成的 API key。通常应以 sk-ant- 开头。")
            if provider == PROVIDER_OPENAI and api_key and not looks_like_openai_key(api_key):
                raise ValueError("这个密钥看起来不像 OpenAI 兼容接口的 token。通常以 sk- 开头。")
            model = self.storage.config.get("model", DEFAULT_MODEL)
            max_tokens = int(self.storage.config.get("max_tokens", DEFAULT_MAX_TOKENS))
            system_prompt = self.storage.config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)

            full_text = []
            for event_name, payload in self.client.stream_message(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                auth_scheme=auth_scheme,
                api_version=api_version,
                model=model,
                messages=messages,
                system=system_prompt,
                max_tokens=max_tokens,
            ):
                if self.current_stream and self.current_stream.get("stop"):
                    return
                if provider == PROVIDER_OPENAI:
                    chunk = payload if isinstance(payload, dict) else {}
                    choices = chunk.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        text_piece = delta.get("content")
                        if text_piece:
                            full_text.append(text_piece)
                            GLib.idle_add(self._replace_stream_widget, "".join(full_text))
                    if event_name == "done":
                        break
                elif event_name == "content_block_delta":
                    delta = payload.get("delta", {})
                    if delta.get("type") == "text_delta":
                        full_text.append(delta.get("text", ""))
                        GLib.idle_add(self._replace_stream_widget, "".join(full_text))
                elif event_name == "message_delta":
                    pass
                elif event_name == "message_stop":
                    break
                elif event_name == "error":
                    raise RuntimeError(payload.get("error", {}).get("message", "Unknown API error"))

            GLib.idle_add(self._finish_stream, conv_id, "".join(full_text).strip())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else str(exc)
            GLib.idle_add(self._fail_stream, conv_id, detail)
        except Exception:
            GLib.idle_add(self._fail_stream, conv_id, traceback.format_exc(limit=5))


def main():
    app = ClaudeLinuxApp()
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
