#!/usr/bin/env bash
# Run as root after uploading reviewed source to /opt/seaseek and checking
# the model hash. Argument: an existing standalone Python 3.12 installation.
set -euo pipefail
python_source=${1:?Specify a standalone Python 3.12 directory}
test "$(id -u)" = 0
test -f /opt/seaseek/backend.py
test -f /opt/seaseek/models/ship_obb.pt
test -x "$python_source/bin/python3.12"
if ! id seaseek >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/seaseek --shell /sbin/nologin seaseek
fi
install -d -m 750 -o seaseek -g seaseek /var/lib/seaseek /opt/seaseek/.tmp
install -d -m 700 /etc/seaseek
if test ! -d /opt/seaseek/python; then
    cp -a "$python_source" /opt/seaseek/python
fi
if test ! -x /opt/seaseek/.venv/bin/python; then
    /opt/seaseek/python/bin/python3.12 -m venv /opt/seaseek/.venv
fi
if test ! -f /etc/seaseek/api.env; then
    /opt/seaseek/.venv/bin/python - <<'PY'
from pathlib import Path
import os,secrets
p=Path('/etc/seaseek/api.env')
with p.open('x') as f:
    f.write('SEASEEK_API_MODE=remote\nHAIXUN_DATA_DIR=/var/lib/seaseek\nHAIXUN_API_TOKEN='+secrets.token_urlsafe(48)+'\n')
os.chmod(p,0o600)
PY
fi
if test -d /opt/seaseek/.tmp/wheelhouse; then
    /opt/seaseek/.venv/bin/python -m pip install --no-cache-dir --no-index --find-links /opt/seaseek/.tmp/wheelhouse --find-links /opt/seaseek/.tmp/wheels torch==2.11.0+cpu torchvision==0.26.0+cpu -r /opt/seaseek/deploy/backend-requirements.txt
elif test -d /opt/seaseek/.tmp/wheels; then
    /opt/seaseek/.venv/bin/python -m pip install --no-cache-dir /opt/seaseek/.tmp/wheels/*.whl --index-url https://mirrors.aliyun.com/pypi/simple
    /opt/seaseek/.venv/bin/python -m pip install --no-cache-dir -r /opt/seaseek/deploy/backend-requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple
else
    /opt/seaseek/.venv/bin/python -m pip install --no-cache-dir torch==2.11.0+cpu torchvision==0.26.0+cpu --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://mirrors.aliyun.com/pypi/simple
    /opt/seaseek/.venv/bin/python -m pip install --no-cache-dir -r /opt/seaseek/deploy/backend-requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple
fi
/opt/seaseek/.venv/bin/python -m pip check
# Root's restrictive umask must not prevent the service user reading packages.
chgrp -R seaseek /opt/seaseek
chmod -R g+rX /opt/seaseek
/opt/seaseek/.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
root=Path('/opt/seaseek/models')
expected=json.loads((root/'provenance.json').read_text())['sha256']
assert hashlib.sha256((root/'ship_obb.pt').read_bytes()).hexdigest()==expected,'Model hash mismatch'
print('Model provenance verified')
PY
install -m 644 /opt/seaseek/deploy/seaseek-api.service /etc/systemd/system/seaseek-api.service
systemctl daemon-reload
systemctl enable --now seaseek-api.service
systemctl is-active seaseek-api.service
