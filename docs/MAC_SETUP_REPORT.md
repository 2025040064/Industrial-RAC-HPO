# macOS 运行与验证记录（2026-11-09）

## 环境与变更

- 本机 macOS 26.6，Apple Silicon arm64，Python 3.11.18。Python、uv 缓存与虚拟环境保存在工程目录；LightGBM 所需 libomp 23.1.5 通过 Homebrew 安装。
- macOS 使用与原依赖同版本的 PySide6-Essentials 6.9.3，提供本项目使用的 QtCore、QtGui、QtWidgets 与 QtTest；其他平台保留 PySide6 6.9.3。锁文件中各包版本未发生变化。环境快照和运行时检查支持两种发行包。
- 两个验收脚本的原生模式交由 Qt 选择平台；修复 GUI 未列出已在回归后端支持的 Grid、Successive Halving、Hyperband。
- 使用项目 CLI 显式下载 Steel Energy 与 CNC Milling 公开数据；分别保存在 `datasets/raw/steel_energy` 和 `datasets/raw/cnc_milling_2025`。数据不包含在源代码发行中。

## 实际检查

- `./Setup.command` 完成依赖同步和导入检查；`uv pip check` 显示 43 个已安装包兼容。
- macOS 原生 Qt 测试创建实际主窗口：平台为 `cocoa`，窗口 `isVisible=True`，七个页面均已创建。首次沙箱内原生启动因无法连接桌面失败；在可访问桌面的会话中通过。未人工逐一检查全部分辨率与 DPI。
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --basetemp .cache/pytest-mac-final -o cache_dir=.cache/pytest-state`：301 passed，82.35 秒。包含真实数据的后台导入、训练、搜索与离线闭环测试；不构成生产验证。
- 首次完整测试时公开数据尚未下载，部分数据相关用例失败或跳过；下载数据后发现 GUI 算法列表与已有测试不一致，补回入口后完整测试通过。
- 本次未验证 Windows 平台；原 Windows 依赖声明与启动脚本保留。

## 使用

在工程目录运行 `./Run-GUI.command`，或在 Finder 双击该文件。新机器先按照 README 安装 uv 与 libomp，运行一次 `./Setup.command`。如需其他公开数据，应通过 CLI 或界面显式导入。
