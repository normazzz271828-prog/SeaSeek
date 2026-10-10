# 海寻 SeaSeek

融合 PAC-Net 特征增强的海面搜救协同平台。本地端与 Streamlit 云端共用界面和统一后端，当前按数字媒体比赛演示作品建设；PAC-Net 海面适配尚未完成。

## Streamlit 云端

仓库：`normazzz271828-prog/SeaSeek`，分支 `main`，部署入口 **`cloud/streamlit_app.py`**，Python **3.12**。不要误选根目录的本地入口。

前端 https://seaseek.streamlit.app 已接通阿里云统一后端与临时 HTTPS API，并完成真实船舶检测、视频、协同业务及重启持久化验证。云端四个业务页、从云端发起图片增强/检测及重新连接后读取标注结果验证通过。未配置 Secrets 时可浏览首页/关于页；业务页显示准备中，不创建云端数据库。

在 Streamlit Secrets 填写 `cloud/secrets.example.toml` 中的实际 API 地址与服务密钥。真实配置通过本地私密文件交付，不进入 Git。完整步骤见 [部署说明](deploy/README.md)。根目录 requirements 是本地依赖，cloud/requirements.txt 是轻量前端依赖，deploy/backend-requirements.txt 是后端依赖。

## 启动

在本目录执行 `powershell -ExecutionPolicy Bypass -File .\start_local.ps1`。

网站：http://127.0.0.1:8505。业务 API：http://127.0.0.1:8765/docs。

当前 `.venv` 复用本机已有 Streamlit 运行环境。换电脑请使用 Python 3.11 或以上创建虚拟环境，再执行 `python -m pip install -r requirements.txt`。

## 演示流程

第二版提供手机拍照、任务/线索直达链接和轻量媒体预览。任务选择器下展开“手机接续”复制链接；手机与电脑选择同一任务，通过“刷新任务记录”读取另一设备提交的数据。手机摄像头需要 HTTPS 和浏览器授权，未宣称已完成具体手机型号的实机验收。

分析详情 API 改为元数据，媒体独立读取 `/analyses/{id}/media/{original|result|detection}?size=preview|thumb|full`。默认仅加载当前视图的 JPEG 预览，勾选“准备高清图片下载”才读取无损 PNG。新分析结果与原图相同时以空 result 引用原图，旧独立 BLOB 兼容读取。`tools/compact_media.py` 可在备份并停止 API 后去除旧库逐字节相同的结果副本。

任务总览的“重置演示任务”只清 `demo-coastal` 及其关联记录和视频，其他任务保留；云端需要单独的演示管理口令 `HAIXUN_RESET_TOKEN`，不使用服务令牌。管理口令不要写入共享链接或提交 Git。

演示环境每会话每小时最多 60 次写请求、20 次图片分析；全局每小时最多 240 次写请求、100 次图片分析，分析存储最多 500 条。额度是单进程资源控制，并非用户权限，重启或新会话不是稳定身份。图片忙时拒绝重叠提交；图片与排队/运行中的视频互斥，视频显示前方任务数。

完整八步演练与现场检查见 [演示检查清单](deploy/DEMO_CHECKLIST.md)。

1. 首页进入搜救工作台，在任务总览载入演示任务或新建任务。
2. 影像分析选择示例图片，执行真实增强，对比并下载图片。
3. 将影像提交为待核实线索；坐标可选、由人工录入。
4. 在线索态势查看位置，在协同处置填写负责人、状态与反馈。
5. 导出 Markdown 报告或完整 JSON 记录。刷新页面验证记录仍然存在。

数据保存在 `data/haixun.sqlite`，含处理尺寸的原图与增强图。最长边 1600 像素，上传限 12 MB、2400 万像素。EXIF 旋转自动校正。

已接入原项目 YOLO11s-OBB 九类船舶模型，权重 SHA256 校验。默认原图检测，1024 正方形预处理；标注中文类别、旋转四边形与模型置信度。坐标基于最长边 1600 像素的处理图片，不是原始上传尺寸。降低阈值可能增加误检。尚未支持落水人员等目标。

视频页上传 MP4 或选择训练图片合成的 8 秒演示片，提交独立后台队列。最高 1080p、30 秒、12 MB，每秒抽取 0.5/1/2 帧，输出最长边 960 像素的 H.264 无音频抽样视频、逐帧 JSON 和关键帧。只保留抽样帧，不做跟踪，可能遗漏短暂目标，逐帧目标数量不能相加当作船舶总数。视频关键帧线索保存关联和时间点。最多三个待处理任务，单视频 worker、CPU 检测；模型调用使用锁避免图片和视频同时访问模型。取消可在下一帧停止，服务重启将未完成任务标记为失败，可重新提交。

本版未实现个人登录权限或 PAC-Net。默认 API 仅绑定本机；准备的远程服务需要访问密钥与 HTTPS，但服务密钥不等于用户身份和角色权限。

## 四端约定

本地端开发验证、Streamlit 云端部署验证，验收通过后再推广到独立域名网页端和微信小程序端。统一业务规则和后端数据源；当前 SQLite 为本地开发库，未来按统一后端迁移，不为每个端复制业务库。

## 素材来源

传统增强和去雾来自用户授权的 `D:/Projects/海面目标检测与识别/accuracy_lab/followup`，只调整模块导入。21 张示例覆盖九类，映射见 `assets/examples/sources.json`；训练划分共 4920 张、9710 个目标，见 `assets/dataset_summary.json`。未改写来源项目，不使用验证、确认或测试集作为样例，也未进行新训练。

权重位于 `models/ship_obb.pt`，不提交 Git；转移项目时按 `models/provenance.json` 单独复制并校验。演示视频是静态训练图片合成，不是真实航拍视频。

## 验证

`python -m unittest discover -s tests` 验证业务持久化、影像、处置及输入边界，使用独立临时库。启动本地 API 后，运行 `python tests/check_pages.py` 检查五个页面。
