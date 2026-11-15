"""Evaluate T1 screening and T4 end-to-end case submissions."""
import argparse
import json
from pathlib import Path
from evaluation.scoring import compare_case, gold_selection
from evaluation.numeric import gold_rows
from evaluation.metrics import prf, aggregate_prf
from evaluation.analysis_metrics import score_pooled, summarize_pooled
ROOT = Path(__file__).resolve().parent


def evaluate(registry, gold_root=ROOT / 'evaluation/gold'):
    gold_root = Path(gold_root); rows = []; seen = set()
    version = json.loads((ROOT / 'manifest.json').read_text())['release_version']
    roster = [r['case_id'] for r in json.loads((ROOT / 'tracks/t4/manifest.json').read_text())['cases']]
    for entry in registry['runs']:
        cid = entry['case_id']; system = entry.get('system', 'unspecified'); run = Path(entry['run']).expanduser().resolve()
        if cid not in roster: raise ValueError('Unknown case: ' + cid)
        if (system, cid) in seen: raise ValueError('Duplicate system/case entry')
        seen.add((system, cid)); folder = gold_root / cid
        manifest_path = run / 'pipeline_manifest.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        required = {'screening': '01_screening/effective_screening_results.json',
                    'extraction': '02_extraction/case_extraction_submission.json',
                    'analysis_selection': '05_analysis/analysis_result.json'}
        present = {key: (run / path).is_file() for key, path in required.items()}
        if not (run / 'request.normalized.json').is_file():
            rows.append({'case_id': cid, 'system': system, 'status': 'missing_input_identity', 'metrics': None}); continue
        extraction = json.loads((folder / 'extraction.json').read_text()); analysis = json.loads((folder / 'analysis.json').read_text())
        result = compare_case(cid, run, manifest, version, gold_root, extraction, analysis)
        result.pop('version', None); result.pop('run', None)
        for key, available in present.items():
            if not available: result[key] = None
        result['stage_outputs_present'] = present; result['system'] = system; rows.append(result)
    summaries = {}
    for system in sorted({r['system'] for r in rows}):
        selected = {r['case_id']: r for r in rows if r['system'] == system}
        screening = []; extraction = []; selection = []; comparative = []; noncomparative = []
        negatives = tn = 0
        for cid in roster:
            folder = gold_root / cid; row = selected.get(cid, {})
            sg = json.loads((folder / 'screening.json').read_text()); eg = json.loads((folder / 'extraction.json').read_text()); ag = json.loads((folder / 'analysis.json').read_text())
            sc = row.get('screening') or prf(0, 0, sg['positive_count'])
            ex = row.get('extraction') or prf(0, 0, len(gold_rows(eg)))
            sel = row.get('analysis_selection') or prf(0, 0, sum(map(len, gold_selection(ag, eg).values())))
            screening.append(sc); extraction.append(ex); selection.append(sel)
            negatives += sg['negative_count']; tn += sc.get('tn', 0)
            pooled = row.get('pooled') or score_pooled([], ag, cid)
            comparative.extend(pooled['comparative']['results']); noncomparative.extend(pooled['noncomparative']['results'])
        screen_summary = aggregate_prf(screening); screen_summary.update(positive_total=sum(x['expected'] for x in screening), negative_total=negatives, true_negatives=tn)
        summaries[system] = {'cohort_cases': len(roster), 'submitted_cases': len(selected), 'missing_case_ids': sorted(set(roster) - set(selected)),
            'screening': screen_summary, 'extraction': aggregate_prf(extraction), 'analysis_selection': aggregate_prf(selection),
            'pooled': summarize_pooled(comparative, noncomparative)}
    result = {'benchmark_version': version, 'tasks': ['t1', 't4'], 'cases': rows, 'summaries': summaries}
    if len(summaries) == 1: result['summary'] = next(iter(summaries.values()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True); parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    registry = json.loads(args.runs.read_text())
    for row in registry['runs']:
        path = Path(row['run']); row['run'] = str(path if path.is_absolute() else args.runs.parent / path)
    result = evaluate(registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('Evaluation written to', args.output)


if __name__ == '__main__': main()
