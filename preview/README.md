# 海寻磨砂玻璃首页视觉预览

独立 HTML/CSS/JS 预览，业务入口指向现有 Streamlit 本地端。本轮用于确认视觉方向。

运行：`python -m http.server 8504 --bind 127.0.0.1 --directory preview`，访问 http://127.0.0.1:8504。

背景为 AI 生成的搜救主题装饰场景，不是现场影像。标题展示项目名称，实际算法接入状态以业务工作台为准。

动态效果由浏览器 CSS 实现，可在页脚暂停，并支持 prefers-reduced-motion。无视频背景、远程字体或第三方 JS 依赖。
