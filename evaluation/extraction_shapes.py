"""Normalization of extraction records for reference matching."""
from __future__ import annotations
import math
import re
from typing import Any

def normalise_text(value: Any) -> str:
    return ' '.join(str(value).casefold().split())

def normalise_effect_type(value: Any, aliases: dict[str, list[str]]) -> str:
    text = normalise_text(value)
    for (canonical, values) in aliases.items():
        if text in {normalise_text(item) for item in [canonical, *values]}:
            return canonical
    return text

def flatten_prediction(record: dict[str, Any]) -> dict[str, Any]:
    if isinstance(record.get('source_location'), str):
        record = dict(record, source_location={'source_id': record['source_location']})
    flattened = dict(record)
    effect = record.get('used_effect')
    if isinstance(effect, dict):
        flattened.update({'effect_type': effect.get('effect_type'), 'effect_value': effect.get('value'), 'ci_lower': effect.get('ci_lower'), 'ci_upper': effect.get('ci_upper')})
    source_data = record.get('source_data')
    raw_data = record.get('raw_data')
    arm_data = source_data if isinstance(source_data, dict) else raw_data
    if not isinstance(arm_data, dict) and isinstance(raw_data, dict):
        arm_data = raw_data
    if isinstance(arm_data, dict):
        counts = _extract_arm_counts(arm_data)
        flattened.update(counts)
    if isinstance(raw_data, dict) and (not _has_complete_arm_counts(flattened)):
        flattened.update(_extract_arm_counts(raw_data))
    for data in (source_data, raw_data):
        if not isinstance(data, dict):
            continue
        if isinstance(data.get('reported_summary'), dict):
            flattened['reported_summary'] = data['reported_summary']
            flattened['summary_n'] = data.get('n')
            if 'planned_target' in data:
                flattened['planned_target'] = data.get('planned_target')
        case_counts = data.get('case_counts')
        control_counts = data.get('control_counts')
        if isinstance(case_counts, dict) and isinstance(control_counts, dict):
            flattened['case_counts'] = case_counts
            flattened['control_counts'] = control_counts
        case_allele_percent = data.get('case_allele_percent')
        control_allele_percent = data.get('control_allele_percent')
        if isinstance(case_allele_percent, dict) and isinstance(control_allele_percent, dict):
            flattened['case_allele_percent'] = case_allele_percent
            flattened['control_allele_percent'] = control_allele_percent
            flattened['case_total_n'] = data.get('case_total_n')
            flattened['control_total_n'] = data.get('control_total_n')
        events = data.get('events')
        total = data.get('total')
        if events is not None and total is not None:
            flattened['single_events'] = events
            flattened['single_total'] = total
        elif data.get('intervention_episodes') is not None and data.get('intervention_total') is not None:
            flattened['single_events'] = data.get('intervention_episodes')
            flattened['single_total'] = data.get('intervention_total')
        continuous = _extract_continuous_arms(data)
        if continuous:
            flattened['continuous_arms'] = continuous
        diagnostic = _extract_diagnostic_cells(data)
        if diagnostic:
            flattened.update(diagnostic)
        arm_options = _extract_arm_count_options(data)
        if arm_options:
            flattened['arm_count_options'] = arm_options
    if not _has_complete_diagnostic_cells(flattened):
        quote = str((record.get('source_location') or {}).get('source_quote') or '')
        parsed = _diagnostic_cells_from_quote(quote)
        if parsed:
            flattened.update(parsed)
    return flattened

def _extract_arm_counts(data: dict[str, Any]) -> dict[str, Any]:
    """Map common two-group schemas to canonical intervention/control fields."""
    direct = {'intervention_events': data.get('intervention_events', data.get('intervention_arm.events')), 'intervention_total': data.get('intervention_total', data.get('intervention_arm.total')), 'control_events': data.get('control_events', data.get('comparator_arm.events')), 'control_total': data.get('control_total', data.get('comparator_arm.total'))}
    intervention_keys = ('intervention_arm', 'treatment_arm', 'exposure_arm', 'exposed_arm', 'intervention_group', 'treatment_group', 'exposure_group', 'exposed_group', 'pandemic_group', 'experimental_group', 'group_1', 'group1')
    control_keys = ('comparator_arm', 'control_arm', 'comparison_arm', 'reference_arm', 'comparator_group', 'control_group', 'comparison_group', 'reference_group', 'unexposed_group', 'usual_care_group', 'group_2', 'group2')

    def arm_values(keys: tuple[str, ...]) -> tuple[Any, Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict) and value.get('events') is not None and (value.get('total', value.get('n')) is not None):
                return (value.get('events'), value.get('total', value.get('n')))
        return (None, None)
    (intervention_events, intervention_total) = arm_values(intervention_keys)
    (control_events, control_total) = arm_values(control_keys)
    if intervention_events is None:
        intervention_events = direct['intervention_events']
    if intervention_total is None:
        intervention_total = direct['intervention_total']
    if control_events is None:
        control_events = direct['control_events']
    if control_total is None:
        control_total = direct['control_total']
    if intervention_events is None or intervention_total is None or control_events is None or (control_total is None):
        arms = [value for value in data.values() if isinstance(value, dict) and value.get('events') is not None and (value.get('total', value.get('n')) is not None)]
        if len(arms) == 2:
            (intervention_events, intervention_total) = (arms[0].get('events'), arms[0].get('total', arms[0].get('n')))
            (control_events, control_total) = (arms[1].get('events'), arms[1].get('total', arms[1].get('n')))
    return {'intervention_events': intervention_events, 'intervention_total': intervention_total, 'control_events': control_events, 'control_total': control_total}

def _has_complete_arm_counts(data: dict[str, Any]) -> bool:
    return all((data.get(field) is not None for field in ('intervention_events', 'intervention_total', 'control_events', 'control_total')))

def _extract_continuous_arms(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize one/two continuous arms while retaining source order."""
    arms = data.get('arms')
    normalized: list[dict[str, Any]] = []
    if isinstance(arms, dict):
        for value in arms.values():
            if isinstance(value, dict) and any((value.get(field) is not None for field in ('mean', 'sd', 'n'))):
                normalized.append({field: value.get(field) for field in ('n', 'mean', 'sd')})
    elif isinstance(arms, list):
        for value in arms:
            if isinstance(value, dict) and any((value.get(field) is not None for field in ('mean', 'sd', 'n', 'total'))):
                normalized.append({'n': value.get('n', value.get('total')), 'mean': value.get('mean'), 'sd': value.get('sd')})
    if normalized:
        return normalized
    named_arms = []
    for key in ('intervention_arm', 'treatment_arm', 'exposure_arm', 'exposed_arm', 'intervention_group', 'treatment_group', 'exposure_group', 'exposed_group', 'group_1', 'group1', 'comparator_arm', 'control_arm', 'comparison_arm', 'reference_arm', 'comparator_group', 'control_group', 'comparison_group', 'reference_group', 'group_2', 'group2'):
        value = data.get(key)
        if not isinstance(value, dict):
            continue
        n = value.get('n', value.get('total'))
        if n is not None and value.get('mean') is not None and (value.get('sd') is not None):
            named_arms.append({'n': n, 'mean': value.get('mean'), 'sd': value.get('sd')})
    if len(named_arms) == 2:
        return named_arms
    if any((data.get(field) is not None for field in ('intervention_mean', 'intervention_sd', 'intervention_total'))):
        result = [{'n': data.get('intervention_total'), 'mean': data.get('intervention_mean'), 'sd': data.get('intervention_sd')}]
        if any((data.get(field) is not None for field in ('control_mean', 'control_sd', 'control_total'))):
            result.append({'n': data.get('control_total'), 'mean': data.get('control_mean'), 'sd': data.get('control_sd')})
        return result
    return []

def _extract_diagnostic_cells(data: dict[str, Any]) -> dict[str, Any]:
    direct = {field: data.get(field) for field in ('true_positive', 'false_positive', 'false_negative', 'true_negative')}
    if all((value is not None for value in direct.values())):
        return direct
    context = ' '.join((str(data.get(key, '')) for key in ('outcome_unit', 'effect_measure', 'data_type')))
    if 'diagnostic' not in context.casefold() and 'confusion' not in context.casefold():
        return {}
    if all((data.get(field) is not None for field in ('intervention_events', 'intervention_total', 'control_events', 'control_total'))):
        return {'true_positive': data['intervention_events'], 'false_negative': float(data['intervention_total']) - float(data['intervention_events']), 'true_negative': data['control_events'], 'false_positive': float(data['control_total']) - float(data['control_events'])}
    return {}

def _has_complete_diagnostic_cells(data: dict[str, Any]) -> bool:
    return all((data.get(field) is not None for field in ('true_positive', 'false_positive', 'false_negative', 'true_negative')))

def _diagnostic_cells_from_quote(quote: str) -> dict[str, Any]:
    """Read explicitly named TP/FP/FN/TN counts from a source quotation."""
    aliases = {'true_positive': ('true positive', 'tp'), 'false_positive': ('false positive', 'fp'), 'false_negative': ('false negative', 'fn'), 'true_negative': ('true negative', 'tn')}
    result: dict[str, Any] = {}
    for (field, names) in aliases.items():
        match = re.search(f"(?:{'|'.join((re.escape(name) for name in names))})\\s*[=:]?\\s*(\\d+(?:\\.0+)?)", quote, re.IGNORECASE)
        if match:
            result[field] = float(match.group(1))
    return result if len(result) == 4 else {}

def _extract_arm_count_options(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return source arms from multi-arm count tables without selecting one."""
    arms = data.get('arms')
    if not isinstance(arms, list):
        return []
    options = []
    for arm in arms:
        if not isinstance(arm, dict):
            continue
        (events, total) = (arm.get('events'), arm.get('n', arm.get('total')))
        if events is not None and total is not None:
            options.append({'events': events, 'total': total, 'role': arm.get('role'), 'label': arm.get('label')})
    return options

def number_matches(left: Any, right: Any, absolute: float, relative: float) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return math.isclose(float(left), float(right), abs_tol=absolute, rel_tol=relative)
    except (TypeError, ValueError):
        return False
