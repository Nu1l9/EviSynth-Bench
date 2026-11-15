"""Numeric signatures for reported effects and structured source evidence."""
from __future__ import annotations
import math
from evaluation.contracts import FAMILY_ALIASES

def _number(value):
    return isinstance(value, (int,float)) and not isinstance(value, bool) and math.isfinite(value)


def _values(raw, keys):
    values=tuple(raw.get(k) for k in keys)
    return values if all(_number(v) for v in values) else None


def _base_numeric_signature(row):
    """Return an oriented, lossless numeric tuple for explicitly known shapes."""
    raw=row.get('raw_data') or row.get('source_data') or row
    if not isinstance(raw,dict):return None
    family=FAMILY_ALIASES.get(row.get('data_family'), row.get('data_family'))
    if family == 'allele_frequency_summary_only' or 'case_allele_percent' in raw:
        case, control = raw.get('case_allele_percent'), raw.get('control_allele_percent')
        totals = _values(raw, ('case_total_n', 'control_total_n'))
        if isinstance(case, dict) and isinstance(control, dict) and set(case) == set(control) and case and totals and all(_number(x) for x in [*case.values(), *control.values()]):
            return ('allele_frequency', *totals, tuple(sorted(case.items())), tuple(sorted(control.items())))
        return None
    if family == 'partial_binary_exposure_outcome_counts' or raw.get('data_type') == 'partial_binary_exposure_outcome_counts':
        arms = [(key, arm) for key, arm in sorted(raw.items()) if key.endswith('_arm') and isinstance(arm, dict)]
        if arms and any(_number(arm.get(k)) for _, arm in arms for k in ('events', 'n')):
            if all(arm.get(k) is None or _number(arm.get(k)) for _, arm in arms for k in ('events', 'n')):
                return ('partial_binary', tuple((key, arm.get('events'), arm.get('n')) for key, arm in arms))
        return None
    if family=='complete_genotype_case_control_counts' or ('case_counts' in raw and 'control_counts' in raw):
        a,b=raw.get('case_counts'),raw.get('control_counts')
        if isinstance(a,dict) and isinstance(b,dict) and set(a)==set(b) and all(_number(v) for v in [*a.values(),*b.values()]):
            return ('genotype', tuple(sorted((str(k).replace('/', '').replace('|', '').upper(), v) for k,v in a.items())), tuple(sorted((str(k).replace('/', '').replace('|', '').upper(), v) for k,v in b.items())))
    for keys in [('intervention_events','intervention_total','control_events','control_total'),('new_ppm_deaths','new_ppm_total','no_new_ppm_deaths','no_new_ppm_total'),('20g_events','20g_total','mivs_events','mivs_total')]:
        values=_values(raw,keys)
        if values is not None: return ('binary', *values)
    for a,b in [('intervention_arm','control_arm'),('intervention_arm','comparator_arm'),('exposed_arm','unexposed_arm'),('pandemic_group','reference_group'),('pandemic_group','prepandemic_group'),('pandemic_group','pre_pandemic_group')]:
        if isinstance(raw.get(a),dict) and isinstance(raw.get(b),dict):
            av=_values(raw[a],('events','n')) or _values(raw[a],('events','total'))
            bv=_values(raw[b],('events','n')) or _values(raw[b],('events','total'))
            if av is not None and bv is not None: return ('binary',*av,*bv)
    for keys in [('true_positive','false_positive','false_negative','true_negative'),('tp','fp','fn','tn')]:
        values=_values(raw,keys)
        if values is not None:return ('diagnostic',*values)
    if family=='single_arm_event_counts' or raw.get('data_type')=='single_arm_event_counts':
        values=_values(raw,('events','total'))
        if values is not None:return ('proportion',*values)
    for keys in [('intervention_n','intervention_mean','intervention_sd','control_n','control_mean','control_sd')]:
        values=_values(raw,keys)
        if values is not None:return ('continuous',*values)
    if family in ('adjusted_ratio_effect','reported_ratio_effect','time_to_event','reported_standardized_mean_difference') or raw.get('data_type') in ('adjusted_effect_estimate','reported_adjusted_hazard_ratio','reported_adjusted_rate_ratio'):
        effect=raw.get('reported_effect') or row.get('used_effect') or row.get('effect') or {}
        for block,keys in [(raw,('effect_value','ci_lower','ci_upper')),(raw,('value','ci_lower','ci_upper')),(effect,('value','ci_lower','ci_upper'))]:
            values=_values(block,keys)
            if values is not None:
                measure=raw.get('effect_type') or raw.get('reported_effect_type') or raw.get('effect_measure') or effect.get('effect_type')
                return ('reported',measure,*values)
    effect = row.get('used_effect') or row.get('effect') or {}
    if isinstance(effect, dict):
        values = _values(effect, ('value', 'ci_lower', 'ci_upper'))
        if values is not None and effect.get('effect_type'):
            return ('reported', effect['effect_type'], *values)
    return None



def axis(raw):
    label = str(raw.get('outcome_axis') or '').casefold()
    if 'version' in label or 'retroversion' in label:
        return 'version'
    if 'inclination' in label or 'tilt' in label:
        return 'inclination'
    if 'offset' in label or 'starting' in label:
        return 'offset'
    return label


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def pair(arm):
    n = arm.get('n', arm.get('total'))
    e = arm.get('events')
    return (e, n) if finite(e) and finite(n) else None


def continuous(arm):
    values = (arm.get('n'), arm.get('mean'), arm.get('sd'))
    return values if all(finite(v) for v in values) else None


def numeric_signature(row):
    signature = _base_numeric_signature(row)
    if signature is not None:
        return signature
    raw = row.get('raw_data') or row.get('source_data') or row
    if not isinstance(raw, dict):
        return None
    arms = raw.get('arms')
    if isinstance(arms, dict):
        values = [continuous(v) for v in arms.values() if isinstance(v, dict)]
        if len(values) == 2 and all(values):
            return ('continuous_arms', axis(raw), tuple(sorted(values)))
    for first, second in (('intervention_arm', 'comparator_arm'), ('intervention_arm', 'control_arm')):
        if isinstance(raw.get(first), dict) and isinstance(raw.get(second), dict):
            values = [continuous(raw[first]), continuous(raw[second])]
            if all(values):
                return ('continuous_arms', axis(raw), tuple(sorted(values)))
    if isinstance(arms, list):
        valid = [(str(a.get('role') or a.get('label') or ''), pair(a)) for a in arms if isinstance(a, dict)]
        if valid and all(v is not None for _, v in valid):
            low = [v for role, v in valid if role == 'low_volume_metastasis']
            negative = [v for role, v in valid if role == 'node_negative']
            if low and len(negative) == 1 and len(low) + 1 == len(valid):
                return ('binary', sum(x[0] for x in low), sum(x[1] for x in low), *negative[0])
            if len(valid) == 2:
                interventions = [v for role, v in valid if 'intervention' in role]
                controls = [v for role, v in valid if 'control' in role or 'comparator' in role]
                if len(interventions) == len(controls) == 1:
                    return ('binary', *interventions[0], *controls[0])
            return ('binary_multi', tuple(sorted((role, *v) for role, v in valid)))
    episodes = tuple(raw.get(k) for k in ('intervention_episodes', 'intervention_total',
                                          'control_episodes', 'control_total', 'follow_up_months'))
    if all(finite(v) for v in episodes):
        return ('episodes', *episodes)
    summary = raw.get('reported_summary')
    if isinstance(summary, dict) and finite(raw.get('n')):
        def leaves(item, prefix=''):
            if isinstance(item, dict):
                return [out for key, val in sorted(item.items()) for out in leaves(val, prefix + '.' + key)]
            return [(prefix, item)] if finite(item) else []
        values = tuple(leaves(summary))
        if values:
            return ('continuous_summary', axis(raw), raw['n'], values)
    return None


def same_numbers(left, right, *, abs_tol=1e-8, rel_tol=1e-6):
    if left is None or right is None or len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if isinstance(a, tuple) and isinstance(b, tuple):
            if not same_numbers(a, b, abs_tol=abs_tol, rel_tol=rel_tol):
                return False
        elif finite(a) and finite(b):
            if not math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol):
                return False
        elif a != b:
            return False
    return True



def gold_rows(gold):
    rows=[]
    for unit in (gold or {}).get('report_units',[]):
        children=unit.get('candidates') or unit.get('effect_estimates') or []
        if not children and any(k in unit for k in ('case_counts', 'case_allele_percent', 'raw_data', 'source_data')):children=[{}]
        for child in children:
            row={**unit,**child}
            row.pop('effect_estimates',None);row.pop('candidates',None)
            rows.append(row)
    return rows


def resolve_article(source_id, gold_ids):
    if source_id in gold_ids:return source_id
    matches=[x for x in gold_ids if x.startswith(source_id+'_')]
    return matches[0] if len(matches)==1 else None
