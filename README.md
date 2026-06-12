# ModelBuddyCC

## 项目背景

Claude Code 是 Anthropic 推出的命令行 AI 编程工具，功能强大，但官方并未提供可视化的模型切换界面。每当用户想更换底层大模型（如从官方默认模型切换到 DeepSeek、Kimi 等），都需要手动编辑 `~/.claude.json` 配置文件，修改环境变量。过程繁琐、容易出错，对非技术用户极不友好。

ModelBuddyCC 正是为了解决这一痛点而生。它提供了一套完整的图形化管理方案，让模型切换像切换账号一样简单。***自用为主***，目前不能够保证完全的稳定性和安全性，但已经能够满足大部分使用场景。**碰瓷不辽目前主流的切换器**

本项目由 **江西某高校在校废物** 发起并与AI协作开发，针对**自己**高校学生日常使用 Claude Code 的实际场景与课程要求进行了针对性优化：

- 🎓 **零门槛操作：** 不需要懂 JSON 配置文件，不需要记环境变量名，GUI 界面点点即可完成切换
- 💰 **余额可视：** 内置 DeepSeek、Kimi 等高校常用 API 厂商的余额查询，避免写到一半欠费中断（目前只支持deepseek、kimi）
- 📄 **对话导出：** 支持将编程对话导出为排版精良的 HTML，方便交作业、写报告时附上完整的 AI 协作记录
- ⚡ **多配置记忆：** 一次填写，永久保存，不同课程/项目可快速切换不同模型

> 🧠 **开发方式：** 本项目 100% 由人类通过与 **AI 编程助手** 持续对话、迭代交互完成。从第一行代码到最终成品的每一处细节，均由人类提出需求、审核方案、把关质量，AI 负责代码生成与实现。这是「人机协作」开发模式的实践产物。

## 功能概览

| 模块 | 说明 |
|------|------|
| **模型配置** | 保存/编辑/切换 Claude Code 的 API 地址、密钥、模型名 |
| **Claude 启动器** | 选择目录启动 Claude Code，记录打开历史 |
| **执行模式** | 切换 Claude Code 的权限模式（默认/编辑/计划/锁定/自动/绕过） |
| **对话导出** | 将 Claude Code 对话记录导出为 HTML（含思考过程、工具调用） |
| **余额仪表盘** | 一键查询各 API 厂商的账户余额 |

## 系统要求

- Windows 10/11
- Python 3.10+
- 已安装 [Claude Code](https://claude.ai/code) CLI

## 快速开始

### 方式一：直接运行源码

```bash
# 安装依赖
pip install customtkinter

# 运行
python main.py
```

## 使用指南

### 1. 模型配置管理

程序会读取 `~/.claude.json` 中的环境变量，支持以下配置项：

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `ANTHROPIC_BASE_URL` | API 地址 | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_AUTH_TOKEN` | API 密钥 | `sk-xxxxxxxx` |
| `ANTHROPIC_MODEL` | 模型名称 | `deepseek-v4-flash` |

**操作流程：**

1. 点击左下角 **＋ 新建**，填写配置信息
2. 在左侧列表中选择一个配置
3. 点击右下角 **▶ 应用配置** 写入 `.claude.json`
4. 手动重启 Claude Code 使新配置生效

> 配置数据保存在 `~/.claude/model_profiles.json`，API 密钥**不会**以明文形式出现在程序界面上。

### 2. 支持的余额查询厂商

程序内置了以下 API 厂商的余额查询接口：

| 厂商 | 匹配域名 |
|------|----------|
| DeepSeek | `api.deepseek.com` |
| Kimi (Moonshot) | `api.moonshot.cn` |

如需添加其他厂商，可在 `BALANCE_PROVIDERS` 字典中注册新的解析规则。

### 3. 执行模式

在顶部状态栏右侧可选择 Claude Code 的执行模式：

| 模式 | 说明 |
|------|------|
| 默认模式 (Normal) | 每次操作需手动确认，最安全 |
| 编辑模式 (Accept Edits) | 自动接受文件编辑，Bash 命令仍需确认 |
| 计划模式 (Plan) | 仅分析和制定计划，不执行任何修改 |
| 锁定模式 (Don't Ask) | 拒绝所有未授权操作，适合审查环境 |
| 自动模式 (Auto) | AI 安全分类器实时把关 |
| 绕过模式 (Bypass) | 完全跳过权限检查，仅适合隔离沙盒 |

### 4. 对话导出

将 Claude Code 对话记录导出为 HTML 文件：

1. 切换到 **Claude 启动器** 标签页
2. 输入或选择项目目录
3. 点击 **📄 导出对话**
4. 选择要导出的内容类型（用户消息、助手回复、思考过程、工具调用等）
5. 选择保存路径，程序将在后台生成 HTML

HTML 导出文件支持：
- 浏览器直接查看
- 打印 / 另存为 PDF
- 思考内容折叠展开
- 工具调用信息展示

### 5. Claude 启动器

- 输入项目目录路径，点击 **🚀 在此目录打开 Claude** 启动 Claude Code
- 支持自动启动：勾选"切换配置后自动在此目录打开 Claude"，应用配置后将自动启动
- 打开历史自动记录，支持一键重新打开

## 目录结构

```
ModelBuddyCC/
├── main.py                  # 程序入口
├── start.bat                # 开发启动脚本
├── README.md                # 本文件
└── app/                     # 应用模块包
    ├── constants.py         # 路径常量 & 执行模式
    ├── theme.py             # 主题颜色 & 字体
    ├── models.py            # 数据模型
    ├── balance.py           # 余额查询
    ├── config.py            # 配置管理器
    ├── export.py            # 对话导出（JSONL解析 + HTML生成）
    ├── dashboard.py         # 余额仪表盘弹窗
    ├── profile_dialog.py    # 配置编辑对话框
    ├── export_dialog.py     # 导出选项对话框
    └── main_window.py       # 主窗口
```

## 数据文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| Claude Code 配置 | `~/.claude.json` | Claude Code 的 env 配置 |
| 模型配置记忆 | `~/.claude/model_profiles.json` | 保存的多组配置 |
| 启动历史 | `~/.claude/launch_history.json` | 打开目录的历史记录 |
| 配置备份 | `~/.claude/backups/` | `.claude.json` 的自动备份 |
| 对话记录 | `~/.claude/projects/` | Claude Code 的对话 JSONL |

## 技术栈

- **GUI 框架:** [customtkinter](https://github.com/TomSchimansky/CustomTkinter)
- **打包工具:** [PyInstaller](https://pyinstaller.org/)
- **并发:** `concurrent.futures.ThreadPoolExecutor`
- **主题:** 自动跟随 Windows 系统明暗模式

## 许可证

MIT License
