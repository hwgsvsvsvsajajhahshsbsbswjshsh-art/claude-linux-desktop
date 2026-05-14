# Claude Linux

这是一个 Linux 原生的 Claude 桌面客户端，界面已中文化，并支持自定义第三方 API 站点。

## 功能

- 原生 GTK 桌面窗口
- 左侧会话列表，右侧聊天区
- 支持 Anthropic Messages API 流式回复
- 本地保存对话记录
- 可在设置里配置 API 密钥、模型、最大输出和系统提示词
- 可切换官方 Anthropic 或第三方兼容接口

## 依赖

- `python3`
- `python3-gi`
- `gir1.2-gtk-3.0`

## 运行

```bash
./claude_linux_desktop/launch.sh
```

## 安装

```bash
./claude_linux_desktop/install.sh
```

## 配置

可以在设置里填写 `ANTHROPIC_API_KEY`，也可以直接设置环境变量。
如果你使用第三方站点，请填写它提供的完整接口地址和对应鉴权方式。

数据默认保存在：

- `~/.config/claude-linux/config.json`
- `~/.local/share/claude-linux/conversations.json`
