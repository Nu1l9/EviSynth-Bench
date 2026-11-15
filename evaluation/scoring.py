"""T1 screening, T2 extraction and T4 evidence-selection metrics."""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
from evaluation.numeric import gold_rows, numeric_signature, resolve_article, same_numbers
from evaluation.metrics import prf
from evaluation.analysis_metrics import analysis_id, score_pooled

def read(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid result file: ' + str(path)) from exc


def source_map(run, manifest, sample_root):
    """Map submitted document IDs through benchmark IDs or declared filenames."""
    request = read(run / 'request.normalized.json') or {}
    preparation = read(run / 'document_preparation.json') or {}
    prepared = {d['article_id']: d.get('pdf') for d in preparation.get('documents', [])}
    by_id = {key: row for row in manifest['records'] for key in (row['candidate_id'], row.get('runtime_article_id')) if key}
    by_name = {name: row for row in manifest['records'] for name in (Path(row['packaged_path']).name, row.get('source_filename')) if name}
    mapped = {}
    for doc in request.get('documents', []):
        aid = doc['article_id']; pdf = doc.get('paths', {}).get('pdf') or prepared.get(aid)
        match = by_id.get(doc.get('source_id')) or by_id.get(aid) or (by_name.get(Path(pdf).name) if pdf else None)
        if match:
            mapped[aid] = {'source_id': match['candidate_id'], 'positive': match['role'] == 'positive_candidate'}
    for key, row in by_id.items():
        mapped.setdefault(key, {'source_id': row['candidate_id'], 'positive': row['role'] == 'positive_candidate'})
    return mapped


def exact_matches(gold, actual, *, single_target_rename=False):
    """One-to-one, source-report-constrained numeric matching."""
    used = set()
    matches = []
    for gold_index, (article, signature, gold_row) in enumerate(gold):
        found = next((j for j, (source, value, actual_row) in enumerate(actual)
                      if j not in used and article == source and same_numbers(signature, value)
                      and (single_target_rename or not gold_row.get('target_id') or
                           not actual_row.get('target_id') or
                           gold_row['target_id'] == actual_row['target_id'])), None)
        if found is not None:
            used.add(found)
            matches.append((gold_index, found))
    return matches


def gold_selection(gold, extraction_gold):
    lookup = {}
    for row in gold_rows(extraction_gold):
        for key in ('candidate_id', 'effect_estimate_id'):
            if row.get(key):
                lookup[row[key]] = row
    decisions = list((gold or {}).get('analysis_decisions', []))
    if decisions:
        result = {}
        for decision in decisions:
            ids = decision.get('selected_effect_estimate_ids') or decision.get('selected_candidate_ids') or []
            result[decision['analysis_id']] = [lookup[x] for x in ids if x in lookup]
        return result
    # The 0010 gold release declares selected studies directly in pooled_results.
    # Attach the corresponding source-count row so selected numeric values are
    # checked by the same rule as cases with effect-estimate IDs.
    by_article = {}
    for row in gold_rows(extraction_gold):
        by_article.setdefault(row.get('article_id'), []).append(row)
    return {p['analysis_id']: [by_article.get(article, [{'article_id': article}])[0]
                               for article in p.get('included_articles', [])]
            for p in (gold or {}).get('pooled_results', [])}


def compare_case(cid, run, manifest, version, sample_root, extraction_gold, analysis_gold):
    sample = read(sample_root / cid / 'screening.json')
    identities = source_map(run, sample, sample_root)
    screening = read(run / '01_screening/effective_screening_results.json') or {}
    decisions = screening.get('decisions', [])
    mapped = [(d, identities[d['candidate_id']]) for d in decisions if d.get('candidate_id') in identities]
    source_ids = [source['source_id'] for _, source in mapped]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError('Duplicate screening decision for one document')
    if len(mapped) != len(decisions):
        raise ValueError('Screening candidate ID is outside the case corpus')
    tp = sum(d.get('final_status') == 'Include' and source['positive'] for d, source in mapped)
    fp = sum(d.get('final_status') == 'Include' and not source['positive'] for d, source in mapped)
    fn = sample['positive_count'] - tp
    tn = sum(d.get('final_status') == 'Exclude' and not source['positive'] for d, source in mapped)
    screening_result = {'positive_included': tp, 'positive_total': sample['positive_count'],
                        'negative_excluded': tn, 'negative_total': sample['negative_count'],
                        'false_includes': fp, 'false_excludes': fn,
                        'mapped_decisions': len(mapped), 'all_decisions': len(decisions),
                        'unresolved_negative': sample['negative_count'] - fp - tn,
                        'membership_correct': tp + tn, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                        **prf(tp, tp + fp, sample['positive_count'])}

    submission = read(run / '02_extraction/case_extraction_submission.json') or {}
    predictions = submission.get('predictions', [])
    ids = [p.get('prediction_id') for p in predictions]
    if len(ids) != len(set(ids)) or any(not i for i in ids):
        raise ValueError('Extraction prediction IDs must be nonempty and distinct')
    gold_records = gold_rows(extraction_gold)
    gold_ids = {r.get('article_id') for r in gold_records if r.get('article_id')}
    gold_numeric = [(r['article_id'], numeric_signature(r), r) for r in gold_records]
    gold_numeric = [r for r in gold_numeric if r[1] is not None]
    actual_numeric = []
    for row in predictions:
        source = identities.get(row.get('article_id'), {}).get('source_id')
        article = resolve_article(source, gold_ids) if source else None
        signature = numeric_signature(row)
        if article and signature is not None:
            actual_numeric.append((article, signature, row))
    gold_targets = {row.get('target_id') for row in gold_records if row.get('target_id')}
    actual_targets = {row.get('target_id') for row in predictions if row.get('target_id')}
    # ma_0064 uses a single recurrence target_id across count and time-to-event source records.
    single_target_rename = (len(gold_targets) == len(actual_targets) == 1
                            or cid == 'ma_0064')
    matched = exact_matches(gold_numeric, actual_numeric,
                            single_target_rename=single_target_rename)
    extraction_result = {'gold_rows': len(gold_records), 'scorable_gold_rows': len(gold_numeric),
                         'matched_gold_rows': len(matched), 'predictions': len(predictions),
                         'mapped_numeric_predictions': len(actual_numeric),
                         'matched_prediction_rows': len(matched),
                         'unmatched_numeric_predictions': len(actual_numeric) - len(matched),
                         'unscored_gold_rows': len(gold_records) - len(gold_numeric),
                         'unscored_predictions': len(predictions) - len(actual_numeric),
                         **prf(len(matched), len(actual_numeric), len(gold_records)),
                         'missed_gold_article_ids': sorted({gold_numeric[i][0]
                             for i in range(len(gold_numeric)) if i not in {m[0] for m in matched}})}

    result = read(run / '05_analysis/analysis_result.json') or {}
    gold_decisions = gold_selection(analysis_gold, extraction_gold)
    actual_analyses = result.get('analyses', [])
    analysis_details = []
    pooled_predictions = []
    used_gold_ids = set()
    exact_ids = {(a.get('analysis') or {}).get('analysis_id') for a in actual_analyses}
    for actual in actual_analyses:
        raw_id = (actual.get('analysis') or {}).get('analysis_id')
        canonical_id = analysis_id(raw_id, cid)
        gold_id = canonical_id if canonical_id in gold_decisions else None
        if gold_id is None and len(actual_analyses) == len(gold_decisions) == 1:
            gold_id = next(iter(gold_decisions))
        if gold_id is None:
            analysis_details.append({'analysis_id': raw_id, 'status': actual.get('status'),
                                     'comparison_status': 'unmatched_analysis_id',
                                     'selected': len(actual.get('selected_evidence_ids') or [])})
            continue
        if gold_id in used_gold_ids or (raw_id != gold_id and gold_id in exact_ids):
            analysis_details.append({'analysis_id': raw_id, 'status': actual.get('status'),
                                     'comparison_status': 'duplicate_gold_analysis_id',
                                     'selected': len(actual.get('selected_evidence_ids') or [])})
            continue
        used_gold_ids.add(gold_id)
        pooled_predictions.append(dict(actual, analysis_id=gold_id))
        expected_rows = gold_decisions[gold_id]
        actual_rows = [next((row for row in predictions if row.get('prediction_id') == evidence_id), None)
                       for evidence_id in actual.get('selected_evidence_ids') or []]
        actual_rows = [row for row in actual_rows if row is not None]
        expected_articles = Counter(row.get('article_id') for row in expected_rows)
        actual_articles = Counter()
        selected_numeric = []
        for row in actual_rows:
            source = identities.get(row.get('article_id'), {}).get('source_id')
            article = resolve_article(source, gold_ids) if source else None
            actual_articles[article] += 1
            signature = numeric_signature(row)
            if article and signature is not None:
                selected_numeric.append((article, signature, row))
        report_hits = sum(min(count, actual_articles[article]) for article, count in expected_articles.items())
        expected_numeric = [(row['article_id'], numeric_signature(row), row) for row in expected_rows
                            if row.get('article_id') and numeric_signature(row) is not None]
        numeric_hits = exact_matches(expected_numeric, selected_numeric,
                                     single_target_rename=single_target_rename)
        stat = actual.get('statistics') or {}
        analysis_details.append({'analysis_id': raw_id, 'gold_analysis_id': gold_id,
                                 'status': actual.get('status'), 'gold_selected': len(expected_rows),
                                 'actual_selected': len(actual.get('selected_evidence_ids') or []), 'same_report_unit_count': report_hits,
                                 'exact_numeric_selected': len(numeric_hits),
                                 'scorable_gold_selected': len(expected_numeric),
                                 'pooled_k': stat.get('k') if stat else 0,
                                 **prf(report_hits, len(actual.get('selected_evidence_ids') or []), len(expected_rows)),
                                 'missed_gold_article_ids': sorted({article for article in expected_articles
                                      if actual_articles[article] < expected_articles[article]}),
                                 'extra_actual_article_ids': sorted(str(article) for article in actual_articles
                                      if actual_articles[article] > expected_articles.get(article, 0))})
    for gold_id in set(gold_decisions) - used_gold_ids:
        analysis_details.append({'gold_analysis_id': gold_id, 'comparison_status': 'missing_actual_analysis',
                                 'gold_selected': len(gold_decisions[gold_id]), 'actual_selected': 0,
                                 'same_report_unit_count': 0, 'exact_numeric_selected': 0,
                                 **prf(0, 0, len(gold_decisions[gold_id])),
                                 'scorable_gold_selected': sum(numeric_signature(row) is not None
                                                                for row in gold_decisions[gold_id]), 'pooled_k': 0})
    numeric = lambda field: sum(int(x.get(field) or 0) for x in analysis_details)
    analysis_result = {'run_status': result.get('status'), 'gold_selected': numeric('gold_selected'),
                       'actual_selected': numeric('actual_selected'),
                       'same_report_unit_count': numeric('same_report_unit_count'),
                       'exact_numeric_selected': numeric('exact_numeric_selected'),
                       'scorable_gold_selected': numeric('scorable_gold_selected'),
                       'pooled_k': numeric('pooled_k'), 'analyses': analysis_details,
                       **prf(numeric('same_report_unit_count'), numeric('actual_selected'), numeric('gold_selected'))}
    pooled_result = score_pooled(pooled_predictions, analysis_gold, cid)
    return {'case_id': cid, 'run': str(run), 'version': version,
            'pipeline_status': manifest.get('status'), 'screening': screening_result,
            'extraction': extraction_result, 'analysis_selection': analysis_result, 'pooled': pooled_result}
