import base64
import html
import io
import json
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st
from PIL import Image

from ui import ROOT, API, api, badge, task_picker, title
from runtime import CLOUD

METHODS={"自动增强":"adaptive","提亮暗部":"gamma_light","压低过亮区域":"gamma_dark","局部对比度":"clahe","温和去雾":"dehaze_mix","保留原图":"original"}

def overview():
    st.html('<section class="hero"><div class="eyebrow">SeaSeek · MARITIME SEARCH & RESCUE</div><h1>海寻<span>.</span></h1><p class="subtitle">融合 PAC-Net 特征增强的海面搜救协同平台</p><p class="tagline">以影像为线索，向希望靠近。</p><span class="tag">影像感知 / 线索态势 / 协同响应</span></section>')
    left,right=st.columns([3,1],vertical_alignment="center")
    with left:
        st.subheader("任务总览")
        st.caption("搜索、分析、行动。所有进展都留在任务里。")
    with right:
        if st.button("载入演示任务",icon=":material/play_arrow:",width="stretch"):
            st.session_state.active_task=api("POST","/demo")["id"]
            st.rerun()
    tasks=api("GET","/tasks")
    clues=[c for t in tasks for c in api("GET","/clues",params={"task_id":t["id"]})]
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
                    st.rerun()
    if not tasks:
        st.info("还没有搜救任务。创建第一个任务，或载入虚构演示任务体验完整流程。")
        return
    main,side=st.columns([1.7,1])
    with main:
        st.subheader("当前任务")
        for task in tasks:
            with st.container(border=True,key=f"glass_task_{task['id']}"):
                st.markdown(f"### {task['name']}")
                st.caption(f"{task['area']} · 负责人：{task['owner']} · {task['created']}")
                st.write(task["description"])
                if st.button("进入影像分析",key=f"task_{task['id']}",icon=":material/arrow_forward:"):
                    st.session_state.active_task=task["id"]
                    st.switch_page(st.Page(imaging,title="影像分析"))
    with side:
        st.subheader("最近动态")
        events=[]
        for task in tasks:
            events.extend(api("GET",f"/report/{task['id']}")["events"])
        for item in sorted(events,key=lambda e:(e["created"],e["id"]),reverse=True)[:7]:
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

def imaging():
    title("OBSERVE / ANALYZE","影像分析","把现场影像转化为可核实的搜救线索。")
    task=task_picker()
    image_tab,video_tab=st.tabs(["图片分析","视频演示"])
    with image_tab:
        controls,viewer=st.columns([1,2.4])
        with controls:
            with st.container(border=True,key="glass_analysis_controls"):
                st.subheader("分析设置")
                source=st.segmented_control("影像来源",["上传图片","示例图片"],default="示例图片")
                uploaded=None
                examples=sorted((ROOT/"assets/examples").glob("*.jpg"))
                if source=="上传图片":
                    uploaded=st.file_uploader("上传现场影像",type=["jpg","jpeg","png"],max_upload_size=12)
                elif examples:
                    sample=st.selectbox("海面示例",examples,format_func=lambda p:p.stem)
                    st.caption("来源：授权复用项目的训练图片；用于界面演示。")
                else:
                    st.info("暂无示例，请上传图片。")
                method=st.selectbox("增强方法",list(METHODS))
                detect_ships=st.checkbox("同时标注船舶",value=True)
                confidence=st.slider("模型置信度阈值",.05,.95,.25,.05)
                st.caption("九类船舶旋转框检测已接入，默认检测原图。增强方法仍为传统增强，PAC-Net 待适配。")
                if st.button("开始分析",type="primary",icon=":material/auto_fix_high:",width="stretch"):
                    raw=uploaded.getvalue() if uploaded else (sample.read_bytes() if source=="示例图片" and examples else None)
                    if raw is None:
                        st.warning("请先选择图片。")
                    else:
                        with st.status("正在分析现场影像…",expanded=True) as status:
                            st.write("读取图片并执行增强")
                            result=api("POST","/analyses",json=dict(task_id=task["id"],name=uploaded.name if uploaded else sample.name,image=base64.b64encode(raw).decode(),method=METHODS[method]))
                            st.session_state.analysis_id=result["id"]
                            if detect_ships:
                                st.write("执行船舶检测并绘制旋转框")
                                api("POST",f"/analyses/{result['id']}/detect",json=dict(confidence=confidence,source="original"))
                            status.update(label="分析完成，结果已保存",state="complete",expanded=False)
            history=api("GET","/analyses",params={"task_id":task["id"]})
            if history:
                ids=[a["id"] for a in history]
                selected=st.session_state.get("analysis_id")
                selected=st.selectbox("已保存的分析",ids,index=ids.index(selected) if selected in ids else 0,format_func=lambda ident:next(f"{a['name']} · {a['created']}" for a in history if a["id"]==ident))
                st.session_state.analysis_id=selected
        with viewer:
            if not history:
                with st.container(border=True,key="glass_analysis_empty"):
                    st.subheader("等待一张现场影像")
                    st.caption("选择示例或上传图片，开始分析后查看原图与增强结果。")
                    if source=="示例图片" and examples:
                        st.image(str(sample),width="stretch")
            else:
                result=api("GET",f"/analyses/{selected}")
                original=base64.b64decode(result["original"])
                enhanced=base64.b64decode(result["result"])
                detection=result.get('detection')
                st.caption(f"{result['name']} · {result['width']} × {result['height']} · 实际方法：{result['selected']}")
                options=["船舶标注","并排对比","原图","增强结果"] if detection else ["并排对比","原图","增强结果"]
                view=st.segmented_control("查看方式",options,default=options[0],key=f"image_view_{selected}_{bool(detection)}")
                if view=="并排对比":
                    a,b=st.columns(2)
                    a.image(original,caption="原图（已按处理尺寸缩放）",width="stretch")
                    b.image(enhanced,caption="增强结果",width="stretch")
                elif view=="船舶标注":
                    st.image(base64.b64decode(detection['image']),caption="旋转框 + 类别 + 模型置信度（待人工核实）",width="stretch")
                else:
                    st.image(original if view=="原图" else enhanced,width="stretch")
                canvas=Image.new("RGB",(result["width"]*2,result["height"]))
                canvas.paste(Image.open(io.BytesIO(original)),(0,0))
                canvas.paste(Image.open(io.BytesIO(enhanced)),(result["width"],0))
                out=io.BytesIO();canvas.save(out,format="PNG")
                a,b=st.columns(2)
                a.download_button("下载增强图片",enhanced,file_name="haixun_enhanced.png",mime="image/png",width="stretch")
                b.download_button("下载对比图片",out.getvalue(),file_name="haixun_comparison.png",mime="image/png",width="stretch")
                if detection:
                    st.subheader(f"检测目标 · {len(detection['predictions'])}")
                    st.caption(f"检测输入：{'原图' if detection['source']=='original' else '增强图'} · 阈值 {detection['confidence']:.0%}。结果为模型预测，不是数据集真值或识别准确率。")
                    if detection['predictions']:
                        st.dataframe(pd.DataFrame([dict(目标=f"{i+1:02d}",类别=p['category'],模型置信度=f"{p['score']:.1%}") for i,p in enumerate(detection['predictions'])]),hide_index=True)
                    else:
                        st.info("当前阈值下没有检测到船舶，可降低阈值重试；不代表影像中一定没有船。")
                    a,b=st.columns(2)
                    a.download_button("下载船舶标注图",base64.b64decode(detection['image']),file_name="haixun_ships.png",mime="image/png",width="stretch")
                    b.download_button("下载检测坐标",json.dumps({k:v for k,v in detection.items() if k!='image'},ensure_ascii=False,indent=2),file_name="haixun_ships.json",mime="application/json",width="stretch")
                if st.button("按当前阈值重新检测",icon=":material/refresh:"):
                    with st.spinner("正在检测船舶…"):
                        api("POST",f"/analyses/{selected}/detect",json=dict(confidence=confidence,source="original"))
                    st.rerun()
                with st.expander("将这张影像提交为搜救线索",icon=":material/add_location_alt:"):
                    target=None
                    if detection and detection['predictions']:
                        target_index=st.selectbox('关联检测目标',list(range(len(detection['predictions']))),format_func=lambda i:f"{i+1:02d} · {detection['predictions'][i]['category']}")
                        target=detection['predictions'][target_index]
                    clue_form(task,selected,f"image_clue_{selected}_{target_index if target else 'manual'}",target=target)
    with video_tab:
        video_panel(task)

def video_panel(task):
    st.subheader("短视频船舶检测")
    st.caption("上传真实短片，或用训练图片组成的演示片体验流程。最高 1080p、30 秒、12 MB；抽帧结果无音频，不做目标跟踪或唯一船舶计数。")
    a,b=st.columns([1,2])
    with a:
        uploaded=st.file_uploader("上传 MP4",type=['mp4'],max_upload_size=12,key='video_upload')
        demo=ROOT/'assets/demo_ships.mp4'
        use_demo=st.checkbox("使用训练图片合成演示片",value=uploaded is None,disabled=not demo.exists())
        rate=st.select_slider("每秒检测帧数",[.5,1.,2.],value=1.)
        conf=st.slider("视频模型置信度阈值",.05,.95,.25,.05,key='video_conf')
        if st.button("提交后台检测",type='primary',icon=':material/play_arrow:'):
            content=demo.read_bytes() if use_demo and demo.exists() else (uploaded.getvalue() if uploaded else None)
            if content:
                item=api('POST','/videos',params=dict(task_id=task['id'],name='训练图片合成演示片.mp4' if use_demo else uploaded.name,confidence=conf,sample_fps=rate),data=content,headers={'Content-Type':'video/mp4'})
                st.session_state.video_id=item['id']
                st.rerun()
            else:st.warning('请选择视频。')
    with b:
        if uploaded and not use_demo:st.video(uploaded.getvalue())
        elif demo.exists():
            st.video(str(demo))
            st.caption('以上为训练集静态图片合成，非真实航拍视频。检测仍由模型实际执行。')
    items=api('GET','/videos',params={'task_id':task['id']})
    if items:
        ids=[v['id'] for v in items]
        current=st.session_state.get('video_id')
        ident=st.selectbox('视频任务记录',ids,index=ids.index(current) if current in ids else 0,format_func=lambda ident:next(v['name']+' · '+v['created'] for v in items if v['id']==ident))
        item=next(v for v in items if v['id']==ident)
        if item['status'] in ('queued','running'):
            video_result(ident,task)
        else:
            show_video_status(ident,task,api('GET',f'/videos/{ident}'))

@st.fragment(run_every='3s')
def video_result(ident,task):
    result=api('GET',f'/videos/{ident}')
    status=result['status']
    if status in ('queued','running'):
        st.progress(result['progress'],text='等待队列' if status=='queued' else '正在抽帧并标注船舶')
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
    video=api('GET',f'/videos/{ident}/media/result',binary=True)
    st.video(video)
    records=data['frames']
    st.dataframe(pd.DataFrame([dict(时间秒=r['time'],该帧目标数=len(r['predictions']),类别='、'.join(sorted({p['category'] for p in r['predictions']}))) for r in records]),hide_index=True)
    index=st.select_slider('关键帧时间点',options=list(range(len(records))),format_func=lambda i:f"{records[i]['time']:.1f}s",key=f'frame_{ident}')
    st.image(api('GET',f'/videos/{ident}/frames/{index}',binary=True),caption=f"{records[index]['time']:.1f}s · {len(records[index]['predictions'])} 个预测目标",width='stretch')
    st.download_button('下载标注视频',video,file_name='seaseek_video.mp4',mime='video/mp4',key=f'video_media_download_{ident}')
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
            st.caption("位置来自人工录入；演示任务的位置为虚构。底图需要网络连接。")
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

def collaboration():
    title("COORDINATE / RESPOND","协同处置","核实线索、分派行动，保存每一次现场反馈。")
    task=task_picker()
    clues=api("GET","/clues",params={"task_id":task["id"]})
    board,details,report=st.tabs(["行动看板","核实与反馈","任务报告"])
    with board:
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
    with details:
        if not clues:
            st.info("请先提交一条搜救线索。")
        else:
            clue_id=st.selectbox("选择线索",[c["id"] for c in clues],format_func=lambda ident:next(c["title"] for c in clues if c["id"]==ident))
            clue=next(c for c in clues if c["id"]==clue_id)
            if clue["analysis_id"]:
                linked=api("GET",f"/analyses/{clue['analysis_id']}")
                st.image(base64.b64decode(linked["result"]),caption="关联增强影像",width=600)
            elif clue.get('video_id'):
                st.image(api('GET',f"/videos/{clue['video_id']}/frames/{clue['frame_index']}",binary=True),caption=f"关联视频关键帧 · {clue['video_time']:.1f}s",width=600)
            with st.form(f"update_{clue_id}"):
                status=st.selectbox("处置状态",["待核实","待分派","处理中","已完成","已排除"],index=["待核实","待分派","处理中","已完成","已排除"].index(clue["status"]))
                person=st.text_input("处置负责人",value=clue["assignee"])
                feedback=st.text_area("本次反馈",placeholder="填写核实结果、行动进展或排除原因")
                if st.form_submit_button("保存处置更新",type="primary"):
                    if status=="处理中" and not person.strip():
                        st.warning("请填写处置负责人。")
                    else:
                        api("PATCH",f"/clues/{clue_id}",json=dict(status=status,assignee=person,feedback=feedback))
                        st.rerun()
    with report:
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
    title("ABOUT / SeaSeek","发现线索，协同行动。","海面搜救协同平台 · "+("云端准备版" if CLOUD else "本地端 v0.3.1"))
    st.markdown("海寻围绕 **任务 → 影像分析 → 人工核实 → 协同处置 → 报告归档** 建立搜救业务闭环。")
    a,b=st.columns(2)
    with a:
        with st.container(border=True,key="glass_about_current"):
            st.subheader("已实现")
            st.markdown("- Streamlit 界面与独立 FastAPI 通信\n- SQLite 持久保存任务、影像、线索与操作记录\n- 真实传统增强、去雾和图片下载\n- 人工线索定位、分派、反馈与报告导出\n- 海洋视觉、轻量动画与减少动态效果支持")
            st.markdown("- 九类船舶旋转框检测、中文标注与坐标导出\n- 短视频后台抽帧检测、关键帧与视频线索")
    with b:
        with st.container(border=True,key="glass_about_next"):
            st.subheader("待接入")
            st.markdown("- PAC-Net 海面适配与对照验证\n- 落水人员等搜救目标与视频跟踪\n- 统一登录、角色权限与任务成员隔离\n- 云端、正式网页与微信小程序")
    st.info("当前为演示界面，尚未接入个人账号和角色权限。负责人姓名是业务记录字段。" if CLOUD else "当前仅监听本机地址，属于本地演示模式。姓名是业务记录字段，不是登录认证。")
    st.subheader("四端约定")
    st.markdown("本地端 → Streamlit 云端验证 → 独立域名网页端 / 微信小程序端。四端使用统一业务规则与后端数据源，界面按场景适配。")
    st.subheader("算法来源")
    st.caption("传统增强与去雾复用自 D:/Projects/海面目标检测与识别/accuracy_lab/followup；仅适配模块导入。它们不等同于 PAC-Net。样例从该项目训练划分选取。")
    summary=json.loads((ROOT/'assets/dataset_summary.json').read_text(encoding='utf-8'))
    st.caption(f"源项目训练划分：{summary['training_images']:,} 张图片、{summary['training_objects']:,} 个标注目标。本版复用冻结模型和 {summary['example_images']} 张训练示例，不重新训练；训练样例表现不代表泛化准确率。模型权重与来源校验记录见 models/provenance.json。")
