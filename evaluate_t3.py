"""Score standalone T3 submissions and the complete 22-case cohort."""
import argparse
import json
from pathlib import Path
from evaluation.analysis_metrics import _score_analysis, score_extensions, summarize_pooled, summarize_extensions
from evaluation.metrics import aggregate_prf
from evaluation.submissions import load_batch
ROOT = Path(__file__).resolve().parent


def evaluate(submission, root=ROOT):
    cid = submission.get('case_id')
    roster = json.loads((root / 'tracks/t3/manifest.json').read_text())['cases']
    if cid not in {r['case_id'] for r in roster}: raise ValueError('Unknown T3 case: ' + str(cid))
    if submission.get('task_type') != 'analysis': raise ValueError('Expected task_type="analysis"')
    predictions = submission.get('predictions')
    folder = root / 'evaluation/t3_gold' / cid
    gold = json.loads((folder / 'analysis.json').read_text())
    mapping = json.loads((folder / 'candidate_id_map.json').read_text())['runtime_to_canonical_candidate_id']
    metrics = _score_analysis(predictions, gold, runtime_to_canonical=mapping)
    metrics['extensions'] = score_extensions(predictions, root / 'tracks/t3/cases' / cid, cid)
    version = json.loads((root / 'manifest.json').read_text())['release_version']
    return {'benchmark_version': version, 'case_id': cid, 'task': 't3', 'metrics': metrics}


def evaluate_batch(submissions, root=ROOT):
    roster = [r['case_id'] for r in json.loads((root / 'tracks/t3/manifest.json').read_text())['cases']]
    if set(submissions) - set(roster): raise ValueError('Unknown T3 case IDs')
    rows = []
    for cid in roster:
        submission = submissions.get(cid, {'case_id': cid, 'task_type': 'analysis', 'predictions': []})
        if submission.get('case_id') != cid: raise ValueError('Batch case_id mismatch')
        row = evaluate(submission, root); row['submission_status'] = 'submitted' if cid in submissions else 'missing'; rows.append(row)
    metrics = [r['metrics'] for r in rows]
    pooled = summarize_pooled([x for m in metrics for x in m['pooled']['comparative']['results']],
                              [x for m in metrics for x in m['pooled']['noncomparative']['results']])
    version = json.loads((root / 'manifest.json').read_text())['release_version']
    return {'benchmark_version': version, 'task': 't3', 'cases': rows, 'summary': {
        'cases': len(rows), 'submitted_cases': len(submissions),
        'selection': aggregate_prf([m['selection'] for m in metrics]), 'pooled': pooled,
        'extensions': summarize_extensions([x for m in metrics for x in m['extensions']['results']])}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--submission', type=Path); source.add_argument('--submissions', type=Path)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    result = evaluate(json.loads(args.submission.read_text())) if args.submission else evaluate_batch(load_batch(args.submissions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('T3 evaluation written to', args.output)


if __name__ == '__main__': main()
