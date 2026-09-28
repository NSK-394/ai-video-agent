# ai-video-agent 工作约定

## 上下文

- 本仓库在 Independent-Media 中负责视频分析、编辑蓝图和 DaVinci Resolve 自动化。
- 开始行为变更前读取 `../AGENTS.md`；跨仓库目标与契约以 `../docs/自媒体自动化工作流实施方案.md` 为准。
- 需要变更产物时写入 `../docs/changes/<change-id>/`，不要把决策只留在聊天中。

## 入口与边界

- CLI 入口：`main.py` 和已注册命令 `ai-video-agent`。
- 蓝图执行：`run_blueprint.py`；MCP 接口位于 `mcp/`。
- 核心模块：`analysis/`、`editor/`、`automation/`、`config/`、`utils/`。
- 保持 Python 3.10+ 兼容；Ruff 目标为 Python 3.11、行宽 100。
- 与 Independent-Media 的其他项目通过稳定 CLI、JSON/文件产物交互，不导入其他子仓库的私有模块。

## 实施与验证

- 先检查 `tests/` 中相邻用例；行为变化先建立失败证据并添加回归测试。
- 相关最小检查：`python -m pytest tests`。
- Python 代码检查：`ruff check .`；类型相关改动运行 `mypy .`。
- 涉及 FFmpeg、媒体文件或 DaVinci Resolve 的集成验证若环境不可用，明确记录未验证项，不用 Mock 成功替代真实结论。

## 安全

- 不提交媒体原件、渲染产物、模型文件、日志、`.env` 或凭证。
- 未经明确授权，不操作真实 DaVinci Resolve 项目或覆盖用户媒体。
