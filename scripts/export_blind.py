"""Export participant inputs and schemas for one benchmark task."""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export(output, task='t4'):
    if task not in {'t1', 't2', 't3', 't4'}:
        raise ValueError('Unknown task: ' + task)
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Export outside the benchmark checkout')
    if output.exists():
        raise ValueError('Choose a new output directory')
    output.mkdir(parents=True)
    source_manifest = json.loads((ROOT / f'tracks/{task}/manifest.json').read_text())
    manifest = {'task': task, 'case_count': source_manifest['case_count'], 'cases': []}
    if task in {'t1', 't4'}:
        for row in source_manifest['cases']:
            rel = Path('cases') / row['case_id'] / 'request.json'
            request = json.loads((ROOT / rel).read_text())
            if task == 't1':
                request.pop('analysis_profile', None)
                request.pop('options', None)
            path = output / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
            manifest['cases'].append({'case_id': row['case_id'], 'request': str(rel), 'documents': row['documents']})
    else:
        # Each task export uses its declared JSON input files.
        for row in source_manifest['cases']:
            case_rel = Path(f'tracks/{task}/cases') / row['case_id']
            source = ROOT / case_rel
            paths = ([source / name for name in ('task.json', 'protocol.json', 'documents.json', 'submission_template.json')]
                     if task == 't2' else [*sorted((source / 'inputs').glob('*.json')),
                                           source / 'tasks/analysis_main_outcomes.json', source / 'submission_template.json'])
            for path in paths:
                dest = output / path.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
            manifest['cases'].append({'case_id': row['case_id'], 'task': f'tracks/{task}/' + row['task']})
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path in sorted((ROOT / 'schemas').glob('*.json')):
        if 'gold' in path.name.lower():
            continue
        dest = output / 'schemas' / path.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, dest)
    for name in ['TASK.md', 'OUTPUT_CONTRACT.md', 'DATA_FORMAT.md']:
        shutil.copyfile(ROOT / name, output / name)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', choices=['t1', 't2', 't3', 't4'], default='t4')
    args = parser.parse_args()
    print(export(args.output, args.task))
