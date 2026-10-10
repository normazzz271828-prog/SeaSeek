"""Render the accepted landing composition inside the Streamlit router."""
import re
from urllib.parse import quote
import streamlit as st
from ui import ROOT


def home():
    document=(ROOT/'preview/index.html').read_text(encoding='utf-8')
    content=document.split('<main class="shell">',1)[1].split('</main>',1)[0]
    content=re.sub(r'<a href="http://127.0.0.1:8505/about"[^>]*>.*?</a>','',content)
    content=content.replace('http://127.0.0.1:8505"','/overview"').replace('http://127.0.0.1:8505/','/')
    content=content.replace(' target="_blank" rel="noopener"','').replace('hero','landing-hero')
    content=content.replace('首页视觉预览 · 背景为 AI 创作场景 · 算法接入状态以工作台为准','背景为 AI 创作场景 · 算法接入状态以工作台为准')
    def icon_image(match):
        svg=match.group(0).replace('<svg ','<svg xmlns="http://www.w3.org/2000/svg" fill="none" stroke="#a0ddd9" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" ',1)
        return '<img class="landing-icon" alt="" aria-hidden="true" src="data:image/svg+xml,'+quote(svg,safe='')+'">'
    content=re.sub(r'<svg\b.*?</svg>',icon_image,content,flags=re.S)
    css='\n'.join((ROOT/'preview'/name).read_text(encoding='utf-8') for name in ('style.css','liquid.css'))
    css=css.replace('hero','landing-hero')
    st.html('<style>@scope (.sea-landing) {'+css+'}</style>')
    st.html('<div class="sea-landing"><main class="shell">'+content+'</main></div>')
