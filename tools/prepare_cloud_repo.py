"""Copy only reviewed deployment files into an existing SeaSeek checkout."""
import argparse
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FILES=['streamlit_app.py','ui.py','runtime.py','backend.py','requirements.txt','README.md','AGENTS.md','CHANGELOG.md','.gitignore','.gitattributes','start_local.ps1','models/provenance.json','.streamlit/config.toml']
FOLDERS=['app_pages','algorithms','assets','static','cloud','deploy','tests','tools']
PREVIEW=['index.html','style.css','liquid.css','preview.js','README.md','assets/rescue-background.png','assets/background-generation.md']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('checkout',type=Path)
    target=parser.parse_args().checkout.resolve()
    if target==ROOT or not (target/'.git').is_dir():
        raise SystemExit('Use a separate existing Git checkout.')
    paths=[ROOT/name for name in FILES]+[ROOT/'preview'/name for name in PREVIEW]
    for folder in FOLDERS:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pt','.env'))
    for source in paths:
        relative=source.relative_to(ROOT)
        destination=target/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix in ('.png','.jpg','.mp4'):
            shutil.copy2(source,destination)
        else:
            destination.write_bytes((source.read_text(encoding='utf-8').rstrip()+'\n').encode('utf-8'))
    # Runtime binding belongs to the local launcher; Cloud chooses its own socket.
    config=target/'.streamlit/config.toml'
    config.write_bytes(('\n'.join(line for line in config.read_text(encoding='utf-8').splitlines() if not line.startswith(('address =','port =')))+'\n').encode('utf-8'))
    print(f'Prepared {len(paths)} reviewed files in {target}')

if __name__=='__main__':
    main()
