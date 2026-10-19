import base64
import html
import io
import json
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st
from PIL import Image

from ui import ROOT, api, badge, task_picker, title, media, share_link, capture_handoff
from runtime import CLOUD

METHODS={"自动增强":"adaptive","提亮暗部":"gamma_light","压低过亮区域":"gamma_dark","局部对比度":"clahe","温和去雾":"dehaze_mix","保留原图":"original"}

def page_items(items,key,size=3):
    pages=max(1,(len(items)+size-1)//size)
    page=min(max(0,st.session_state.get(key,0)),pages-1)
    st.session_state[key]=page
    previous,label,following=st.columns([1,2,1],vertical_alignment='center')
    if previous.button('上一页',key=key+'_previous',disabled=page==0,width='stretch'):
        st.session_state[key]=page-1
        st.rerun()
    label.caption(f'第 {page+1} / {pages} 页 · 共 {len(items)} 条')
    if following.button('下一页',key=key+'_next',disabled=page==pages-1,width='stretch'):
        st.session_state[key]=page+1
        st.rerun()
    return items[page*size:(page+1)*size]

def management_panel(tasks):
    with st.expander('资源管理 · 存储与清理',icon=':material/storage:'):
        st.caption('只在需要时读取存储信息。清理先预览再确认，不删除任务或文字线索。')
        code=st.text_input('清理管理口令',type='password',key='cleanup_code') if CLOUD else ''
        headers={'X-Seaseek-Reset':code}
        if st.button('查看存储用量'):
            st.session_state.storage_info=api('GET','/admin/storage',headers=headers)
        info=st.session_state.get('storage_info')
        if info:
            a,b,c=st.columns(3)
            a.metric('影像记录',f"{info['analyses']} / {info['analysis_limit']}")
            b.metric('影像内容',f"{info['image_bytes']/1024**2:.1f} MB")
            c.metric('磁盘剩余',f"{info['disk_free']/1024**3:.1f} GB")
            st.caption(f"数据库占用 {info['database_bytes']/1024**2:.1f} MB，其中 {info['reusable_bytes']/1024**2:.1f} MB 可供后续写入复用；删除记录不会立即缩小数据库文件。")
        ident=st.selectbox('清理哪个任务',[t['id'] for t in tasks],format_func=lambda ident:next(t['name']+' · '+ident[:6] for t in tasks if t['id']==ident),key='cleanup_task')
        linked=st.checkbox('包括已关联线索的影像（保留文字线索，移除影像关联）')
        selection=dict(task_id=ident,include_linked=linked)
        if st.button('预览清理范围'):
            st.session_state.cleanup_preview=(selection,api('POST','/admin/cleanup/preview',json=selection,headers=headers))
        stored=st.session_state.get('cleanup_preview')
        if stored and stored[0]==selection:
            plan=stored[1]
            st.write(f"将清理 {len(plan['images'])} 张影像、{len(plan['videos'])} 条失效视频；{plan['linked_clues']} 条线索将失去影像关联。")
            if plan['images']:st.dataframe(pd.DataFrame(plan['images'])[['name','bytes','linked']],hide_index=True)
            st.caption('处理中的视频、成功的视频、实拍示例素材及其他任务均保留。请先导出需要的报告与影像。')
            confirmed=st.checkbox('确认按本次预览清理资源',key='cleanup_confirm_'+plan['confirmation'])
            if st.button('执行本次清理',disabled=not confirmed or not (plan['images'] or plan['videos'])):
                outcome=api('POST','/admin/cleanup',json=dict(**selection,confirmation=plan['confirmation']),headers=headers)
                st.session_state.storage_info=outcome['storage']
                st.session_state.pop('cleanup_preview',None)
                st.session_state.pop('image_media',None)
                st.success('已清理选定资源。任务与文字线索已保留。')

def next_steps(task):
    st.caption('下一步：核实影像 → 定位线索 → 记录处置')
    a,b=st.columns(2)
    a.link_button('查看线索态势',share_link('situation',task['id']),width='stretch')
    b.link_button('进入协同处置',share_link('collaboration',task['id']),width='stretch')

def overview():
    st.html('<section class="hero"><div class="eyebrow">SeaSeek · MARITIME SEARCH & RESCUE</div><h1>海寻<span>.</span></h1><p class="subtitle">融合 PAC-Net 特征增强的海面搜救协同平台</p><p class="tagline">以影像为线索，向希望靠近。</p><span class="tag">影像感知 / 线索态势 / 协同响应</span></section>')
    left,right=st.columns([3,1],vertical_alignment="center")
    with left:
        st.subheader("任务总览")
        st.caption("搜索、分析、行动。所有进展都留在任务里。")
    with right:
        if st.button("打开示例任务",icon=":material/play_arrow:",width="stretch"):
            st.session_state.active_task=api("POST","/demo")["id"]
            st.session_state.task_selection=st.session_state.active_task
            st.rerun()
    snapshot=api('GET','/overview')
    tasks=snapshot['tasks']
    clues=snapshot['clues']
    for col,label,value in zip(st.columns(4),["进行中任务","待核实线索","处理中线索","已完成线索"],[len([t for t in tasks if t["status"]=="进行中"]),sum(c["status"]=="待核实" for c in clues),sum(c["status"]=="处理中" for c in clues),sum(c["status"]=="已完成" for c in clues)]):
        col.metric(label,value)
    st.space("small")
    with st.expander("新建搜救任务",icon=":material/add_circle:",expanded=not tasks):
        with st.form("new_task"):
            a,b=st.columns(2)
            name=a.text_input("任务名称",placeholder="例如：近海联合搜救")
            area=b.text_input("搜救海域",placeholder="例如：青岛近海")
            owner=a.text_input("任务负责人")
            description=st.text_area("任务说明",placeholder="记录任务背景、搜索范围和注意事项")
            if st.form_submit_button("创建任务",type="primary"):
                if not all(v.strip() for v in (name,area,owner)):
                    st.warning("请填写任务名称、海域和负责人。")
                else:
                    st.session_state.active_task=api("POST","/tasks",json=dict(name=name,area=area,owner=owner,description=description))["id"]
                    st.session_state.task_selection=st.session_state.active_task
                    st.rerun()
    if not tasks:
        st.info("暂无搜救任务。创建任务，开始采集影像与整理线索。")
        return
    with st.popover('管理与维护',icon=':material/settings:'):
        management_panel(api('GET','/tasks',include_internal=True))
        with st.expander('重置演示任务',icon=':material/restart_alt:'):
            st.caption('只恢复“近海联合搜救 · 演示任务”，删除其影像、线索、视频和记录；其他任务保留。')
            reset_code=st.text_input('演示管理口令',type='password') if CLOUD else ''
            confirmed=st.checkbox('我确认清理演示任务并恢复三条初始线索')
            if st.button('确认重置演示',disabled=not confirmed):
                api('POST','/demo/reset',headers={'X-Seaseek-Reset':reset_code})
                for key in ('analysis_id','video_id','image_media','task_selection','clue_selection','entry_link'):
                    st.session_state.pop(key,None)
                st.session_state.active_task='demo-coastal'
                st.success('演示任务已恢复。')
                st.rerun()
    main,side=st.columns([1.7,1])
    with main:
        st.subheader("当前任务")
        for task in page_items(tasks,'overview_tasks'):
            with st.container(border=True,key=f"glass_task_{task['id']}"):
                st.markdown(f"### {task['name']}")
                summary=task['area']+(f" · 负责人：{task['owner']}" if task['id']!='demo-coastal' else '')
                st.caption(summary)
                st.write(task["description"])
                if st.button("进入影像分析",key=f"task_{task['id']}",icon=":material/arrow_forward:"):
                    st.session_state.active_task=task["id"]
                    st.session_state.task_selection=task["id"]
                    st.switch_page(st.Page(imaging,title="影像分析"))
    with side:
        st.subheader("最近动态")
        events=snapshot['events']
        if not events:st.caption('暂无最新动态。任务进展将在这里更新。')
        for item in page_items(sorted(events,key=lambda e:(e["created"],e["id"]),reverse=True),'overview_events'):
            with st.container(border=True,key=f"glass_event_{item['id']}"):
                st.caption(item["created"])
                st.write(item["message"])

def clue_form(task,analysis_id=None,key="clue",target=None):
    with st.form(key):
        heading=st.text_input("线索标题",value=f"疑似{target['category']}" if target else '',placeholder="描述疑似目标或需要核实的情况")
        notes=st.text_area("核实备注",value=f"模型预测：{target['category']}，置信度 {target['score']:.1%}；原图处理尺寸像素坐标：{json.dumps(target['points'])}。待人工核实。" if target else '',placeholder="请依据影像记录核实意见。")
        positioned=st.checkbox("已知位置（人工录入）")
        a,b=st.columns(2)
        lat=a.number_input("纬度",min_value=-90.,max_value=90.,value=36.02,format="%.6f")
        lon=b.number_input("经度",min_value=-180.,max_value=180.,value=120.44,format="%.6f")
        if st.form_submit_button("提交待核实线索",type="primary"):
            if not heading.strip():
                st.warning("请填写线索标题。")
            else:
                api("POST","/clues",json=dict(task_id=task["id"],analysis_id=analysis_id,title=heading,notes=notes,lat=lat if positioned else None,lon=lon if positioned else None))
                st.success("线索已保存，可在协同处置中核实和分派。")
                next_steps(task)

def imaging():
    title("OBSERVE / ANALYZE","影像分析","把现场影像转化为可核实的搜救线索。")
    task=task_picker()
    image_tab,video_tab=st.tabs(["图片分析","视频分析"],key="analysis_tab",on_change="rerun")
    if image_tab.open:
        with image_tab:
            with st.container(border=True,key="glass_analysis_controls"):
                source_col,settings_col=st.columns([1,1],gap="large")
                with source_col:
                    st.subheader("现场影像")
                    capture_handoff(task)
                    source=st.segmented_control("影像来源",["手机拍照","上传图片","示例图片"],default="示例图片")
                    uploaded=None
                    examples=sorted((ROOT/"assets/examples").glob("*.jpg"))
                    if source=='手机拍照':
                        uploaded=st.camera_input('拍摄现场影像',resolution='720p',key='scene_camera')
                        st.caption('允许浏览器访问摄像头后拍照；也可以切换到上传图片，选择手机相册。')
                    elif source=="上传图片":
                        uploaded=st.file_uploader("上传现场影像",type=["jpg","jpeg","png"],max_upload_size=12)
                    elif source=='示例图片' and examples:
                        sample=st.selectbox("海面示例",examples,format_func=lambda p:p.stem)
                        st.caption("选择样例影像，或上传现场图片。")
                    else:
                        st.info("暂无示例，请上传图片。")
                with settings_col:
                    st.subheader("分析设置")
                    method=st.selectbox("增强方法",list(METHODS))
                    detect_ships=st.checkbox("同时标注船舶",value=True)
                    confidence=st.slider("模型置信度阈值",.05,.95,.25,.05)
                    st.caption("对原图进行船舶检测，可按画面情况调整阈值。")
                    if st.button("开始分析",type="primary",icon=":material/auto_fix_high:",width="stretch"):
                        raw=uploaded.getvalue() if uploaded else (sample.read_bytes() if source=="示例图片" and examples else None)
                        if raw is None:
                            st.warning("请先选择图片。")
                        else:
                            with st.status("正在分析现场影像…",expanded=True) as status:
                                st.write("读取图片并执行增强")
                                result=api("POST","/analyses/upload",params=dict(task_id=task["id"],name=uploaded.name if uploaded else sample.name,method=METHODS[method]),data=raw,headers={"Content-Type":"application/octet-stream"})
                                st.session_state.analysis_id=result["id"]
                                if detect_ships:
                                    st.write("识别船舶目标")
                                    api("POST",f"/analyses/{result['id']}/detect",json=dict(confidence=confidence,source="original"))
                                status.update(label="分析完成，结果已保存",state="complete",expanded=False)
            history=api("GET","/analyses",params={"task_id":task["id"]})
            if history:
                ids=[a["id"] for a in history]
                selected=st.session_state.get("analysis_id")
                selected=st.selectbox("已保存的分析",ids,index=ids.index(selected) if selected in ids else 0,format_func=lambda ident:next(f"{a['name']} · {a['created']} · {ident[:6]}" for a in history if a["id"]==ident))
                st.session_state.analysis_id=selected
            if not history:
                with st.container(border=True,key="glass_analysis_empty"):
                    st.subheader("等待一张现场影像")
                    st.caption("选择示例或上传图片，开始分析后查看原图与增强结果。")
                    if source=="示例图片" and examples:
                        st.image(str(sample),width="stretch")
            else:
                result=api("GET",f"/analyses/{selected}")
                detection=result.get('detection')
                st.caption(f"{result['name']} · {result['width']} × {result['height']} · 增强方式：{result['selected']}")
                canvas,details=st.columns([1.8,1],gap="large")
                with canvas:
                    options=["船舶标注","并排对比","原图","增强结果"] if detection else ["并排对比","原图","增强结果"]
                    view=st.segmented_control("查看方式",options,default=options[0],key=f"image_view_{selected}_{bool(detection)}")
                    if view=="并排对比":
                        a,b=st.columns(2)
                        a.image(media(selected,'original'),caption="原图预览",width="stretch")
                        b.image(media(selected,'original' if result['result_is_original'] else 'result'),caption="增强结果预览",width="stretch")
                    elif view=="船舶标注":
                        st.image(media(selected,'detection',detection['created']),caption="船舶识别结果",width="stretch")
                    else:
                        st.image(media(selected,'original' if view=='原图' or result['result_is_original'] else 'result'),width="stretch")
                    with st.expander("图片下载",icon=":material/download:"):
                        if st.checkbox('准备高清图片下载',key=f'download_{selected}'):
                            enhanced=media(selected,'result',size='full')
                            original=media(selected,'original',size='full')
                            canvas=Image.new('RGB',(result['width']*2,result['height']))
                            canvas.paste(Image.open(io.BytesIO(original)),(0,0))
                            canvas.paste(Image.open(io.BytesIO(enhanced)),(result['width'],0))
                            out=io.BytesIO();canvas.save(out,format='PNG')
                            a,b=st.columns(2)
                            a.download_button('下载增强图片',enhanced,file_name='seaseek_enhanced.png',mime='image/png')
                            b.download_button('下载对比图片',out.getvalue(),file_name='seaseek_comparison.png',mime='image/png')
                            if detection:st.download_button('下载船舶标注图',media(selected,'detection',detection['created'],size='full'),file_name='seaseek_ships.png',mime='image/png')
                with details:
                    if detection:
                        st.subheader(f"检测目标 · {len(detection['predictions'])}")
                        st.caption(f"检测输入：{'原图' if detection['source']=='original' else '增强图'} · 阈值 {detection['confidence']:.0%}。")
                        if detection['predictions']:
                            st.dataframe(pd.DataFrame([dict(目标=f"{i+1:02d}",类别=p['category'],模型置信度=f"{p['score']:.1%}") for i,p in enumerate(detection['predictions'])]),hide_index=True)
                        else:
                            st.info("当前阈值下没有检测到船舶，可降低阈值重试；不代表影像中一定没有船。")
                        st.download_button("下载检测坐标",json.dumps(detection,ensure_ascii=False,indent=2),file_name="seaseek_ships.json",mime="application/json",width="stretch")
                    review=result.get('review')
                    st.caption('人工核实：'+({'confirmed':'已确认目标','ignored':'已忽略结果'}.get(review['decision'],'待核实') if review else '待核实'))
                    confirm,ignore=st.columns(2)
                    for col,label,decision in ((confirm,'确认目标','confirmed'),(ignore,'忽略结果','ignored')):
                        if col.button(label,key=f'{decision}_{selected}'):
                            api('POST',f'/analyses/{selected}/review',json={'decision':decision})
                            st.rerun()
                    if st.button("按当前阈值重新检测",icon=":material/refresh:"):
                        with st.spinner("正在检测船舶…"):
                            api("POST",f"/analyses/{selected}/detect",json=dict(confidence=confidence,source="original"))
                        st.session_state.pop('image_media',None)
                        st.rerun()
                    with st.expander("将这张影像提交为搜救线索",icon=":material/add_location_alt:"):
                        if review and review['decision']=='ignored':
                            st.info('该结果已忽略。需要生成线索时请先重新确认目标。')
                            return
                        target=None
                        if detection and detection['predictions']:
                            target_index=st.selectbox('关联检测目标',list(range(len(detection['predictions']))),format_func=lambda i:f"{i+1:02d} · {detection['predictions'][i]['category']}")
                            target=detection['predictions'][target_index]
                        clue_form(task,selected,f"image_clue_{selected}_{target_index if target else 'manual'}",target=target)
    if video_tab.open:
        with video_tab:
            video_panel(task)

def video_panel(task):
    st.subheader("短视频船舶检测")
    st.caption("选择实拍短片或上传自己的视频。最高 1080p、30 秒、12 MB；抽帧结果无音频，不做目标跟踪或唯一船舶计数。")
    if st.session_state.pop('video_open_result',False):
        st.session_state.video_workspace='查看结果'
    workspace=st.segmented_control('视频工作区',['提交素材','查看结果'],default='提交素材',key='video_workspace')
    if workspace=='查看结果':
        items=api('GET','/videos',params={'task_id':task['id']})
        if not items:
            st.info('暂无视频记录，请先提交视频进行分析。')
            return
        ids=[v['id'] for v in items]
        current=st.session_state.get('video_id')
        ident=st.selectbox('视频任务记录',ids,index=ids.index(current) if current in ids else 0,format_func=lambda ident:next(v['name']+' · '+v['created']+' · '+ident[:6] for v in items if v['id']==ident))
        st.session_state.video_id=ident
        item=next(v for v in items if v['id']==ident)
        if item['status'] in ('queued','running'):
            video_result(ident,task)
        else:
            show_video_status(ident,task,api('GET',f'/videos/{ident}'))
        return
    a,b=st.columns([1,2],gap='large')
    with a:
        source=st.segmented_control('视频来源',['实拍示例','上传视频','合成样片'],default='实拍示例',key='video_source')
        content=None
        name=''
        sample=None
        demo=ROOT/'assets/demo_ships.mp4'
        if source=='实拍示例':
            samples=api('GET','/video-samples')
            if samples:
                ident=st.selectbox('实拍短片',[item['id'] for item in samples],format_func=lambda ident:next(item['label'] for item in samples if item['id']==ident))
                sample=next(item for item in samples if item['id']==ident)
                st.caption(f"{sample['seconds']:g} 秒 · {sample['width']} × {sample['height']} · {sample['bytes']/1024/1024:.1f} MB")
                st.caption(sample['purpose'])
                name=sample['label']+'.mp4'
                # Keep at most one small input preview per session; do not fetch other clips.
                cached=st.session_state.get('video_sample_preview')
                identity=(task['id'],ident,sample['sha256'])
                if not cached or cached[0]!=identity:
                    cached=(identity,api('GET',f'/video-samples/{ident}/media',binary=True))
                    st.session_state.video_sample_preview=cached
                content=cached[1]
            else:st.info('暂无实拍样片，请上传视频。')
        elif source=='上传视频':
            uploaded=st.file_uploader("上传 MP4",type=['mp4'],max_upload_size=12,key='video_upload')
            if uploaded:
                content=uploaded.getvalue()
                name=uploaded.name
        elif source=='合成样片' and demo.exists():
            content=demo.read_bytes()
            name='训练图片合成样片片.mp4'
        rate=st.select_slider("每秒检测帧数",[.5,1.,2.],value=.5)
        st.caption('默认每两秒检测一帧，可按目标运动速度调整。')
        conf=st.slider("视频模型置信度阈值",.05,.95,.25,.05,key='video_conf')
        if st.button("开始视频分析",type='primary',icon=':material/play_arrow:'):
            if content:
                item=api('POST','/videos',params=dict(task_id=task['id'],name=name,confidence=conf,sample_fps=rate),data=content,headers={'Content-Type':'video/mp4'})
                st.session_state.video_id=item['id']
                st.session_state.video_open_result=True
                st.rerun()
            else:st.warning('请选择视频。')
    with b:
        with st.container(border=True,key='glass_video_preview'):
            st.subheader('素材预览')
            if content:st.video(content)
            else:st.info('选择一段短片后在此预览。')
            st.caption('预览素材，确认后提交分析。')
            if sample:
                with st.expander('素材来源与适用范围'):
                    st.write(sample['source'])
                    st.caption(sample['provenance'])
            elif source=='合成样片':
                st.caption('训练集静态图片合成，非真实航拍视频。')
        st.caption('识别结果供线索核实参考，小型船舶与复杂场景可能存在偏差。')

@st.fragment(run_every='3s')
def video_result(ident,task):
    result=api('GET',f'/videos/{ident}')
    status=result['status']
    if status in ('queued','running'):
        st.progress(result['progress'],text=f"等待队列 · 前方 {result.get('ahead',0)} 个任务" if status=='queued' else '正在抽帧并标注船舶')
        if st.button('取消检测',key=f'cancel_{ident}'):
            api('POST',f'/videos/{ident}/cancel')
            st.rerun()
        return
    st.rerun()

def show_video_status(ident,task,result):
    status=result['status']
    if status=='failed':
        st.error(result['error']);return
    if status=='cancelled':
        st.info('该视频任务已取消。');return
    video_completed(ident,task,result)

def video_completed(ident,task,result):
    data=result['results']
    st.success(f"检测完成 · {len(data['frames'])} 个抽样帧 · {data['sample_fps']:g} 帧/秒")
    st.caption('视频播放的是抽样帧标注结果。抽帧可能遗漏短暂出现的目标；各帧目标数不代表唯一船舶数。')
    st.caption('船型判断请结合影像核实。')
    records=data['frames']
    playback,frames=st.tabs(['标注视频','关键帧核实'],key=f'video_result_view_{ident}',on_change='rerun')
    if playback.open:
        with playback:
            video=api('GET',f'/videos/{ident}/media/result',binary=True)
            st.video(video)
            st.download_button('下载标注视频',video,file_name='seaseek_video.mp4',mime='video/mp4',key=f'video_media_download_{ident}')
    if frames.open:
        with frames:
            st.dataframe(pd.DataFrame([dict(时间秒=r['time'],该帧目标数=len(r['predictions']),类别='、'.join(sorted({p['category'] for p in r['predictions']}))) for r in records]),hide_index=True)
            index=st.select_slider('关键帧切换（抽样帧）',options=list(range(len(records))),format_func=lambda i:f"{records[i]['time']:.1f}s",key=f'frame_{ident}')
            st.image(api('GET',f'/videos/{ident}/frames/{index}',binary=True),caption=f"{records[index]['time']:.1f}s · {len(records[index]['predictions'])} 个预测目标",width='stretch')
            st.download_button('下载逐帧检测记录',json.dumps(data,ensure_ascii=False,indent=2),file_name='haixun_video.json',mime='application/json',key=f'video_download_{ident}')
            with st.form(f'video_clue_{ident}'):
                title_text=st.text_input('视频线索标题',value=f"视频 {records[index]['time']:.1f}s 疑似船舶")
                note=st.text_area('人工核实备注')
                if st.form_submit_button('提交视频线索',type='primary'):
                    if not title_text.strip():st.warning('请填写标题。')
                    else:
                        api('POST',f'/videos/{ident}/clues',json=dict(frame_index=index,title=title_text,notes=note))
                        st.success('视频线索已保存。')

def situation():
    title("LOCATE / VERIFY","线索态势","让线索拥有位置，让位置关联行动。")
    task=task_picker()
    clues=api("GET","/clues",params={"task_id":task["id"]})
    selected_status=st.pills("状态筛选",["待核实","待分派","处理中","已完成","已排除"],selection_mode="multi")
    filtered=[c for c in clues if not selected_status or c["status"] in selected_status]
    mapped=[dict(c,color=[8,127,140,210] if c["status"]!="待核实" else [222,155,52,210]) for c in filtered if c["lat"] is not None]
    a,b=st.columns([1.8,1])
    with a:
        with st.container(border=True,key="glass_map"):
            st.subheader("搜救海域")
            st.caption("根据已录入坐标查看线索分布。")
            if mapped:
                latitude=sum(c["lat"] for c in mapped)/len(mapped)
                longitude=sum(c["lon"] for c in mapped)/len(mapped)
                st.pydeck_chart(pdk.Deck(map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",initial_view_state=pdk.ViewState(latitude=latitude,longitude=longitude,zoom=10),layers=[pdk.Layer("ScatterplotLayer",mapped,get_position="[lon,lat]",get_fill_color="color",get_radius=250,radius_min_pixels=7,pickable=True)],tooltip={"text":"{title}\n{status}"}),height=430)
                st.dataframe(pd.DataFrame(mapped)[["title","lat","lon","status"]],hide_index=True)
            else:
                st.info("当前筛选下没有已定位线索。无坐标线索仍可核实和处置。")
        with st.expander("人工添加线索"):
            clue_form(task,key="manual_clue")
    with b:
        st.subheader(f"线索列表 · {len(filtered)}")
        for clue in filtered:
            with st.container(border=True,key=f"glass_map_clue_{clue['id']}"):
                badge(clue["status"])
                st.markdown(f"**{clue['title']}**")
                st.caption(f"负责人：{clue['assignee'] or '未分派'} · {'人工定位' if clue['lat'] is not None else '待定位'}")
                st.write(clue["notes"])

                st.link_button('打开线索处置',share_link('collaboration',task['id'],clue['id']))

def collaboration():
    title("COORDINATE / RESPOND","协同处置","核实线索、分派行动，保存每一次现场反馈。")
    task=task_picker()
    clues=api("GET","/clues",params={"task_id":task["id"]})
    section=st.segmented_control("工作区",["行动看板","核实与反馈","任务报告"],default="核实与反馈" if st.session_state.get("open_feedback") else "行动看板",key="collab_section")
    if section=="行动看板":
        with st.container():
            for col,label,statuses in zip(st.columns(3),["待核实与分派","正在处置","已完成与排除"],[{"待核实","待分派"},{"处理中"},{"已完成","已排除"}]):
                with col:
                    st.subheader(label)
                    group=[c for c in clues if c["status"] in statuses]
                    if not group:st.caption("暂无事项")
                    for clue in group:
                        with st.container(border=True,key=f"glass_board_clue_{clue['id']}"):
                            badge(clue["status"])
                            st.markdown(f"**{clue['title']}**")
                            st.caption(clue["assignee"] or "等待负责人核实与分派")
                            st.write(clue["notes"])
    if section=="核实与反馈":
        with st.container():
            if not clues:
                st.info("请先提交一条搜救线索。")
            else:
                if st.session_state.get('clue_selection') not in [c['id'] for c in clues]:
                    st.session_state.clue_selection=clues[0]['id']
                clue_id=st.selectbox("选择线索",[c["id"] for c in clues],index=None,format_func=lambda ident:next(c["title"]+" · "+ident[:6] for c in clues if c["id"]==ident),key='clue_selection',persist_state='session')
                if clue_id is None:
                    st.info('请选择要反馈的线索。')
                    return
                clue=next(c for c in clues if c["id"]==clue_id)
                with st.popover('手机提交反馈',icon=':material/devices:'):
                    st.code(share_link('collaboration',task['id'],clue_id),language=None)
                    st.caption('手机打开此链接即可反馈这条线索。')
                if clue["analysis_id"]:
                    st.image(media(clue['analysis_id'],'result'),caption="关联增强影像预览",width='stretch')
                elif clue.get('video_id'):
                    st.image(api('GET',f"/videos/{clue['video_id']}/frames/{clue['frame_index']}",binary=True),caption=f"关联视频关键帧 · {clue['video_time']:.1f}s",width=600)
                with st.form(f"update_{clue_id}"):
                    status=st.selectbox("处置状态",["待核实","待分派","处理中","已完成","已排除"],index=["待核实","待分派","处理中","已完成","已排除"].index(clue["status"]))
                    person=st.text_input("处置负责人",value=clue["assignee"])
                    feedback=st.text_area("本次反馈",placeholder="填写核实结果、行动进展或排除原因")
                    clicked=st.form_submit_button("保存处置更新",type="primary")
                    if clicked:
                        if status=="处理中" and not person.strip():
                            st.warning("请填写处置负责人。")
                        else:
                            api("PATCH",f"/clues/{clue_id}",json=dict(status=status,assignee=person,feedback=feedback))
                            st.rerun()
    if section=="任务报告":
        with st.container():
            data=api("GET",f"/report/{task['id']}")
            st.subheader(task["name"])
            st.caption(f"{task['area']} · 负责人：{task['owner']}")
            st.write(task["description"])
            markdown=f"# 海寻搜救任务报告\n\n任务：{task['name']}\n\n海域：{task['area']}\n\n负责人：{task['owner']}\n\n导出时间：{data['exported']}\n\n## 线索与处置\n"
            for clue in data["clues"]:
                markdown+=f"\n### {clue['title']}\n\n状态：{clue['status']}；负责人：{clue['assignee'] or '未分派'}\n\n{clue['notes']}\n"
            markdown+="\n## 操作记录\n"+"\n".join(f"- {e['created']} {e['message']}" for e in reversed(data["events"]))
            a,b=st.columns(2)
            a.download_button("导出任务报告",markdown,file_name="haixun_report.md",mime="text/markdown",width="stretch")
            b.download_button("导出完整记录",json.dumps(data,ensure_ascii=False,indent=2),file_name="haixun_report.json",mime="application/json",width="stretch")
            for item in data["events"]:
                st.caption(item["created"])
                st.write(item["message"])

def about():
    title("ABOUT / SeaSeek","发现线索，协同行动。","海寻 · 海面搜救协同平台")
    st.markdown("海寻连接现场影像、目标发现、线索核实与协同处置，为海面搜救提供清晰、连续的信息工作流。")
    a,b=st.columns(2)
    with a,st.container(border=True,key="glass_about_current"):
        st.subheader("影像感知")
        st.markdown("- 图片增强与原图对比\n- 船舶目标识别与标注\n- 短视频分析与关键帧查看\n- 关联影像与搜救线索")
    with b,st.container(border=True,key="glass_about_next"):
        st.subheader("协同响应")
        st.markdown("- 任务与线索集中管理\n- 线索位置与海域态势\n- 负责人、处置状态与反馈\n- 任务报告与记录导出")
    with st.expander("技术与数据说明"):
        st.write("当前提供传统图像增强与九类船舶检测，PAC-Net 海面适配仍在推进。模型输出属于预测结果，需结合原始影像人工核实；置信度不等于识别准确率。")
        st.write("线索位置由人工录入，示例任务使用预设数据。视频采用抽帧分析，不提供目标跟踪或唯一船舶计数。")
        st.caption("样例图片来自授权复用项目的训练划分；实拍样片保留来源说明，未用于模型训练或准确率评估。首页背景为创作场景。")
