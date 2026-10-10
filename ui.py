import os
import base64
import uuid
from urllib.parse import urlencode
from pathlib import Path
import requests
import streamlit as st
from runtime import CLOUD, connection_settings

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
    api_url,api_token=connection_settings()
    if not api_url:
        st.info("云端工作台正在准备中。你可以先浏览首页与平台介绍。")
        finish_and_stop()
    headers=dict(kwargs.pop('headers',{}))
    if 'client_session' not in st.session_state:
        st.session_state.client_session=uuid.uuid4().hex
    headers['X-Seaseek-Session']=st.session_state.client_session
    if api_token:
        headers['Authorization']='Bearer '+api_token
    try:
        response=requests.request(method,api_url+path,timeout=(8,90),headers=headers,allow_redirects=False,**kwargs)
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
    if st.session_state.get('task_selection') not in ids:
        st.session_state.task_selection=current if current in ids else ids[0]
    selected=st.selectbox("当前搜救任务",ids,index=None,format_func=lambda ident:next(t["name"]+" · "+ident[:6] for t in tasks if t["id"]==ident),key='task_selection',persist_state='session')
    if selected is None:
        st.info('请选择要接续的任务。')
        finish_and_stop()
    st.session_state.active_task=selected
    with st.expander('手机接续 · 打开同一任务',icon=':material/devices:'):
        link=share_link('imaging',selected)
        st.code(link,language=None)
        st.caption('在手机浏览器打开此链接即可进入同一任务。点击刷新可查看另一设备的新记录。')
        st.link_button('打开任务采集页',link)
    if st.button('刷新任务记录',icon=':material/refresh:',key='refresh_task'):
        st.rerun()
    return next(t for t in tasks if t["id"]==selected)

def share_link(page,task,clue=None):
    from runtime import setting
    base=setting('SEASEEK_PUBLIC_URL','https://seaseek.streamlit.app' if CLOUD else 'http://127.0.0.1:8505')
    return base.rstrip('/')+'/'+page+'?'+urlencode(dict(task_id=task,**({'clue_id':clue} if clue else {})))

def media(ident,kind,version='',size='preview'):
    # Bounded per-browser cache; never expose service credentials to the client.
    cache=st.session_state.setdefault('image_media',{})
    key=(connection_settings(),ident,kind,version,size)
    if key not in cache:
        if len(cache)>=8:cache.pop(next(iter(cache)))
        cache[key]=api('GET',f'/analyses/{ident}/media/{kind}',params={'size':size},binary=True)
    return cache[key]

def badge(status):
    color={"待核实":"orange","待分派":"blue","处理中":"blue","已完成":"green","已排除":"gray"}.get(status,"blue")
    st.badge(status,color=color)
