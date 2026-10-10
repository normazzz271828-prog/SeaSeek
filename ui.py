import os
import base64
from pathlib import Path
import requests
import streamlit as st
from runtime import API, API_TOKEN, CLOUD

ROOT=Path(__file__).resolve().parent

@st.cache_data(max_entries=1,show_spinner=False)
def scene_style():
    # Embedded, optimized asset avoids relying on a host's static-file route.
    image=base64.b64encode((ROOT/'static/rescue-background.jpg').read_bytes()).decode('ascii')
    return '<style>:root{--hx-scene-image:url("data:image/jpeg;base64,'+image+'");}</style>'

def finish_and_stop():
    # st.stop interrupts script execution before the entrypoint's finally can enqueue.
    # Finish the transition before requesting that stop, including cloud setup states.
    st.html('<script>window.haiXunGlass?.enter(document.documentElement.dataset.hxRoute);</script>',unsafe_allow_javascript=True)
    st.stop()

def api(method,path,*,binary=False,**kwargs):
    if not API:
        st.info("云端工作台正在准备中。你可以先浏览首页与平台介绍。")
        finish_and_stop()
    headers=dict(kwargs.pop('headers',{}))
    if API_TOKEN:
        headers['Authorization']='Bearer '+API_TOKEN
    try:
        response=requests.request(method,API+path,timeout=(8,90),headers=headers,allow_redirects=False,**kwargs)
        if response.is_redirect:
            raise requests.HTTPError('API redirect',response=response)
        response.raise_for_status()
        return response.content if binary else response.json()
    except requests.RequestException as exc:
        detail="云端工作台暂时无法连接，请稍后再试。" if CLOUD else "后端未连接，请通过 start_local.ps1 同时启动网站和 API。"
        if getattr(exc,"response",None) is not None:
            try:
                detail=exc.response.json().get("detail","请求失败")
            except ValueError:
                detail="后端请求失败"
        st.error(str(detail))
        finish_and_stop()

def title(kicker,heading,description):
    st.caption(kicker)
    st.title(heading)
    st.caption(description)

def task_picker():
    tasks=api("GET","/tasks")
    if not tasks:
        st.info("先到任务总览创建任务，或载入演示任务。")
        finish_and_stop()
    ids=[t["id"] for t in tasks]
    current=st.session_state.get("active_task")
    selected=st.selectbox("当前搜救任务",ids,index=ids.index(current) if current in ids else 0,format_func=lambda ident:next(t["name"] for t in tasks if t["id"]==ident))
    st.session_state.active_task=selected
    return next(t for t in tasks if t["id"]==selected)

def badge(status):
    color={"待核实":"orange","待分派":"blue","处理中":"blue","已完成":"green","已排除":"gray"}.get(status,"blue")
    st.badge(status,color=color)
