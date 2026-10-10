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


# A public/default listener is a hosted frontend, even if deployed with the
# root entrypoint. Only an explicit local mode or loopback binding gets a
# localhost API fallback. The cloud wrapper always chooses cloud explicitly.
mode=os.environ.get('SEASEEK_RUNTIME')
CLOUD=mode=='cloud' if mode else st.get_option('server.address') not in ('127.0.0.1','localhost','::1')

def connection_settings():
    # Secrets can change while imported modules remain cached across reruns.
    # Read the current values for every request; never cache service tokens.
    return (
        setting('HAIXUN_API_URL','' if CLOUD else 'http://127.0.0.1:8765').rstrip('/'),
        setting('HAIXUN_API_TOKEN'),
    )

# Startup snapshot retained for runtime diagnostics. Requests use the getter.
API,API_TOKEN=connection_settings()
