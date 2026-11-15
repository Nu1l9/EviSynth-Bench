"""T2 reference recall and source-supported evidence-pool net score."""
from collections import Counter
from evaluation.metrics import prf
from evaluation.numeric import gold_rows, numeric_signature, same_numbers
from evaluation.extraction_shapes import flatten_prediction
from evaluation.extraction_matching import flatten_gold, _matches_claim, _grouped_genotype_claims, _grouped_summary_claims

LABELS = {'main_hit', 'supplementary', 'strict_violation', 'neutral_or_uncertain'}


def references(gold):
    rows = gold_rows(gold)
    result = {str(r.get('effect_estimate_id') or r.get('candidate_id') or r['article_id']): r for r in rows}
    if len(result) != len(rows): raise ValueError('Reference target IDs must be unique')
    return result


def compatible(candidate, reference, flattened_reference=None):
    if candidate.get('article_id') != reference.get('article_id'): return False
    if reference.get('target_id') and candidate.get('target_id') != reference['target_id']: return False
    sig = numeric_signature(candidate); expected = numeric_signature(reference)
    if sig is not None and same_numbers(sig, expected, abs_tol=.01, rel_tol=.01): return True
    if reference.get('data_family') == 'partial_binary_exposure_outcome_counts': return False
    return bool(flattened_reference and _matches_claim(flatten_prediction(candidate), flattened_reference))


def matching_context(predictions, gold):
    refs = references(gold)
    flattened = {str(r['gold_effect_estimate_id']): r for r in flatten_gold(gold)}
    direct = {}; support = set()
    for prediction in predictions:
        matches = [key for key, reference in refs.items() if compatible(prediction, reference, flattened.get(key))]
        if len(matches) == 1: direct[prediction['prediction_id']] = matches[0]
    for group_function in (_grouped_genotype_claims, _grouped_summary_claims):
        claims, supporters = group_function(predictions, list(flattened.values()))
        for pid, reference in claims.items():
            if pid not in direct and pid not in support:
                direct[pid] = str(reference['gold_effect_estimate_id'])
        support.update(pid for pid in supporters if pid not in direct)
    return refs, flattened, direct, support


def validate_predictions(submission):
    if submission.get('task_type', 'extraction') != 'extraction': raise ValueError('Expected extraction submission')
    predictions = submission.get('predictions')
    if not isinstance(predictions, list) or any(not isinstance(p, dict) for p in predictions): raise ValueError('predictions must be an array of objects')
    ids = [p.get('prediction_id') for p in predictions]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)): raise ValueError('prediction_id must be nonempty and distinct')
    if any(not isinstance(p.get('article_id'), str) or not p['article_id'] for p in predictions): raise ValueError('Each prediction requires article_id')
    return predictions


def validate_judgments(judgments, predictions):
    if isinstance(judgments, dict): judgments = judgments.get('judgments')
    if judgments is None: judgments = []
    if not isinstance(judgments, list): raise ValueError('judgments must be an array')
    allowed = {p['prediction_id'] for p in predictions}; result = {}
    for row in judgments:
        pid = row.get('prediction_id')
        if pid not in allowed or pid in result or row.get('label') not in LABELS: raise ValueError('Invalid or duplicate adjudication')
        result[pid] = row
    return result


def score_extraction(submission, gold, judgments=None):
    predictions = validate_predictions(submission)
    refs, flattened, direct, support = matching_context(predictions, gold)
    adjudications = validate_judgments(judgments, predictions)
    credited = set(); supplements = Counter(); rows = []; pending = []
    for candidate in predictions:
        pid = candidate['prediction_id']; decision = adjudications.get(pid, {})
        target = direct.get(pid); label = decision.get('label')
        if target is None and label == 'main_hit':
            proposed = str(decision.get('gold_effect_estimate_id') or '')
            if proposed in refs and compatible(candidate, refs[proposed], flattened.get(proposed)): target = proposed
        points = 0.0; status = 'neutral_or_uncertain'
        if target is not None:
            status = 'reference_hit' if target not in credited else 'duplicate_reference_hit'
            if target not in credited: points = 2.0; credited.add(target)
        elif pid in support:
            status = 'reference_support'
        elif not decision:
            status = 'pending_adjudication'; pending.append(pid)
        else:
            location = candidate.get('source_location') or {}
            quote = location.get('source_quote') if isinstance(location, dict) else None
            if label == 'supplementary' and isinstance(quote, str) and quote.strip():
                source = location.get('source_id') or location.get('document_id')
                if source:
                    group = (candidate['article_id'], candidate.get('target_id'), str(source))
                    position = supplements[group]; supplements[group] += 1
                    points = 1.0 if position == 0 else .5 if position == 1 else .25
                    status = 'supplementary'
                else: status = 'source_id_required'
            elif label == 'strict_violation' and isinstance(quote, str) and quote.strip():
                points = -3.0; status = 'strict_violation'
            elif label in {'supplementary', 'strict_violation'}: status = 'source_quote_required'
            elif label == 'main_hit': status = 'unmatched_reference_claim'
        rows.append({'prediction_id': pid, 'reference_id': target, 'status': status, 'points': points})
    return {'reference': prf(len(credited), len(predictions), len(refs)),
            'reference_ids_matched': sorted(credited), 'net_score': sum(r['points'] for r in rows) if not pending else None,
            'main_points': 2 * len(credited), 'supplementary_points': sum(r['points'] for r in rows if r['status'] == 'supplementary'),
            'violation_points': sum(r['points'] for r in rows if r['status'] == 'strict_violation'),
            'adjudication_status': 'complete' if not pending else 'pending', 'pending_prediction_ids': pending, 'candidate_scores': rows}
