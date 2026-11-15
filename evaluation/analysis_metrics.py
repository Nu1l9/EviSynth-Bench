"""Evidence selection, pooled conclusions and declared analysis coverage."""
from __future__ import annotations
import json
import math
from pathlib import Path
from evaluation.metrics import prf, aggregate_prf

ANALYSIS_ALIASES = {
    'ma_0001': {'primary_any_cv': 'main_pr_any_cv', 'secondary_cv_death': 'main_pr_cv_death',
                'secondary_mi': 'main_pr_mi', 'secondary_stroke': 'main_pr_stroke'},
    'ma_0010': {'primary_rs763780_heterozygote': 'rs763780_heterozygote_vs_common_homozygote'},
    'ma_0026': {'primary_rt_pcr_prevalence': 'rt_pcr_hcw_prevalence_main'},
    'ma_0054': {'primary_ivermectin_all_cause_mortality': 'primary_all_cause_mortality'},
    'ma_0055': {'primary_lge_all_cause_mortality': 'primary_all_cause_mortality'},
    'ma_0064': {'primary_low_volume_nodal_metastasis_recurrence': 'primary_binary_recurrence'},
}
NONCOMPARATIVE_CASES = {'ma_0024', 'ma_0026', 'ma_0028'}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def analysis_id(value, case_id):
    return ANALYSIS_ALIASES.get(case_id, {}).get(value, value)


def lookup_prediction(actual_map, target_id, case_id):
    """Prefer the submitted target ID, then an unambiguous public alias."""
    if target_id in actual_map:
        return actual_map[target_id]
    canonical_id = analysis_id(target_id, case_id)
    if canonical_id in actual_map:
        return actual_map[canonical_id]
    matches = [actual_map[alias] for alias, target in ANALYSIS_ALIASES.get(case_id, {}).items()
               if target == target_id and alias in actual_map]
    return matches[0] if len(matches) == 1 else {}


def effect_values(raw):
    """Normalize reported effect/CI fields and explicit log-ratio scales."""
    raw = raw or {}
    effect = raw.get('used_effect') or raw.get('effect') or raw.get('statistics') or raw.get('pooled_result') or raw
    if not isinstance(effect, dict):
        return {}
    measure = effect.get('effect_type') or effect.get('measure') or effect.get('scale')
    value = effect.get('value', effect.get('pooled_effect', effect.get('estimate', effect.get('estimate_or', effect.get('pooled_prevalence')))))
    interval = effect.get('ci_95') or [None, None]
    lower, upper = effect.get('ci_lower', interval[0]), effect.get('ci_upper', interval[1])
    if not measure:
        measure = 'OR' if 'estimate_or' in effect else 'proportion' if 'pooled_prevalence' in effect else None
    if measure in ('logRR', 'logOR', 'logHR', 'logIRR'):
        try:
            value, lower, upper = [math.exp(v) if finite(v) else None for v in (value, lower, upper)]
        except OverflowError:
            return {}
        measure = measure[3:]
    return {'effect_type': measure, 'value': value, 'ci_lower': lower, 'ci_upper': upper}


def null_value(measure):
    if measure in {'RR', 'OR', 'HR', 'IRR', 'generic_ratio', 'pooled OR/RR', 'OTHER'}:
        return 1.0
    if measure in {'MD', 'SMD', 'RD'} or str(measure).startswith('MD_'):
        return 0.0
    return None


def point_category(value, null):
    return 'above_null' if value > null else 'below_null' if value < null else 'at_null'


def interval_category(lower, upper, null):
    return 'above_null' if lower > null else 'below_null' if upper < null else 'includes_null'


def valid_interval(effect):
    v, lo, hi = [effect.get(k) for k in ('value', 'ci_lower', 'ci_upper')]
    return (all(finite(x) for x in (v, lo, hi)) and lo < hi and lo <= v <= hi
            and (null_value(effect.get('effect_type')) != 1.0 or lo > 0))


def primary_results(gold):
    rows = []
    for decision in gold.get('analysis_decisions', []):
        for pooled in decision.get('pooled_results', []):
            rows.append({'analysis_id': decision['analysis_id'], **pooled})
        if decision.get('pooled_result'):
            rows.append({'analysis_id': decision['analysis_id'], 'pooled_result_id': decision['analysis_id'], **decision['pooled_result']})
    rows.extend(gold.get('pooled_results', []))
    return rows


def normalize_predictions(predictions, case_id):
    if not isinstance(predictions, list):
        raise ValueError('predictions must be an array')
    result = {}
    for raw in predictions:
        if not isinstance(raw, dict):
            raise ValueError('Each analysis prediction must be an object')
        identifier = raw.get('analysis_id') or (raw.get('analysis') or {}).get('analysis_id')
        if not isinstance(identifier, str) or not identifier:
            raise ValueError('Each prediction requires an analysis_id')
        if identifier in result:
            raise ValueError('Duplicate analysis_id: ' + identifier)
        row = dict(raw, analysis_id=identifier)
        selected = row.get('selected_candidate_ids', row.get('selected_evidence_ids', []))
        if not isinstance(selected, list) or any(not isinstance(x, str) or not x for x in selected):
            raise ValueError('selected_candidate_ids must be an array of IDs')
        row['selected_candidate_ids'] = selected
        pools = row.get('pooled_results')
        if pools is None:
            pool = row.get('statistics') or row.get('pooled_result')
            pools = [pool] if isinstance(pool, dict) and pool else []
        if not isinstance(pools, list) or any(not isinstance(p, dict) for p in pools):
            raise ValueError('pooled_results must be an array of objects')
        ids = [p.get('pooled_result_id') for p in pools if p.get('pooled_result_id')]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate pooled_result_id')
        row['pooled_results'] = pools
        result[identifier] = row
    return result


def delivered_pool(prediction, reference=None):
    status = str(prediction.get('status', '')).casefold()
    if status.startswith(('blocked', 'failed', 'missing', 'error')) or status in {'not_delivered', 'not_estimable', 'insufficient_studies'}:
        return None
    pools = prediction.get('pooled_results', [])
    if reference:
        matches = [p for p in pools if p.get('pooled_result_id') == reference.get('pooled_result_id') and reference.get('pooled_result_id')]
        if len(matches) == 1:
            return matches[0]
    return pools[0] if len(pools) == 1 else None


def score_pooled(predictions, gold, case_id):
    actual = normalize_predictions(predictions, case_id)
    comparative, noncomparative = [], []
    for reference in primary_results(gold):
        aid = reference['analysis_id']; expected = effect_values(reference)
        prediction = lookup_prediction(actual, aid, case_id)
        pool = delivered_pool(prediction, reference)
        observed = effect_values(pool) if pool else {}
        row = {'case_id': case_id, 'analysis_id': aid, 'reference': expected,
               'submitted': observed or None, 'status': prediction.get('status', 'submitted' if prediction else 'missing')}
        if case_id in NONCOMPARATIVE_CASES:
            valid_scale = observed.get('effect_type') in {'proportion', 'prevalence', 'sensitivity', 'specificity'} or (expected.get('effect_type') == 'OTHER' and observed.get('effect_type') == 'OTHER')
            row['absolute_error_pp'] = {field: 100 * abs(observed[field] - expected[field])
                if valid_scale and finite(observed.get(field)) and 0 <= observed[field] <= 1 else None
                for field in ('value', 'ci_lower', 'ci_upper')}
            row['numeric_delivered'] = valid_scale and valid_interval(dict(observed, effect_type='proportion')) and all(finite(observed.get(f)) and 0 <= observed[f] <= 1 for f in ('value', 'ci_lower', 'ci_upper'))
            noncomparative.append(row)
        else:
            expected_null = null_value(expected.get('effect_type')); observed_null = null_value(observed.get('effect_type'))
            if expected_null is None:
                raise ValueError('Unknown reference effect scale: ' + str(expected))
            gd = point_category(expected['value'], expected_null)
            gc = interval_category(expected['ci_lower'], expected['ci_upper'], expected_null)
            delivered = observed_null is not None and finite(observed.get('value')) and (observed_null != 1 or observed['value'] > 0)
            direction = point_category(observed['value'], observed_null) if delivered else None
            category = interval_category(observed['ci_lower'], observed['ci_upper'], observed_null) if delivered and valid_interval(observed) else None
            row.update(reference_direction=gd, submitted_direction=direction, reference_ci_category=gc,
                       submitted_ci_category=category, direction_match=direction == gd, ci_category_match=category == gc,
                       numeric_delivered=delivered, valid_ci=category is not None)
            comparative.append(row)
    return summarize_pooled(comparative, noncomparative)


def summarize_pooled(comparative, noncomparative):
    denominator = len(comparative)
    directions = sum(r['direction_match'] for r in comparative); intervals = sum(r['ci_category_match'] for r in comparative)
    errors = {}
    for field in ('value', 'ci_lower', 'ci_upper'):
        values = [r['absolute_error_pp'][field] for r in noncomparative if r['absolute_error_pp'][field] is not None]
        errors[field] = {'mean_absolute_error_pp': sum(values) / len(values) if values else None, 'reported': len(values)}
    return {'main_analyses': denominator + len(noncomparative),
            'comparative': {'denominator': denominator, 'direction_matches': directions, 'ci_category_matches': intervals,
                            'direction_agreement': directions / denominator if denominator else None,
                            'ci_category_agreement': intervals / denominator if denominator else None,
                            'numeric_delivered': sum(r['numeric_delivered'] for r in comparative), 'results': comparative},
            'noncomparative': {'denominator': len(noncomparative), 'numeric_delivered': sum(r['numeric_delivered'] for r in noncomparative),
                               'absolute_error_pp': errors, 'results': noncomparative}}


def extension_plan(case_root):
    """Expand the declared secondary, subgroup and sensitivity analysis IDs."""
    case_root = Path(case_root); inputs = case_root / 'inputs'
    read = lambda name: json.loads((inputs / name).read_text())
    specs = []
    if (inputs / 'analysis_profile_v2.json').exists():
        profile = read('analysis_profile_v2.json')
        specs += [{'analysis_id': x['analysis_id'], 'kind': 'secondary_outcome'} for x in profile.get('secondary_outcomes', [])]
        for key, kind in [('candidate_subgroup_dimensions', 'subgroup'), ('candidate_sensitivity_dimensions', 'sensitivity')]:
            for dimension in profile.get(key, []):
                specs += [{'analysis_id': f"{kind}_{dimension['dimension_id']}_{level['value_id']}", 'kind': kind}
                          for level in dimension.get('levels', [])]
        dimension_ids = {d['dimension_id'] for d in profile.get('candidate_subgroup_dimensions', [])}
    else:
        profile = read('analysis_profile.json')
        specs += [{'analysis_id': x['analysis_id'], 'kind': 'secondary_outcome'} for x in profile.get('analyses', [])[1:]]
        dimension_ids = set()
    extensions = read('analysis_extensions.json')
    for key in ('subgroup_analyses', 'candidate_subgroup_analyses'):
        for dimension in extensions.get(key, []):
            if dimension['analysis_id'] not in dimension_ids:
                specs += [{'analysis_id': f"subgroup_{dimension['analysis_id']}_{level['level_id']}", 'kind': 'subgroup'} for level in dimension['levels']]
                dimension_ids.add(dimension['analysis_id'])
    if len({x['analysis_id'] for x in specs}) != len(specs):
        raise ValueError('Duplicate extension ID')
    return specs


def score_extensions(predictions, case_root, case_id):
    actual = normalize_predictions(predictions, case_id); rows = []
    for spec in extension_plan(case_root):
        prediction = lookup_prediction(actual, spec['analysis_id'], case_id)
        pool = delivered_pool(prediction)
        row = dict(spec, case_id=case_id, numeric_delivered=bool(pool and valid_interval(effect_values(pool))))
        rows.append(row)
    return summarize_extensions(rows)


def summarize_extensions(rows):
    groups = {}
    for kind in ('secondary_outcome', 'subgroup', 'sensitivity'):
        chosen = [r for r in rows if r['kind'] == kind]; n = len(chosen); k = sum(r['numeric_delivered'] for r in chosen)
        groups[kind] = {'covered': k, 'declared': n, 'coverage': k / n if n else None}
    n = len(rows); k = sum(r['numeric_delivered'] for r in rows)
    return {'covered': k, 'declared': n, 'coverage': k / n if n else None, 'by_kind': groups, 'results': rows}


def _score_analysis(predictions, gold, abs_tol=.01, rel_tol=.01, runtime_to_canonical=None):
    mapping = runtime_to_canonical or {}; case_id = gold['case_id'].removesuffix('_full')
    actual = normalize_predictions(predictions, case_id); rows = []
    numeric = composition = matched_pools = 0
    for expected in gold['analysis_decisions']:
        aid = expected['analysis_id']; predicted = lookup_prediction(actual, aid, case_id)
        chosen = {mapping.get(x, x) for x in predicted.get('selected_candidate_ids', [])}
        selected = set(expected.get('selected_candidate_ids', []))
        rows.append({'analysis_id': aid, **prf(len(chosen & selected), len(chosen), len(selected))})
        for reference in expected.get('pooled_results', []):
            pool = delivered_pool(predicted, reference)
            if pool is None: continue
            matched_pools += 1; observed, target = effect_values(pool), effect_values(reference)
            numeric += observed.get('effect_type') == target.get('effect_type') and all(
                finite(observed.get(f)) and math.isclose(observed[f], target[f], abs_tol=abs_tol, rel_tol=rel_tol)
                for f in ('value', 'ci_lower', 'ci_upper'))
            composition += {mapping.get(x, x) for x in pool.get('member_candidate_ids', [])} == set(reference.get('member_candidate_ids', []))
    selection = prf(sum(r['matched'] for r in rows), sum(r['predicted'] for r in rows), sum(r['expected'] for r in rows))
    pooled = score_pooled(predictions, gold, case_id); denominator = len(primary_results(gold))
    return {'selection': selection, 'selection_by_analysis': rows,
            'analysis_coverage': sum(bool(lookup_prediction(actual, d['analysis_id'], case_id))
                                     for d in gold['analysis_decisions']) / len(gold['analysis_decisions']),
            'pooled_numeric_accuracy': numeric / denominator if denominator else None,
            'pooled_composition_accuracy': composition / denominator if denominator else None,
            'pooled_direction_accuracy': pooled['comparative']['direction_agreement'],
            'matched_pooled_results': matched_pools, 'gold_pooled_results': denominator, 'pooled': pooled}
