"""Shared endpoint settings; cloud never falls back to a separate local store."""
import os
import streamlit as st


def setting(name,default=""):
    if name in os.environ:
        return os.environ[name]
    try:
        return str(st.secrets.get(name,default))
    except st.errors.StreamlitSecretNotFoundError:
        return default


CLOUD=os.environ.get('SEASEEK_RUNTIME')=='cloud'
API=setting('HAIXUN_API_URL','' if CLOUD else 'http://127.0.0.1:8765').rstrip('/')
API_TOKEN=setting('HAIXUN_API_TOKEN')
