"""Count-based precision, recall and F1 summaries."""
def prf(matched, predicted, expected):
    if not 0 <= matched <= min(predicted, expected):
        raise ValueError('Matched count exceeds the prediction or reference count')
    return {'tp': matched, 'fp': predicted - matched, 'fn': expected - matched,
            'matched': matched, 'predicted': predicted, 'expected': expected,
            'precision': matched / predicted if predicted else 0.0,
            'recall': matched / expected if expected else 0.0,
            'f1': 2 * matched / (predicted + expected) if predicted + expected else 0.0}


def aggregate_prf(rows):
    micro = prf(sum(r['matched'] for r in rows), sum(r['predicted'] for r in rows), sum(r['expected'] for r in rows))
    macro = {key: sum(r[key] for r in rows) / len(rows) if rows else 0.0 for key in ('precision', 'recall', 'f1')}
    return {'micro': micro, 'macro': macro, 'cases': len(rows)}
