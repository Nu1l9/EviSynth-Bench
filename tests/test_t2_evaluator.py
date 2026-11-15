"""T2 reference recovery, net scoring and OpenAI transport checks."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from evaluate_t2 import evaluate, evaluate_batch
from evaluation.extraction_metrics import score_extraction
from evaluation.numeric import gold_rows, numeric_signature, same_numbers
from evaluation.openai_judge import adjudicate
ROOT = Path(__file__).resolve().parents[1]


def gold_submissions():
    result = {}
    for path in sorted((ROOT / 'evaluation/gold').glob('*/extraction.json')):
        rows = copy.deepcopy(gold_rows(json.loads(path.read_text())))
        for i, row in enumerate(rows): row['prediction_id'] = 'prediction_' + str(i)
        result[path.parent.name] = {'case_id': path.parent.name, 'task_type': 'extraction', 'predictions': rows}
    return result


class T2Tests(unittest.TestCase):
    def test_all_288_targets_round_trip(self):
        result = evaluate_batch(gold_submissions())
        self.assertEqual(288, result['summary']['reference']['micro']['matched'])
        self.assertEqual(1.0, result['summary']['reference']['micro']['recall'])
        self.assertEqual(576, result['summary']['net_score_total'])

    def test_missing_cases_retain_288_denominator(self):
        result = evaluate_batch({})
        self.assertEqual(288, result['summary']['reference']['micro']['expected'])
        self.assertEqual(0, result['summary']['reference']['micro']['matched'])
        self.assertIsNone(result['summary']['net_score_total'])

    def test_partial_and_allele_records_preserve_explicit_values(self):
        cases = gold_submissions()
        partial = next(p for p in cases['ma_0064']['predictions'] if p['data_family'] == 'partial_binary_exposure_outcome_counts')
        altered = copy.deepcopy(partial); altered['source_data']['node_negative_arm']['events'] = 0
        self.assertFalse(same_numbers(numeric_signature(partial), numeric_signature(altered)))
        allele = next(p for p in cases['ma_0010']['predictions'] if p['data_family'] == 'allele_frequency_summary_only')
        self.assertIsNotNone(numeric_signature(allele))
        altered = copy.deepcopy(allele); del altered['case_total_n']
        self.assertIsNone(numeric_signature(altered))

    def fixture(self):
        gold = {'report_units': [{'article_id': 'paper', 'target_id': 'outcome', 'data_family': 'reported_ratio_effect',
            'effect_estimates': [{'effect_estimate_id': 'reference', 'effect': {'effect_type': 'RR', 'value': 2., 'ci_lower': 1.5, 'ci_upper': 2.5}}]}]}
        def candidate(pid, value=99, quote='Synthetic source support.'):
            return {'prediction_id': pid, 'article_id': 'paper', 'target_id': 'outcome',
                'used_effect': {'effect_type': 'RR', 'value': value, 'ci_lower': 1.5, 'ci_upper': 2.5},
                'source_location': {'source_id': 'source', 'source_quote': quote}}
        return gold, candidate

    def test_net_score_deduplication_decay_and_quoted_violations(self):
        gold, candidate = self.fixture()
        predictions = [candidate('main', 2), candidate('duplicate', 2)] + [candidate('s'+str(i)) for i in range(4)] + [candidate('violation'), candidate('unquoted', quote='')]
        judgments = [{'prediction_id': p['prediction_id'], 'label': 'supplementary' if p['prediction_id'].startswith('s') else 'strict_violation'} for p in predictions[2:]]
        report = score_extraction({'predictions': predictions}, gold, judgments)
        self.assertEqual([2, 0, 1, .5, .25, .25, -3, 0], [r['points'] for r in report['candidate_scores']])
        self.assertEqual(1, report['net_score']); self.assertEqual(1, report['reference']['matched'])

    def test_pending_judgment_keeps_net_score_pending(self):
        gold, candidate = self.fixture()
        report = score_extraction({'predictions': [candidate('unmatched')]}, gold)
        self.assertIsNone(report['net_score']); self.assertEqual(['unmatched'], report['pending_prediction_ids'])

    def test_invalid_or_duplicate_judgments_are_rejected(self):
        gold, candidate = self.fixture(); submission = {'predictions': [candidate('x')]}
        with self.assertRaises(ValueError): score_extraction(submission, gold, [{'prediction_id': 'absent', 'label': 'supplementary'}])
        with self.assertRaises(ValueError): score_extraction({'predictions': [candidate('x'), candidate('x')]}, gold)

    def test_cli_runs_with_standard_library(self):
        result = subprocess.run([sys.executable, '-S', str(ROOT/'evaluate_t2.py'), '--submission',
            str(ROOT/'tracks/t2/cases/ma_0010/submission_template.json'), '--validate-only'], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr); self.assertFalse(json.loads(result.stdout)['scored'])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); (folder/'submissions.json').write_text(json.dumps({'submissions': list(gold_submissions().values())}))
            result = subprocess.run([sys.executable, '-S', str(ROOT/'evaluate_t2.py'), '--submissions', str(folder/'submissions.json'), '--output', str(folder/'scores.json')], text=True, capture_output=True, env={**os.environ, 'PORTABLE_EVALUATOR_MODEL':'', 'OPENAI_API_KEY':''})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(576, json.loads((folder/'scores.json').read_text())['summary']['net_score_total'])

    def test_openai_request_uses_official_endpoint(self):
        gold, candidate = self.fixture(); submission = {'case_id': 'synthetic', 'predictions': [candidate('x')]}
        response = {'choices': [{'message': {'content': json.dumps({'judgments': [{'prediction_id': 'x', 'label': 'neutral_or_uncertain', 'gold_effect_estimate_id': None, 'reason': 'Synthetic judgment'}]})}}]}
        opener = mock.Mock(); opener.open.return_value = io.BytesIO(json.dumps(response).encode())
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}, clear=True), mock.patch('urllib.request.build_opener', return_value=opener):
            result = adjudicate(submission, gold, {}, 'test-model')
        request = opener.open.call_args.args[0]
        self.assertEqual('https://api.openai.com/v1/chat/completions', request.full_url)
        self.assertEqual('test-model', result['model'])

    def test_openai_requires_key_and_rejects_endpoint_override(self):
        gold, candidate = self.fixture(); submission = {'case_id': 'synthetic', 'predictions': [candidate('x')]}
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
            adjudicate(submission, gold, {}, 'test-model')
        for name in ['OPENAI_BASE_URL', 'OPENAI_API_BASE']:
            with mock.patch.dict(os.environ, {name: 'https://example.invalid/v1'}, clear=True), self.assertRaisesRegex(ValueError, 'official OpenAI'):
                adjudicate(submission, gold, {}, 'test-model')


if __name__ == '__main__': unittest.main()
