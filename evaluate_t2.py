"""Evaluate T2 reference recovery and the comprehensive extraction net score."""
import argparse
import json
import os
from pathlib import Path
from evaluation.extraction_metrics import score_extraction, validate_predictions
from evaluation.metrics import aggregate_prf
from evaluation.submissions import load_batch
ROOT = Path(__file__).resolve().parent


def evaluate(submission, judgments=None, root=ROOT):
    cid = submission.get('case_id')
    cases = {r['case_id'] for r in json.loads((root / 'tracks/t2/manifest.json').read_text())['cases']}
    if cid not in cases: raise ValueError('Unknown T2 case: ' + str(cid))
    if isinstance(judgments, dict) and judgments.get('case_id', cid) != cid: raise ValueError('Adjudication case_id mismatch')
    gold = json.loads((root / 'evaluation/gold' / cid / 'extraction.json').read_text())
    return {'case_id': cid, 'task': 't2', 'metrics': score_extraction(submission, gold, judgments)}


def evaluate_batch(submissions, judgments=None, root=ROOT):
    roster = [r['case_id'] for r in json.loads((root / 'tracks/t2/manifest.json').read_text())['cases']]
    if set(submissions) - set(roster): raise ValueError('Unknown T2 case IDs')
    judgments = judgments or {}; rows = []
    for cid in roster:
        submission = submissions.get(cid, {'case_id': cid, 'task_type': 'extraction', 'predictions': []})
        if submission.get('case_id') != cid: raise ValueError('Batch case_id mismatch')
        row = evaluate(submission, judgments.get(cid), root); row['submission_status'] = 'submitted' if cid in submissions else 'missing'; rows.append(row)
    complete = len(submissions) == len(roster) and all(r['metrics']['net_score'] is not None for r in rows)
    available = [r['metrics']['net_score'] for r in rows if r['submission_status'] == 'submitted' and r['metrics']['net_score'] is not None]
    version = json.loads((root / 'manifest.json').read_text())['release_version']
    return {'benchmark_version': version, 'task': 't2', 'cases': rows, 'summary': {
        'cohort_cases': len(roster), 'submitted_cases': len(submissions),
        'reference': aggregate_prf([r['metrics']['reference'] for r in rows]),
        'net_score_total': sum(available) if complete else None, 'net_score_observed': sum(available),
        'net_score_cases': len(available), 'scoring_status': 'complete' if complete else 'incomplete'}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--submission', type=Path); source.add_argument('--submissions', type=Path)
    parser.add_argument('--case'); parser.add_argument('--adjudications', type=Path)
    parser.add_argument('--model', help='OpenAI judge model ID for semantic adjudication')
    parser.add_argument('--validate-only', action='store_true'); parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.submission:
        submission = json.loads(args.submission.read_text()); submissions = {submission['case_id']: submission}
        if args.case and args.case != submission['case_id']: parser.error('--case differs from submission case_id')
    else:
        if args.case: parser.error('--case applies to a single submission')
        submissions = load_batch(args.submissions)
    judgments = {}
    if args.adjudications:
        raw = json.loads(args.adjudications.read_text())
        entries = raw.get('cases', [raw])
        judgments = {r['case_id']: r for r in entries}
        if len(judgments) != len(entries): raise ValueError('Duplicate adjudication case_id')
    if args.validate_only:
        for cid, submission in submissions.items(): evaluate(submission, judgments.get(cid))
        print(json.dumps({'valid': True, 'cases': len(submissions), 'scored': False})); return 0
    if not args.output: parser.error('--output is required for scoring')
    from evaluation.openai_judge import load_environment, adjudicate
    load_environment(ROOT / '.env'); model = args.model or os.getenv('PORTABLE_EVALUATOR_MODEL')
    if model:
        for cid, submission in submissions.items():
            if cid not in judgments:
                gold = json.loads((ROOT / 'evaluation/gold' / cid / 'extraction.json').read_text())
                protocol = {'protocol': json.loads((ROOT / 'tracks/t2/cases' / cid / 'protocol.json').read_text()),
                            'task': json.loads((ROOT / 'evaluation/t2_contexts' / (cid + '.json')).read_text())['task']}
                judgments[cid] = adjudicate(submission, gold, protocol, model)
    result = evaluate(submission, judgments.get(submission['case_id'])) if args.submission else evaluate_batch(submissions, judgments)
    if judgments: result['adjudications'] = list(judgments.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('T2 evaluation written to', args.output)
    complete = result['metrics']['net_score'] is not None if args.submission else result['summary']['scoring_status'] == 'complete'
    return 0 if complete else 2


if __name__ == '__main__': raise SystemExit(main())
