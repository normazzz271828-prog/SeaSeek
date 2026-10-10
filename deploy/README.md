# 云端上线步骤

状态：Streamlit 前端已部署至 https://seaseek.streamlit.app；阿里云统一后端已部署，公网 HTTPS 与真实检测/视频业务验收通过。Streamlit 仍需填写真实 Secrets，完整云端页面验收待完成。

## 1. 先浏览云端首页

登录 https://share.streamlit.io，授权 GitHub 中的 SeaSeek 仓库，创建应用：

- Repository：`normazzz271828-prog/SeaSeek`
- Branch：`main`
- Main file path：`cloud/streamlit_app.py`
- Python：`3.12`
- 子域名：可尝试 `seaseek`，以平台显示的可用性为准。

没有后端配置也可以浏览首页和关于页。任务、影像、线索和协同页会显示准备中，不生成云端 SQLite 库，不自动启动 API。

若业务页提示运行 `start_local.ps1`，请检查应用的入口是否为上述 `cloud/streamlit_app.py`。根入口也会按监听地址识别云端，避免误连云机器的 localhost。云端使用嵌入的压缩背景图，不依赖平台静态路径；更新代码后可在 Manage app 中 Reboot app，再刷新浏览器。不要在 Secrets 中填写示例 API 地址或本机 `127.0.0.1` 地址；后端准备好后再填真实地址与令牌。

## 2. 准备统一后端

### 当前演示部署

- 独立 `/opt/seaseek` 程序、Python 3.12.15 虚拟环境、`/var/lib/seaseek` 持久数据与 `/etc/seaseek/api.env` 私密配置；系统 Python 保留原状。
- `seaseek-api.service` 仅监听本机 8766；CPU 版 Torch 2.11.0 / torchvision 0.26.0，模型按 provenance 校验。实际依赖记录在 `backend-verified-lock.txt`，安装脚本支持离线 wheelhouse。
- `seaseek-tunnel.service` 提供临时 HTTPS API；网站入口仍为 Streamlit。重新建立临时通道会改变地址，此时需要更新 Streamlit 的 API URL。后端数据独立于通道，保留原数据库即可。
- `install-server.sh` 以已有独立 Python 3.12 为参数，将其复制到 SeaSeek 自己的目录，只管理 SeaSeek 自己的路径和服务。
- 实际验收通过：公网健康检查、无令牌 401、任务、图像增强、船舶检测和中文标注、线索状态与报告、8 秒短视频的 4 个抽样帧、视频资源和关键帧、视频线索、重启后持久化。冷启动检测样例约 8.3 秒（含网络）；这是一次样例结果，不代表所有输入性能。
- 标注使用 Noto CJK 字体，单独放置于 `.tmp/fonts/NotoSansCJKsc-Regular.otf`，保留项目的字体路径回退逻辑。
- 当前 PAC-Net 仍以工作台显示的接入状态为准；这次部署验收不代表完成 PAC-Net 模型接入。

临时通道用于演示联调，没有可用性保证。自有域名就绪后可用 Nginx 模板接入 HTTPS，再修改 Secrets，保留同一业务数据库。官方说明：https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

### 重建或后续正式部署

先确认服务器剩余资源、操作系统、现有 Nginx 和拾光端口。以下文件都是待安装模板，未执行服务器变更：

- `seaseek-api.service`：独立 `seaseek` 用户、`/opt/seaseek` 程序、`/var/lib/seaseek` 数据、回环端口 `8766`、一个 worker。
- `api.env.example`：复制到 `/etc/seaseek/api.env`，填写随机服务密钥，限制该文件权限。密钥可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 在服务器生成。
- `nginx-seaseek.conf.example`：独立 API 主机名和 HTTPS 证书，转发到上述端口；不要覆盖拾光站点。

安装前创建服务用户、上述目录和 `/opt/seaseek/.tmp`；数据目录、缓存目录必须对 `seaseek` 可写。仓库代码和虚拟环境由该用户读取。先在 Python 3.12 虚拟环境安装 CPU 版 PyTorch/torchvision，再安装 `deploy/backend-requirements.txt`；不要使用云端界面的轻量 requirements 作为后端依赖。

模型不在仓库。单独把本地 `models/ship_obb.pt` 复制到服务器同名路径，校验 `models/provenance.json` 中的 SHA256。本地数据库不上传 GitHub；要保留演示任务，停写后备份数据库及对应视频目录，再迁移到统一数据目录。

服务器只有 2 核 2 GiB，且与拾光共用。模板约束一个 API worker、一个视频队列，CPU 配额为一个核；实际内存占用须部署后测量，不能据此承诺图片和视频并发性能。初版限制短视频，避免增加模型进程。

检查 `/health`、无密钥请求返回 401、正确密钥可读任务，再安装 Nginx 配置并检查 HTTPS。服务密钥控制前端到后端访问，不等于个人账号或角色权限；当前仍是演示作品。不要在公开演示中保存真实救援或个人资料。

## 3. 连接 Streamlit

在应用 Advanced settings / Secrets 中填写 `cloud/secrets.example.toml` 的真实值。不要把实际 Secrets 提交到仓库。`HAIXUN_API_URL` 是 HTTPS API 地址，不是网页首页地址；`HAIXUN_API_TOKEN` 与后端一致。

本地端也可通过相同环境变量或本地 `.streamlit/secrets.toml` 接入此后端。本地默认仍是 8765 开发库；正式联调时把两端指向同一地址，停止使用开发库作为另一套账号或业务源。

视频和关键帧通过 Streamlit 服务端带密钥读取，再由 Streamlit 提供给浏览器，避免把密钥写入 URL。

## 4. 必须完成的线上验收

1. 首页和五项导航正常，背景、玻璃、动画及手机布局可用。
2. 创建任务、图像增强、船舶检测和标注下载成功。
3. 提交线索、核实分派、更新状态、导出报告成功。
4. 用小视频验证提交、后台进度、播放、关键帧和线索。
5. 本地及云端连接同一后端，双方可读取同一任务；重启后数据仍存在。

GitHub 推送或首页可访问不代表功能验收通过。正式域名与微信小程序在本地及云端验收后再推进。

官方部署说明：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
