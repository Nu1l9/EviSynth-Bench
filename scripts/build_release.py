"""Build a reproducible source archive and SHA-256 file manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_repository import findings
from scripts.validate_release import check

DIRECTORIES={'.github','cases','tracks','references','evaluation','schemas','scripts','tests'}
ROOT_FILES={'.gitignore','.gitattributes','README.md','TASK.md','DATA_FORMAT.md','OUTPUT_CONTRACT.md',
            'LICENSE','LICENSE-DATA','.env.example','manifest.json','VALIDATION.json','evaluate.py','evaluate_t2.py','evaluate_t3.py'}
EXTENSIONS={'.py','.json','.md','.yml','.yaml'}


def source_files():
    paths=[]
    for name in sorted(ROOT_FILES):
        path=ROOT/name
        if not path.is_file():raise ValueError('Missing required release file: '+name)
        paths.append(path)
    for directory in sorted(DIRECTORIES):
        for path in sorted((ROOT/directory).rglob('*')):
            rel=path.relative_to(ROOT)
            if path.is_symlink():raise ValueError('Symlink in source tree: '+str(rel))
            if '__pycache__' in rel.parts or path.name=='.DS_Store':continue
            if path.is_file():
                if path.suffix not in EXTENSIONS and path.name not in {'requirements.txt','.env.example'}:
                    raise ValueError('Unexpected source-tree file: '+str(rel))
                paths.append(path)
    return sorted(paths)


def build(output):
    output=Path(output).resolve()
    if output.suffix!='.zip':raise ValueError('Output must end with .zip')
    validation=check()
    if validation['issues']:raise ValueError(validation['issues'])
    files=source_files()
    issues=findings(files)
    if issues:raise ValueError(issues)
    manifest={'algorithm':'sha256','files':[
        {'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,
         'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    inventory=ROOT/'FILE_MANIFEST.json'
    inventory.write_text(json.dumps(manifest,indent=2)+'\n')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in [*files,inventory]:
            name='EviSynth-Bench/'+str(path.relative_to(ROOT))
            info=zipfile.ZipInfo(name,date_time=(2026,11,13,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            archive.writestr(info,path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise ValueError('Archive CRC check failed')
        for item in manifest['files']:
            data=archive.read('EviSynth-Bench/'+item['path'])
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Checksum mismatch: '+item['path'])
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n')
    return {'archive':str(output),'source_files':len(files)+1,'bytes':output.stat().st_size,'sha256':digest}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(build(args.output),indent=2))
