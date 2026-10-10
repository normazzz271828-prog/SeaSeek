import streamlit as st
import json
from ui import ROOT, scene_style
from app_pages.views import overview, imaging, situation, collaboration, about
from app_pages.home import home

st.set_page_config(page_title="海寻 SeaSeek · 海面搜救协同平台",page_icon=":material/radar:",layout="wide")
# Deep links contain stable business IDs, separate from formatted widget labels.
entry=(st.query_params.get('task_id'),st.query_params.get('clue_id'))
if entry[0] and entry!=st.session_state.get('entry_link'):
    st.session_state.entry_link=entry
    st.session_state.active_task=entry[0]
    st.session_state.task_selection=entry[0]
    if entry[1]:
        st.session_state.clue_selection=entry[1]
        st.session_state.open_feedback=True
st.html(scene_style())
st.html((ROOT/"assets/style.css").read_text(encoding="utf-8"))
st.html(ROOT/"assets/liquid.css")
st.html((ROOT/"assets/page-motion.html").read_text(encoding="utf-8"),unsafe_allow_javascript=True)
pages=[
    st.Page(home,title="首页",icon="",default=True),
    st.Page(overview,title="任务总览",icon=""),
    st.Page(imaging,title="影像分析",icon=""),
    st.Page(situation,title="线索态势",icon=""),
    st.Page(collaboration,title="协同处置",icon=""),
    st.Page(about,title="关于海寻",icon=":material/info:",visibility="hidden"),
]
page=st.navigation(pages,position="top")
with st.container(key="masthead"):
    brand_col,about_col=st.columns([5,1],vertical_alignment="center")
with brand_col:
    if page.url_path!="":
        st.html('<div class="brand"><span class="brand-mark"><svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16"/><circle cx="20" cy="20" r="9"/><path d="M20 2v9M20 29v9M2 20h9M29 20h9M20 20l12-9"/></svg></span><div class="brand-word">海寻<small>SeaSeek · MARITIME RESCUE</small></div></div>')
if page.url_path=="":
    with about_col,st.container(key="about_entry"):
        st.page_link(pages[-1],label="关于海寻",icon=":material/radar:",width="content")
st.html('<script>window.haiXunGlass?.prepare('+json.dumps(page.url_path)+');</script>',unsafe_allow_javascript=True)
if page.url_path:
    st.caption('演示环境 · 演练位置为模拟；上传影像仅用于本次演示分析。')
try:
    page.run()
finally:
    st.html('<script>document.documentElement.classList.remove("hx-motion-paused");window.haiXunGlass?.enter('+json.dumps(page.url_path)+');</script>',unsafe_allow_javascript=True)
