# SeaSeek 独立域名网页端

域名：`seaseek.com.cn`、`www.seaseek.com.cn`；网页服务器：`123.57.79.17`。

网页复用已验证的 Streamlit 界面，代码位于 `/opt/seaseek-web/app`，独立环境位于 `/opt/seaseek-web/.venv`。服务为 `seaseek-web`，只监听 `127.0.0.1:8505`，由 Nginx 反向代理网站端口。保留现有宝塔面板。

业务数据继续由现有统一后端保存。`seaseek-backend-link` 使用专用 SSH 密钥，把网页服务器的 `127.0.0.1:8767` 转发到原服务器的 `127.0.0.1:8766`。原端授权密钥仅允许该目的端口转发，禁止交互命令；不复用其他项目私钥，不新建业务数据库。Streamlit 云端继续访问同一后端。

服务配置见 `seaseek-web.service`、`seaseek-backend-link.service`；HTTP 引导配置见 `nginx-web.conf.example`。环境配置在 `/etc/seaseek-web/web.env`，权限 `root:seaseek-web 640`：

```text
SEASEEK_RUNTIME=cloud
HAIXUN_API_URL=http://127.0.0.1:8767
HAIXUN_API_TOKEN=<与统一后端一致的服务令牌>
SEASEEK_PUBLIC_URL=https://seaseek.com.cn
SEASEEK_ICP_NUMBER=<用户提供的真实备案号；尚未提供时留空>
```

公网仅需网站 80/443 端口；SSH 按管理需求限制来源，8505/8767 不对公网开放。凭据、SSH 私钥、证书私钥和业务数据不提交 Git。

证书使用独立 `/opt/seaseek-web/certbot` 环境、Webroot `/var/lib/seaseek-web/acme`。先验证 DNS 与公网挑战文件访问，再签发包含主域名和 www 的证书，配置 HTTP 跳转 HTTPS，并设置自动续期和 Nginx 重载。

实际已签发证书，当前有效期至 2027-01-17，HTTPS 模板见 `nginx-web-https.conf.example`。服务器 IPv6 出站访问证书机构不稳定，使用 `certbot-ipv4.py` 限定证书客户端 IPv4，未改变系统 IPv6 配置。`seaseek-cert-renew.timer` 每日两次检查，续期成功后验证并重载 Nginx。

上线验收必须包括 HTTPS 证书、WebSocket 页面切换、图片增强与检测、实拍视频与关键帧、地图线索、处置反馈、报告导出及手机布局。内部健康检查或代码上传不等于公网验收完成。
