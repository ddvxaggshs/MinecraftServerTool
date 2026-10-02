# Minecraft Relay 3.8.1

多台 Windows 电脑轮流托管同一个 Minecraft 世界。程序更新仓库是
`ddvxaggshs/MinecraftServerTool`；世界存档仓库仍由设置里的 GitHub 地址指定，二者独立。

## 运行与升级

- 源码运行：双击 `Run-Source.vbs`。使用 pythonw 显示界面，不创建控制台。
- EXE 运行：解压完整的 Windows 程序包，双击 `MinecraftRelay.exe`。
- 首次升级到 3.8.0 必须手动安装一次：停服同步并退出所有旧版窗口，然后覆盖程序文件，保留原 `data/`。
- 源码版现在必须同时保留 `MinecraftRelay.py`、整个 `relay/`、启动脚本及 `apply-update.ps1`。
- 每次启动在后台读取 `main/update.json`，只比较 `state`；相同就不下载程序包。
- 状态不同则按当前运行方式下载 source 或 windows ZIP，校验 SHA-256 后暂存到 `data/updates/`。
- 正常退出且会话同步完成后，独立安装器等程序进程退出，备份旧文件再安装。下次启动使用新版本。
- 托管中不替换程序；强杀、关机或恢复未完成时不触发安装。下次正常退出再尝试。
- 网络失败或仓库尚未发布不会阻止开服。首次 GitHub 授权、Git/Java/playit 安装照常进行。
- 程序更新绝不覆盖 `data/`、本机 `config.json` 或服务器世界目录。
- 安装失败会尝试回滚，报告在 `data/updates/last-install.json`；旧文件备份也保留在那里。
- 同一个安装目录只允许一个新版实例运行。安装过程中再次启动会提示稍后重试。
- 可在 `data/config.json` 设置 `"auto_update": false` 关闭自动检查。

## 代码结构

| 文件 | 职责 |
|---|---|
| `MinecraftRelay.py` | 稳定启动入口 |
| `relay/app.py` | Qt 应用组装、启动和退出 |
| `relay/paths.py`、`relay/config.py` | 版本、路径、配置、恢复记录 |
| `relay/processes.py` | 隐藏命令窗口、依赖检测、Windows Job Object |
| `relay/setup.py`、`relay/settings.py` | 首次设置和设置窗口 |
| `relay/window.py` | 主界面、日志、状态显示 |
| `relay/lifecycle.py` | 开服、停服、存档同步、主机锁、恢复 |
| `relay/updater.py` | 状态比较、下载、校验、暂存 |
| `relay/instance.py` | 单实例和安装互斥 |
| `apply-update.ps1` | 退出后安装、失败回滚 |
| `tools/build_release.py` | 构建 EXE、两种更新包和状态文件 |

## 在新仓库发布

上传此目录的源码到 `https://github.com/ddvxaggshs/MinecraftServerTool` 的 `main` 分支。
遵守 `.gitignore`：不要上传 `data/`、存档、事故备份、构建目录或个人配置。

每次发布：

1. 修改 `relay/paths.py` 的 `VERSION`，以及 `release-state.json` 的 `state`、`version`。例如全部使用 `3.8.1`。
2. 提交代码到 `main`，创建并推送同名标签 `v3.8.1`。
3. GitHub Actions 自动构建并发布两个 ZIP，然后把带下载地址和 SHA-256 的 `update.json` 提交回 `main`。
4. 用户下次启动时发现状态改变，自动下载。版本状态必须每次发布唯一，不要复用旧标签。

初次发布使用 `v3.8.0`。GitHub 仓库必须启用 Actions，并允许工作流写入仓库；若 `main` 受分支保护，
可以手动提交构建输出的 `update.json`，但必须先上传两个 Release 资产。

也可本地双击 `Build-Windows.bat`。生成文件在 `dist/3.8.0/`（随版本变化），包括：

- `MinecraftRelay/`：可直接分发的完整 EXE 目录；无需另装 Python。
- `MinecraftRelay-windows.zip`、`MinecraftRelay-source.zip`：Release 更新资产，解压后文件直接位于根目录。
- `update.json`：最后发布到 GitHub `main` 的状态文件。

根目录的初始 `update.json` 没有资产地址，属于未发布占位状态，不代表程序已上线。
不要将源码仓库的 GitHub 自动打包 ZIP 当作更新资产。

## 存档交接

服主 Stop & Sync 成功后，下一台电脑才可接手。强制解锁不等于同步存档。
本次模块拆分和程序自动更新没有改动世界同步协议；旧的分叉或过期恢复会话仍需单独处理。
