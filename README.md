# justVedio 0.1.2

Windows 10/11 64 位身份登录与视频观看助手。参考本机 `E:\Other\codex\vedio` 的 AnsweringVideo 0.2.4 创建独立项目，保留登录、队列、视频、导出和有效期功能，移除题库及答题流程。

## 启动

使用免安装包时，完整解压 `justVedio-Portable-0.1.2-x64.zip`，双击 `justVedio/justVedio.exe`。EXE 与 `_internal` 文件夹须保存在一起。包内包含 Python、Qt、OCR 模型、Playwright 驱动及备用 Chrome，无需另装 Python。

本地源码可双击 `启动软件.cmd`。从源码准备环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

完整复现开发及构建环境可安装 `requirements-lock.txt`；普通使用安装 `requirements.txt` 即可。程序优先发现系统 Chrome/Edge，也可手动选择浏览器 EXE。

## 使用

界面左侧是运行配置，分为“执行、视频、连接”三页；右侧是人数概览与人员任务。底部固定显示暂停、停止和启动操作。运行日志默认收起，保留最新消息，可点击“展开”或按 `Ctrl+L` 查看完整日志；`Ctrl+O` 导入身份。表格使用状态标签和进度条，长路径、消息及单元格可悬停查看完整内容，左右分栏可拖动调整。

1. 导入身份 Excel，或先保存空白模板。必需列为“所在的区县、姓名、身份证号”；身份证列使用文本。拒绝缺失、重复、格式错误及存在精度风险的身份证数据。
2. “启动测试”每次启动默认关闭。关闭时点击“启动登录验证”，登录成功后保留最近并发数量个会话；前台模式双击人员行可查看页面，后台会话保持隐藏。此模式不校验视频配置。
3. 开启“启动测试”后点击“启动测试”，执行登录→直接打开视频→正常播放到结束→保存结果→自动补位。无需题库。默认测试视频为 `https://www.bilibili.com/video/BV14zJY6WExr/`，可修改网址。
4. 并发默认 10，可设 1–30；一个身份从登录到观看结束共占一个名额。每人使用独立浏览器上下文，隔离 Cookie 和本地存储。
5. 左侧“执行”页中的“后台执行（隐藏浏览器）”与 `E:\Other\codex\webTi\Answering` 一致：默认勾选，仅浏览器不显示窗口，主界面始终保留，可查看人员进度、日志、结果并暂停或停止。取消勾选后可观察浏览器流程。设置保存供下次使用；批次使用启动时的配置，运行中锁定，结束后恢复编辑。
6. “暂停补位”只暂停新身份，当前身份继续。“停止”可等待当前身份全部完成，或立即中止。重试从登录重新执行未完成身份；同一模式已完成身份不重跑。
7. 每批保存“已完成信息统计.xlsx”“未完成信息统计.xlsx”“人员状态.json”。未完成表可重新导入；导出被占用时停止队列，解除占用后重新导出。界面及日志脱敏，统计文件保留完整身份信息。

关闭主窗口会结束程序并清理会话。后台执行不收起主界面、不进入托盘；双击后台人员记录也不会改变本批次的隐藏配置。运行期间申请阻止自动休眠，完成和异常退出时释放。手动睡眠、关机、断网或网站限制仍可能中断流程；程序不会将未确认的视频记为完成。

## 播放设置与后续扩展

保留静音、播放器元素、播放按钮、iframe、完成标志、下一视频和超时配置。连续视频默认上限 100 段。视频必须实际播放并到达结束状态，配置平台完成标志时还需该标志出现。停滞、页面关闭、解码失败和超时均记录失败。程序不修改播放位置、倍速或平台完成接口。

“视频”页中的“点击站内视频入口”保留基础选择器配置，例如 `text=观看视频`；具体网站按钮与页面适配留待后续，本版默认走“直接打开视频网址”。外站视频只接收视频页面请求，身份信息只填入登录网站。

设置空间为 `LocalTools/justVedio`，不自动迁移参考项目设置，结果默认保存在源码或 EXE 旁的 `results`。有效期至北京时间 **2027-05-20 当天**；次日 00:00 起提示“软件已过期，请联系1564532736@qq.com”，运行中的队列也会停止。本地时间校验不能防止修改电脑时间。

## 验证与构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py --smoke-test build/source-smoke
$env:QT_QPA_PLATFORM='windows'
$env:RUN_DESKTOP_TEST='1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_desktop.py
.\scripts\build_release.ps1
.\.venv\Scripts\python.exe scripts/verify_portable.py
.\.venv\Scripts\python.exe scripts/check_reference.py
```

离线自检使用合成身份、本机模拟登录站点和原创短视频，检查 12 人、10 路并发的登录→直接观看，以及 OCR 模型加载和统计导出；不会提交真实身份。显式桌面检查验证主界面持续可见且可操作、后台浏览器不显示窗口或抢占前台，以及取消勾选后的可见浏览器流程。最终便携包在新中文及空格目录解压，移除 Python 环境配置后运行 EXE 复验。实际结果见 `验证记录.md`。

外部公开测试视频和真实登录网站分别通过 `scripts/check_video.py`、`scripts/check_environment.py` 检查；环境检查只读取登录页面，不提交身份。真实身份验收需用户自己的身份表。

项目来源见 `SOURCE_REFERENCE.md`，第三方许可见 `THIRD_PARTY_NOTICES.md`。
