> 历史记录：本文描述上一版界面；当前56px固定导航及五页工作台规范见[UI_DESIGN.md](../UI_DESIGN.md)，验收见[工作台V2报告](UI_WORKBENCH_V2_REPORT.md)。

# 折叠侧边栏导航（方案 B）

日期：2026-10-30。范围：仅左侧导航 UI 与必要的布局适配；页面路由、应用服务、训练与搜索逻辑未改动。

## 1. 改动前现状

| 项 | 改动前 |
|---|---|
| 框架 | PySide6 6.9.3 桌面应用 |
| 侧边栏实现 | `main_window.py` 内联 `QWidget#sidebar` + `QListWidget#navigation` |
| 宽度 | 固定 178px，始终显示图标 + 文字 |
| 布局 | 位于 `QHBoxLayout` 中，占据独立列 |
| 选中态 | QSS `::item:selected`，背景 `#EAF3FF`，文字 `#007AFF` |
| 图标 | `theme.navigation_icon(index)`，24px 画布，固定 `secondary` 色 |
| 深色主题 | 工程只有一套浅色主题，无深色变量可适配 |

## 2. 改动后行为

| 交互 | 实现 |
|---|---|
| 默认收起 | 60px，仅图标；文字透明度为 0 |
| 鼠标进入 | 自动展开到 200px |
| 鼠标离开 | 90ms 延迟后收起（避免边缘抖动） |
| 动画 | 240ms `OutCubic`，宽度插值 |
| 图标位置 | 固定 x=20（面板内），动画全程不变 |
| 文字 | 随进度淡入，同时做 8px 位移 |
| 选中态 | 浅蓝药丸 `#E9F2FF` + 图标/文字 `#287BEA`，圆角 10px |
| 覆盖式布局 | 侧边栏是 body 的子控件，手动设置几何，`raise_()` 置顶；内容区固定 60px 左边距 |
| 键盘 | `QListWidget` 获得焦点即展开；焦点移出且鼠标不在栏内则收起 |
| 触摸 | 收起状态下点按菜单先展开（不切换页面）；顶部箭头按钮显式展开/收起 |
| 减少动画 | 读取 Windows `SPI_GETCLIENTAREAANIMATION`；为 0 时动画时长归零 |

### 视觉参数

| 参数 | 值 |
|---|---|
| 收起宽度 | 60px |
| 展开宽度 | 200px |
| 图标尺寸 | 20px |
| 菜单高度 | 42px |
| 菜单圆角 | 10px |
| 动画时长 | 240ms |
| 侧边栏背景 | `#FFFFFF` |
| 选中背景 | `#E9F2FF` |
| 选中图标/文字 | `#287BEA` |
| 普通文字 | `#667085` |

这些颜色写入 `theme.TOKENS` 的 `nav_text` / `nav_selected_bg` / `nav_selected`，不改动全局 `accent`（`#007AFF` 仍用于按钮与进度条），因此其他页面视觉不变。

## 3. 修改文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `src/rac_hpo/interfaces/gui/sidebar.py` | 新增 | `CollapsingSidebar`、`NavigationDelegate`、`reduced_motion_enabled`、`build_sidebar_navigation` |
| `src/rac_hpo/interfaces/gui/main_window.py` | 修改 | 侧边栏改为覆盖式子控件；body 增加 60px 左边距；`self.navigation` 仍指向同一 `QListWidget` |
| `src/rac_hpo/interfaces/gui/theme.py` | 修改 | 新增 3 个导航色 token；`navigation_icon` 支持颜色与尺寸；新增 `chevron_icon`；导航 QSS 改为无内边距 |
| `tests/integration/test_sidebar.py` | 新增 | 11 项侧边栏行为测试 |
| `docs/SIDEBAR_COLLAPSE_UI.md` | 新增 | 本文档 |
| `docs/images/sidebar-collapsed.png` 等 3 张 | 新增 | 收起 / 展开 / 动画中间态截图 |
| `CHANGELOG.md` | 修改 | 追加本轮记录 |

未改动：`application/`、`domain/`、`training/`、`optimization/`、`evaluation/`、`data/`、`infrastructure/`、五个页面文件、`workers.py`、`widgets.py`。

## 4. 关键实现说明

### 4.1 覆盖而非挤压

`body` 是一个普通 `QWidget`，内容通过 `QHBoxLayout` 排布并保留 60px 左边距；侧边栏作为 `body` 的子控件**不加入任何布局**，几何由 `_apply_geometry()` 在宿主 `resize` 事件里同步。展开时只改变自身宽度并覆盖在页面之上，`QStackedWidget` 的几何完全不动。

### 4.2 图标不抖动

图标绘制在 `NavigationDelegate.paint()` 中，位置为 `item_rect.left() + 12`。列表项左边固定为 0，因此图标横坐标恒为 20（60px 轨道内居中）。测试在 0 / 0.25 / 0.5 / 0.75 / 1.0 五个进度点采样，断言图标包围盒左边界始终相同。

### 4.3 圆角在收起态可见

`QListView` 的 item 矩形宽度取 `sizeHint`（184px），收起时会被视口裁掉右侧圆角。委托在绘制前把矩形宽度收敛到 `viewport().width()`，因此药丸在 44px 宽度下仍保留完整 10px 圆角。

### 4.4 防闪烁

- 离开后先等 90ms 再收起；期间重新进入会取消定时器。
- 动画中途改变方向时从**当前进度**续跑，不回到 0。
- 收起前用 `underMouse()` 二次确认鼠标确实不在栏内。
- 动画结束时强制落到精确目标值，避免缓动停在 0.99994 造成宽度差 1px。

### 4.5 文字溢出

委托用 `QFontMetrics.elidedText` 按可用宽度省略，最长项「超参数优化」在 200px 宽度下完整显示；窗口极窄或文字被替换为长名称时以 `…` 收尾，不撑破布局。

## 5. 验证结果

### 自动化测试

```
tests/integration/test_sidebar.py ................ 11 passed
tests/integration/test_gui.py     ................  7 passed
全量 tests/                        ............... 112 passed in 62.66s
```

侧边栏测试覆盖：

1. 默认 60px 收起
2. 悬停展开到 200px、离开收起
3. 展开不改变 `pages` 几何（覆盖式）
4. 五个进度点图标 x 不变
5. 收起态菜单文字区域无强调色像素（仅图标）
6. 五个菜单仍驱动 `QStackedWidget`
7. 箭头按钮展开/收起且 pin 状态正确
8. 键盘焦点展开
9. 快速移入移出不重置动画
10. 减少动画时零时长
11. 环境变量可覆盖减少动画检测

### 手动检查

- 收起态：60px 轨道，5 个图标，首项浅蓝药丸，底部不显示版本文字。
- 展开态：文字渐显，图标与收起态同列，底部「LightGBM · Optuna / App 0.1.0」淡入。
- 中间态（55%）：文字半透明，图标位置不变，页面内容未被挤压。

截图见 `docs/images/sidebar-*.png`。

### 未执行项

- 未在真实触摸屏上验证点按展开；离屏环境下以合成鼠标事件路径覆盖。
- 未做深色主题适配，工程当前只有浅色主题。
- 未在 Windows 开启「减少动画」的实机上比对，检测逻辑以环境变量测试覆盖。
