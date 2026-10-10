"""Run against the local API after start_local.ps1."""
from streamlit.testing.v1 import AppTest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

for view in ('overview','imaging','situation','collaboration','about'):
    app=AppTest.from_string(f'from app_pages.views import {view}\n{view}()',default_timeout=30).run()
    assert not app.exception, [(e.message) for e in app.exception]
    print(view, 'OK')
