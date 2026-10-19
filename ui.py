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

INTERNAL_TASK_IDS=frozenset({'c2c2457908024d498291cda4823f6b50','cb89847e4849466bb4dda1e230123af8','80a89ff30d334994816b9cef359247de','7d44d789615d49689ce44f7fcf83ae84','9683a535971e4a199bfdc630937a6dd0','dbbb97f5eae145fc984ca9cb9c2be1af','b1ba1dbc9d4a43b7bea8033b62e4e42b','e6485f1813664f6fbb98c03143c75cc1'})

def public_tasks(tasks):
    visible=[dict(task) for task in tasks if task['id'] not in INTERNAL_TASK_IDS]
    for task in visible:
        if task['id']=='demo-coastal':
            task.update(name='近海联合搜救 · 示例任务',area='青岛近海',owner='示例任务',description='查看影像、核实线索并记录处置进展。')
    return visible

def api(method,path,*,binary=False,include_internal=False,**kwargs):
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
        if binary:return response.content
        data=response.json()
        if not include_internal and method=='GET':
            if path=='/tasks':return public_tasks(data)
            if path=='/overview':
                data['tasks']=public_tasks(data['tasks'])
                for field in ('clues','events'):data[field]=[row for row in data[field] if row['task_id'] not in INTERNAL_TASK_IDS]
        return data
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
    import html
    st.html(f'<section class="work-heading"><span>{html.escape(kicker)}</span><h1>{html.escape(heading)}</h1><p>{html.escape(description)}</p></section>')

def task_picker():
    tasks=api("GET","/tasks")
    if not tasks:
        st.info("请先到任务总览创建搜救任务。")
        finish_and_stop()
    ids=[t["id"] for t in tasks]
    current=st.session_state.get("active_task")
    if st.session_state.get('task_selection') not in ids:
        st.session_state.task_selection=current if current in ids else ids[0]
    context,refresh=st.columns([5,1],vertical_alignment='bottom')
    selected=context.selectbox("当前搜救任务",ids,index=None,format_func=lambda ident:next(t["name"]+" · "+ident[:6] for t in tasks if t["id"]==ident),key='task_selection',persist_state='session')
    if selected is None:
        st.info('请选择要接续的任务。')
        finish_and_stop()
    st.session_state.active_task=selected
    if refresh.button('刷新',icon=':material/refresh:',key='refresh_task',width='stretch'):
        st.rerun()
    return next(t for t in tasks if t["id"]==selected)

def capture_handoff(task):
    with st.popover('手机接续',icon=':material/devices:'):
        link=share_link('imaging',task['id'])
        st.caption('把链接发到手机，在同一任务里拍照或上传。另一设备提交后，点击刷新查看新记录。')
        st.code(link,language=None)
        st.link_button('打开任务采集页',link)

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
