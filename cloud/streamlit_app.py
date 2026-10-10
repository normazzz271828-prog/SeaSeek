"""Streamlit Community Cloud entry; reuse local UI without starting a database."""
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['SEASEEK_RUNTIME']='cloud'
runpy.run_path(str(ROOT/'streamlit_app.py'),run_name='__main__')
