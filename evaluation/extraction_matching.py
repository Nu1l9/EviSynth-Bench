"""Source-aware matching of reported effects, genotype tables and summaries."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any
from evaluation.extraction_shapes import flatten_prediction, number_matches, normalise_effect_type, _extract_arm_counts, _extract_continuous_arms, _extract_diagnostic_cells, _extract_arm_count_options

DEFAULT_ALIASES = {'OR': ['OR', 'aOR', 'odds ratio', 'adjusted odds ratio', 'adjusted odds ratio (aOR)'], 'RR': ['RR', 'aRR', 'risk ratio', 'rate ratio', 'adjusted rate ratio', 'adjusted risk ratio (aRR)'], 'HR': ['HR', 'aHR', 'hazard ratio', 'adjusted hazard ratio', 'adjusted hazard ratio (aHR)'], 'IRR': ['IRR', 'incidence rate ratio']}

def _arm_counts(data: Any) -> dict[str, Any]:
    """Normalize arm-level event counts from flat or nested source data."""
    if not isinstance(data, dict):
        return {}
    return _extract_arm_counts(data)

def _has_complete_arm_counts(data: Any) -> bool:
    counts = _arm_counts(data)
    return all((counts.get(field) is not None for field in ('intervention_events', 'intervention_total', 'control_events', 'control_total')))

def flatten_gold(gold: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for unit in gold.get('report_units', []):
        if not isinstance(unit, dict):
            continue
        estimates = unit.get('effect_estimates')
        if not isinstance(estimates, list):
            record = {'gold_effect_estimate_id': unit.get('article_id'), 'article_id': unit.get('article_id'), 'target_id': unit.get('target_id'), 'outcome': unit.get('outcome'), 'population_or_subgroup': unit.get('population_or_subgroup'), 'timepoint': unit.get('timepoint'), 'quantitative_usability': unit.get('quantitative_usability'), 'analysis_memberships': unit.get('analysis_memberships') or [], 'data_family': unit.get('data_family')}
            if isinstance(unit.get('case_counts'), dict) and isinstance(unit.get('control_counts'), dict):
                record['case_counts'] = unit['case_counts']
                record['control_counts'] = unit['control_counts']
            if isinstance(unit.get('case_allele_percent'), dict):
                record['case_allele_percent'] = unit['case_allele_percent']
                record['control_allele_percent'] = unit.get('control_allele_percent')
                record['case_total_n'] = unit.get('case_total_n')
                record['control_total_n'] = unit.get('control_total_n')
            if record['gold_effect_estimate_id'] and (not isinstance(unit.get('candidates'), list)):
                records.append(record)
            for candidate in unit.get('candidates', []):
                if not isinstance(candidate, dict):
                    continue
                raw = candidate.get('raw_data') or {}
                records.append({'gold_effect_estimate_id': candidate.get('candidate_id'), 'article_id': unit.get('article_id'), 'target_id': candidate.get('target_id'), 'outcome': candidate.get('outcome'), 'population_or_subgroup': candidate.get('population_or_subgroup'), 'timepoint': candidate.get('timepoint'), 'quantitative_usability': candidate.get('quantitative_usability'), 'analysis_memberships': candidate.get('analysis_memberships') or [], 'data_family': candidate.get('data_family'), 'single_events': raw.get('events'), 'single_total': raw.get('total')})
            continue
        for estimate in estimates:
            if not isinstance(estimate, dict):
                continue
            effect = estimate.get('used_effect') or estimate.get('effect')
            source_data = estimate.get('source_data')
            has_effect = isinstance(effect, dict)
            has_arm_counts = _has_complete_arm_counts(source_data)
            has_structured_data = isinstance(source_data, dict) and bool(source_data)
            if not has_effect and (not has_structured_data):
                continue
            source_measure = source_data.get('effect_measure') if isinstance(source_data, dict) else None
            record = {'gold_effect_estimate_id': estimate.get('effect_estimate_id'), 'article_id': unit.get('article_id'), 'target_id': unit.get('target_id'), 'outcome': unit.get('outcome'), 'population_or_subgroup': unit.get('population_or_subgroup'), 'timepoint': unit.get('timepoint'), 'quantitative_usability': estimate.get('quantitative_usability', unit.get('quantitative_usability')), 'analysis_memberships': unit.get('analysis_memberships') or [], 'effect_type': effect.get('effect_type') if has_effect else None, 'source_effect_measure': source_measure, 'effect_value': effect.get('value') if has_effect else None, 'ci_lower': effect.get('ci_lower') if has_effect else None, 'ci_upper': effect.get('ci_upper') if has_effect else None, 'data_family': source_data.get('data_type') if isinstance(source_data, dict) else None}
            record.update(_arm_counts(source_data))
            record.update(_extract_diagnostic_cells(source_data if isinstance(source_data, dict) else {}))
            arm_options = _extract_arm_count_options(source_data if isinstance(source_data, dict) else {})
            if arm_options:
                record['arm_count_options'] = arm_options
            continuous = _extract_continuous_arms(source_data if isinstance(source_data, dict) else {})
            if continuous:
                record['continuous_arms'] = continuous
            if isinstance(source_data, dict):
                summary = source_data.get('reported_summary')
                if isinstance(summary, dict):
                    record['reported_summary'] = summary
                    record['summary_n'] = source_data.get('n')
                    if 'planned_target' in source_data:
                        record['planned_target'] = source_data.get('planned_target')
                case_counts = source_data.get('case_counts')
                control_counts = source_data.get('control_counts')
                if isinstance(case_counts, dict) and isinstance(control_counts, dict):
                    record['case_counts'] = case_counts
                    record['control_counts'] = control_counts
                if source_data.get('events') is not None and source_data.get('total') is not None:
                    record['single_events'] = source_data.get('events')
                    record['single_total'] = source_data.get('total')
            records.append(record)
    invalid = [record for record in records if not isinstance(record['gold_effect_estimate_id'], str)]
    if invalid:
        raise ValueError('Every quantitative Gold effect needs effect_estimate_id')
    return records

def _summary_component_key(*values: Any) -> str | None:
    """Map only explicit measurement labels to a small canonical vocabulary."""
    text = ' '.join((str(value or '') for value in values)).casefold()
    text = re.sub('[_/\\-]+', ' ', text)
    if 'three dimensional' in text or re.search('\\b3\\s*d\\b', text):
        return 'three_dimensional'
    if 'absolute angular' in text or 'angular difference' in text:
        return 'absolute_angular'
    if 'anteroposterior' in text or 'anterior posterior' in text or re.search('\\banterior\\b', text):
        return 'anteroposterior'
    if 'superoinferior' in text or 'superior inferior' in text or (re.search('\\bsuperior\\b', text) and 'inclination' not in text):
        return 'superoinferior'
    if 'lateral' in text:
        return 'lateral'
    if 'inclination' in text or 'tilt' in text:
        return 'inclination'
    if 'rotation' in text:
        return 'rotation'
    if 'version' in text or 'retroversion' in text:
        return 'version'
    if 'offset' in text:
        return 'offset'
    return None

def _normalised_summary_components(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return explicitly reported summary components without deriving values."""
    summary = record.get('reported_summary')
    if not isinstance(summary, dict):
        return []
    components: list[dict[str, Any]] = []
    for (name, values) in summary.items():
        if not isinstance(values, dict):
            continue
        normalized_name = re.sub('[_/\\-]+', ' ', str(name).casefold()).strip()
        component = _summary_component_key(name)
        if component is None or normalized_name in _GENERIC_SUMMARY_KEYS:
            component = _summary_component_key(record.get('outcome_axis'), record.get('outcome'), name)
        numeric_values = {field: values.get(field) for field in _SUMMARY_VALUE_FIELDS if values.get(field) is not None}
        if component is not None and numeric_values:
            components.append({'component': component, 'n': record.get('summary_n'), 'values': numeric_values})
    return components

def _numeric_mapping_matches(actual: Any, expected: Any) -> bool:
    """Verify every explicitly required scalar in a nested Gold mapping."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all((_numeric_mapping_matches(actual.get(key), value) for (key, value) in expected.items() if value is not None))
    return number_matches(actual, expected, 0.01, 0.01)

def _planned_target_matches(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    expected = gold.get('planned_target')
    return expected is None or _numeric_mapping_matches(candidate.get('planned_target'), expected)

def _summary_component_matches(candidate_component: dict[str, Any], expected_component: dict[str, Any]) -> bool:
    if candidate_component.get('component') != expected_component.get('component'):
        return False
    expected_n = expected_component.get('n')
    if expected_n is not None and (not number_matches(candidate_component.get('n'), expected_n, 0.01, 0.01)):
        return False
    actual_values = candidate_component.get('values') or {}
    expected_values = expected_component.get('values') or {}
    return bool(expected_values) and all((number_matches(actual_values.get(field), value, 0.01, 0.01) for (field, value) in expected_values.items()))

def _same_summary_components(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    expected = _normalised_summary_components(gold)
    actual = _normalised_summary_components(candidate)
    if not expected or not _planned_target_matches(candidate, gold):
        return False
    unmatched = list(actual)
    for expected_component in expected:
        match_index = next((index for (index, actual_component) in enumerate(unmatched) if _summary_component_matches(actual_component, expected_component)), None)
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return True

def _matches_claim(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    if candidate.get('article_id') != gold.get('article_id'):
        return False
    gold_target = gold.get('target_id')
    if gold_target not in (None, '') and candidate.get('target_id') != gold_target:
        return False
    if isinstance(gold.get('case_counts'), dict) and isinstance(gold.get('control_counts'), dict):
        return _same_genotype_count_mapping(candidate.get('case_counts'), gold['case_counts']) and _same_genotype_count_mapping(candidate.get('control_counts'), gold['control_counts'])
    if isinstance(gold.get('case_allele_percent'), dict) and isinstance(gold.get('control_allele_percent'), dict):
        return _same_numeric_mapping(candidate.get('case_allele_percent'), gold['case_allele_percent']) and _same_numeric_mapping(candidate.get('control_allele_percent'), gold['control_allele_percent']) and number_matches(candidate.get('case_total_n'), gold.get('case_total_n'), 0.01, 0.01) and number_matches(candidate.get('control_total_n'), gold.get('control_total_n'), 0.01, 0.01)
    if gold.get('single_events') is not None or gold.get('single_total') is not None:
        return gold.get('single_events') is not None and gold.get('single_total') is not None and number_matches(candidate.get('single_events'), gold.get('single_events'), 0.01, 0.01) and number_matches(candidate.get('single_total'), gold.get('single_total'), 0.01, 0.01)
    arm_options = gold.get('arm_count_options')
    if isinstance(arm_options, list) and arm_options:
        candidate_arm = {'events': candidate.get('intervention_events'), 'total': candidate.get('intervention_total')}
        candidate_control = {'events': candidate.get('control_events'), 'total': candidate.get('control_total')}
        if all((value is not None for value in (*candidate_arm.values(), *candidate_control.values()))):

            def same_arm(left: dict[str, Any], right: dict[str, Any]) -> bool:
                return number_matches(left['events'], right.get('events'), 0.01, 0.01) and number_matches(left['total'], right.get('total'), 0.01, 0.01)
            return any((same_arm(candidate_arm, exposure) and same_arm(candidate_control, comparator) for exposure in arm_options for comparator in arm_options if exposure is not comparator))
    diagnostic_fields = ('true_positive', 'false_positive', 'false_negative', 'true_negative')
    if all((gold.get(field) is not None for field in diagnostic_fields)):
        if all((number_matches(candidate.get(field), gold.get(field), 0.01, 0.01) for field in diagnostic_fields)):
            return True
        values = ('intervention_events', 'intervention_total', 'control_events', 'control_total')
        if all((candidate.get(field) is not None for field in values)):
            (tp, positive_total) = (candidate['intervention_events'], candidate['intervention_total'])
            (control_value, negative_total) = (candidate['control_events'], candidate['control_total'])
            possible = ({'true_positive': tp, 'false_negative': positive_total - tp, 'false_positive': control_value, 'true_negative': negative_total - control_value}, {'true_positive': tp, 'false_negative': positive_total - tp, 'true_negative': control_value, 'false_positive': negative_total - control_value})
            return any((all((number_matches(option[field], gold[field], 0.01, 0.01) for field in diagnostic_fields)) for option in possible))
        return False
    if isinstance(gold.get('continuous_arms'), list) and gold['continuous_arms']:
        actual = candidate.get('continuous_arms')
        expected = gold['continuous_arms']
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all((all((number_matches(actual_item.get(field), expected_item.get(field), 0.01, 0.01) if expected_item.get(field) is not None else actual_item.get(field) is None for field in ('n', 'mean', 'sd'))) for (actual_item, expected_item) in zip(actual, expected)))
    if gold.get('reported_summary'):
        return _same_summary_components(candidate, gold)
    arm_fields = ('intervention_events', 'intervention_total', 'control_events', 'control_total')
    gold_has_arms = all((gold.get(field) is not None for field in arm_fields))
    candidate_has_arms = all((candidate.get(field) is not None for field in arm_fields))
    if gold_has_arms:
        return candidate_has_arms and all((number_matches(candidate.get(field), gold.get(field), 0.01, 0.01) for field in arm_fields))
    candidate_type = normalise_effect_type(candidate.get('effect_type'), DEFAULT_ALIASES)
    gold_types = {normalise_effect_type(gold.get('effect_type'), DEFAULT_ALIASES), normalise_effect_type(gold.get('source_effect_measure'), DEFAULT_ALIASES)}
    same_rate_ratio_family = candidate_type == 'IRR' and 'RR' in gold_types
    if candidate_type not in gold_types and (not same_rate_ratio_family):
        return False
    return all((number_matches(candidate.get(field), gold.get(field), 0.01, 0.01) for field in ('effect_value', 'ci_lower', 'ci_upper')))

def _canonical_genotype_key(value: Any) -> str:
    """Collapse only separator differences in explicitly named genotype keys."""
    return re.sub('[^ATCG]', '', str(value or '').upper())

def _same_genotype_count_mapping(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    normalized_actual = {_canonical_genotype_key(key): value for (key, value) in actual.items()}
    normalized_expected = {_canonical_genotype_key(key): value for (key, value) in expected.items()}
    return set(normalized_actual) == set(normalized_expected) and all((number_matches(normalized_actual[key], value, 0.01, 0.01) for (key, value) in normalized_expected.items()))

def _same_numeric_mapping(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    normalized_actual = {str(key).upper(): value for (key, value) in actual.items()}
    normalized_expected = {str(key).upper(): value for (key, value) in expected.items()}
    return set(normalized_actual) == set(normalized_expected) and all((number_matches(normalized_actual[key], value, 0.01, 0.01) for (key, value) in normalized_expected.items()))

def _single_genotype_label(value: Any) -> str | None:
    """Return the label of an explicitly named single genotype."""
    text = str(value or '').upper()
    labels = re.findall('(?<![A-Z])([ATCG])\\s*/?\\s*([ATCG])(?![A-Z])', text)
    normalized = [f'{left}{right}' for (left, right) in labels]
    recognized = [label for label in normalized if label in _GENOTYPE_LABELS]
    return recognized[0] if len(set(recognized)) == 1 else None

def _genotype_rows_from_quote(quote: Any) -> dict[str, tuple[float, float]]:
    """Read only explicitly printed genotype case/control rows from a quote."""
    text = str(quote or '')
    rows: dict[str, tuple[float, float]] = {}
    pipe_pattern = re.compile('\\b(AA|AG|GG|TT|CT|CC)\\b\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|\\s*\\d+(?:\\.\\d+)?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\b', re.IGNORECASE)
    paren_pattern = re.compile('\\b(AA|AG|GG|TT|CT|CC)\\b\\s+(\\d+(?:\\.\\d+)?)\\s*\\([^)]*\\)\\s+(\\d+(?:\\.\\d+)?)\\s*\\(', re.IGNORECASE)
    for pattern in (pipe_pattern, paren_pattern):
        for match in pattern.finditer(text):
            rows[match.group(1).upper()] = (float(match.group(2)), float(match.group(3)))
    return rows

def _genotype_rows_from_candidate(candidate: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Return source-explicit genotype rows represented by one candidate."""
    rows: dict[str, tuple[float, float]] = {}
    location = candidate.get('source_location') or {}
    rows.update(_genotype_rows_from_quote(location.get('source_quote')))
    label = _single_genotype_label(candidate.get('exposure'))
    if label is None:
        label = _single_genotype_label(candidate.get('outcome'))
    fields = ('intervention_events', 'control_events')
    if label and all((candidate.get(field) is not None for field in fields)):
        rows[label] = (float(candidate['intervention_events']), float(candidate['control_events']))
    return rows

def _same_genotype_table(actual: dict[str, tuple[float, float]], gold: dict[str, Any]) -> bool:
    expected_cases = gold.get('case_counts')
    expected_controls = gold.get('control_counts')
    if not isinstance(expected_cases, dict) or not isinstance(expected_controls, dict):
        return False
    expected_labels = set(expected_cases)
    if not expected_labels or expected_labels != set(expected_controls) or (not expected_labels.issubset(actual)):
        return False
    return all((number_matches(actual[label][0], expected_cases[label], 0.01, 0.01) and number_matches(actual[label][1], expected_controls[label], 0.01, 0.01) for label in expected_labels))

def _grouped_genotype_claims(predictions: list[dict[str, Any]], gold_effects: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Match complete genotype tables split across source-grounded candidates.

    Every reference genotype row must appear explicitly in the submission.
    """
    by_article: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_prediction in predictions:
        candidate = flatten_prediction(raw_prediction)
        if isinstance(candidate.get('article_id'), str):
            by_article[candidate['article_id']].append(candidate)
    claims: dict[str, dict[str, Any]] = {}
    supporting: dict[str, dict[str, Any]] = {}
    for gold in gold_effects:
        if not isinstance(gold.get('case_counts'), dict) or not isinstance(gold.get('control_counts'), dict):
            continue
        article_candidates = by_article.get(str(gold.get('article_id')), [])
        assembled: dict[str, tuple[float, float]] = {}
        sources_by_label: dict[str, list[str]] = defaultdict(list)
        for candidate in article_candidates:
            for (label, values) in _genotype_rows_from_candidate(candidate).items():
                expected_cases = gold['case_counts']
                expected_controls = gold['control_counts']
                if label not in expected_cases or label not in expected_controls:
                    continue
                if number_matches(values[0], expected_cases[label], 0.01, 0.01) and number_matches(values[1], expected_controls[label], 0.01, 0.01):
                    assembled[label] = values
                    sources_by_label[label].append(str(candidate['prediction_id']))
        if not _same_genotype_table(assembled, gold):
            continue
        source_ids = sorted({source_id for ids in sources_by_label.values() for source_id in ids})
        if not source_ids:
            continue
        representative = source_ids[0]
        claims[representative] = gold
        for source_id in source_ids:
            if source_id != representative:
                supporting[source_id] = gold
    return (claims, supporting)

def _grouped_summary_claims(predictions: list[dict[str, Any]], gold_effects: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Match all explicit components of a reference summary within one article."""
    by_article: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_prediction in predictions:
        candidate = flatten_prediction(raw_prediction)
        if isinstance(candidate.get('article_id'), str):
            by_article[candidate['article_id']].append(candidate)
    claims: dict[str, dict[str, Any]] = {}
    supporting: dict[str, dict[str, Any]] = {}
    for gold in gold_effects:
        expected = _normalised_summary_components(gold)
        if len(expected) < 2:
            continue
        selected_ids: list[str] = []
        for expected_component in expected:
            matches: list[str] = []
            for candidate in by_article.get(str(gold.get('article_id')), []):
                if not _planned_target_matches(candidate, gold):
                    continue
                if any((_summary_component_matches(component, expected_component) for component in _normalised_summary_components(candidate))):
                    matches.append(str(candidate['prediction_id']))
            if not matches:
                selected_ids = []
                break
            selected_ids.append(sorted(matches)[0])
        source_ids = sorted(set(selected_ids))
        if not source_ids:
            continue
        representative = source_ids[0]
        claims[representative] = gold
        for source_id in source_ids[1:]:
            supporting[source_id] = gold
    return (claims, supporting)


_SUMMARY_VALUE_FIELDS = ('mean', 'sd', 'min', 'max')

_GENERIC_SUMMARY_KEYS = {'overall', 'mean error', 'mean deviation', 'absolute difference'}

_GENOTYPE_LABELS = ('AA', 'AG', 'GG', 'TT', 'CT', 'CC')
