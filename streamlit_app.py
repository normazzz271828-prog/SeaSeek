import streamlit as st
import json
import importlib
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parent

@st.cache_resource(max_entries=1,show_spinner=False)
def load_pages(revision):
    # Cloud can update the entrypoint without evicting imported page modules.
    # Reload once per reviewed source revision, not on each widget interaction.
    ui=importlib.reload(importlib.import_module('ui'))
    views=importlib.reload(importlib.import_module('app_pages.views'))
    landing=importlib.reload(importlib.import_module('app_pages.home'))
    return ui,views,landing

revision=hashlib.sha256(b''.join((ROOT/name).read_bytes() for name in ('ui.py','app_pages/views.py','app_pages/home.py'))).hexdigest()
ui,views,landing=load_pages(revision)
scene_style=ui.scene_style
overview,imaging,situation,collaboration,about=(getattr(views,name) for name in ('overview','imaging','situation','collaboration','about'))
home=landing.home

st.set_page_config(page_title="海寻 SeaSeek · 海面搜救协同平台",page_icon=":material/radar:",layout="wide")
# Deep links contain stable business IDs, separate from formatted widget labels.
entry=(st.query_params.get('task_id'),st.query_params.get('clue_id'))
if not entry[0]:st.session_state.pop('entry_link',None)
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
try:
    page.run()
finally:
    st.html('<script>document.documentElement.classList.remove("hx-motion-paused");window.haiXunGlass?.enter('+json.dumps(page.url_path)+');</script>',unsafe_allow_javascript=True)
