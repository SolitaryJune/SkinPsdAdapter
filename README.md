# 皮肤 PSD 自动适配工具

这是一个独立的本地工具，不依赖主小程序后端、数据库、权限系统。

## 功能

- 上传 PSD、包含 PSD 的 zip，或 PNG/JPG/WebP 设计图。
- 上传目标 `.bds` / `.bdi` 底包。
- 解析 `port/*.ini`、`res/default.css`、`res/*.til`。
- 按键切片后替换目标底包的 PNG 图集。
- 支持预览、导出重建 PSD、导出新 `.bds/.bdi`。
- PSD 导出默认使用“保留源 PSD 图层”模式：尽量保留原图层名、顺序和分层形态。

## 本地开发运行

Windows 双击：

```bat
start_windows.bat
```

macOS / Linux：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python start.py
```

启动后会自动打开浏览器。如果没有自动打开，手动访问终端显示的 `http://127.0.0.1:端口/`。

## Windows 单文件 EXE 打包

在 Windows PowerShell 里执行：

```powershell
.\build_windows.ps1 -Clean
```

产物在：

```text
dist\SkinPsdAdapter.exe
```

把 `dist\SkinPsdAdapter.exe` 这个单文件发给别人即可。普通用户不需要安装 Python，也不需要现场安装依赖。

注意：Windows `.exe` 必须在 Windows 环境打包。macOS/Linux 上的 PyInstaller 不能直接交叉打出 Windows 可执行文件。

## GitHub Actions 自动打包

仓库已提供工作流：

```text
.github/workflows/build-skin-psd-adapter.yml
```

触发方式：

- 手动运行：GitHub 仓库页面 -> Actions -> Build Skin PSD Adapter EXE -> Run workflow。
- 或推送本仓库改动后自动运行。

打包完成后，在 workflow run 的 Artifacts 里下载：

```text
SkinPsdAdapter-windows-exe
```

里面就是可直接发给别人的：

```text
SkinPsdAdapter.exe
```

## 当前边界

- PSD 导出是“重建版 PSD”：默认尽量保留原 PSD 图层名和顺序，但不保证保留智能对象、文字矢量、图层样式等 Photoshop 专有编辑能力。
- 面板解析清单已对齐小程序前端：`py_26`、`en_26`、`py_9`、`en_9`、`bh`、`num_9`、`num_9h`、`symbol`、`hw_grid`。
- 面板尺寸默认按小程序“以默认为准”规则解析；遇到 1080x641 这类 PNG 外框时，会优先收敛到 INI 真实键盘区。界面也提供“以图片为准”选项。
- 按键定位默认使用 `INI VIEW_RECT`；如果底包的 INI 坐标不准，可以切到 `TIL SOURCE_RECT 缩放定位`，用图集切片反推面板布局。
- 如果设计稿和目标底包键位布局差异极大，自动裁切可能需要人工微调。后续可以增加源布局 INI 上传或前端手动校正。
