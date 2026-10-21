# 来源与独立性

本项目参考用户提供的 `E:\Other\codex\vedio`（AnsweringVideo 0.2.4），在 `E:\Other\codex\justVedio` 独立创建，品牌为 justVedio，Python 包为 justvedio，设置空间为 LocalTools/justVedio。

沿用身份 Excel 导入、目标站点登录、验证码 OCR、浏览器发现、独立会话、队列、视频播放监测、脱敏、统计和有效期实现。移除题库、答题、评分及相应资源和依赖；新增 Windows 窗口隐藏管理、系统托盘、后台切换反馈、防自动休眠及专门验收。

开发开始时记录参考项目 67 个源文件/资源的 SHA-256，见 reference-hashes.json。scripts/check_reference.py 只读复核参考项目，写入仅发生在新项目。参考项目的历史构建、身份表、设置、结果和虚拟环境没有复制为新项目数据。

参考项目记录其登录逻辑更早来源于 https://github.com/tellmai/web-login-assistant.git；本说明保留来源，不为参考代码新增源码许可。

## 0.1.1 后台执行修正

依据用户指定的 `E:\Other\codex\webTi\Answering`，采用“后台执行（隐藏浏览器）”复选项：默认勾选、保存偏好、批次启动时锁定，使用相同的 `headless=background` 浏览器启动机制。主界面始终显示，保留日志、进度和暂停/停止操作；取消勾选时启动可见浏览器。移除 0.1.0 的托盘和运行中 Windows 窗口显隐控制。有效期、防自动休眠和其他业务流程保留。

新增参考项目只读摘要见 webti-reference-hashes.json，覆盖所参考的 6 个源码/说明文件；没有修改该项目。
