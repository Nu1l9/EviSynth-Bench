"""Check tracked (or candidate source) files without printing secret values."""
import argparse
import json
import re
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN={'data','runs','outputs','audit','benchmark_runs','benchmark_packages','documents','submissions','results','expert_qa_sessions','expert_qa_library','.venv','__pycache__'}
SECRETS=[re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}'),re.compile(r'\bgh[pousr]_[A-Za-z0-9]{24,}'),re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
def findings(paths):
 errors=[]
 for path in paths:
  rel=path.relative_to(ROOT);name=path.name
  if path.is_symlink():errors.append((str(rel),'symlink'));continue
  if not path.is_file():continue
  if path.suffix.lower() in {'.pdf','.png','.jpg','.jpeg','.tif','.tiff','.docx','.xlsx','.zip','.gz','.parquet'} or name in {'full.md','content_list.json','layout.json'}:
   errors.append((str(rel),'excluded document or binary'))
  if any(part in FORBIDDEN for part in rel.parts) or (name.startswith('.env') and name!='.env.example') or name.endswith('.env') or str(rel)=='config/provider.json':
   errors.append((str(rel),'private/runtime file'))
  if path.stat().st_size>10_000_000:errors.append((str(rel),'large source file'))
  try:text=path.read_text()
  except UnicodeError:errors.append((str(rel),'unexpected binary'));continue
  if any(p.search(text) for p in SECRETS):errors.append((str(rel),'possible credential'))
  if rel.as_posix() != 'scripts/check_repository.py' and re.search(r'/Users/[^/\s]+/|[A-Za-z]:\\Users\\[^\\\s]+\\',text):errors.append((str(rel),'workstation path'))
 return errors
def main():
 p=argparse.ArgumentParser();p.add_argument('--tracked',action='store_true');a=p.parse_args()
 if a.tracked:
  names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
  paths=[ROOT/n for n in names if n]
 elif (ROOT/'.git').exists():
  # Respect Git ignore rules, including locally installed research resources.
  names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
  paths=sorted({ROOT/n for n in names if n})
 else:
  # Release archives omit Git metadata; ignore local runtime directories.
  ignored_dirs={'.git','__pycache__'}
  ignore_file=ROOT/'.gitignore'
  if ignore_file.is_file():
   ignored_dirs.update(line.strip().rstrip('/') for line in ignore_file.read_text().splitlines()
                       if line.strip().endswith('/') and not line.lstrip().startswith(('#','!')))
  paths=sorted(path for path in ROOT.rglob('*') if path.is_file()
               and path.name!='.DS_Store' and path.suffix!='.pyc'
               and not any(part in ignored_dirs for part in path.relative_to(ROOT).parts))
 issues=findings(paths)
 print(json.dumps({'files_checked':len(paths),'issues':[{'path':p,'reason':r} for p,r in issues]},indent=2))
 return bool(issues)
if __name__=='__main__':raise SystemExit(main())
