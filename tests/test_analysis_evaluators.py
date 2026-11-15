"""T3/T4 cohort denominators, reference round trips and pooled conclusions."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from evaluate import evaluate as evaluate_t4
from evaluate_t3 import evaluate as evaluate_t3, evaluate_batch as evaluate_t3_batch
from evaluation.analysis_metrics import (ANALYSIS_ALIASES, effect_values, extension_plan,
                                         lookup_prediction, normalize_predictions, primary_results, score_pooled)
from evaluation.numeric import gold_rows, resolve_article
from evaluation.scoring import compare_case, gold_selection
from evaluation.contracts import CANONICAL_CASES
ROOT = Path(__file__).resolve().parents[1]


def read(path): return json.loads(path.read_text())


def t3_submissions():
    result = {}
    for folder in sorted((ROOT/'evaluation/t3_gold').iterdir()):
        gold = read(folder/'analysis.json'); mapping = read(folder/'candidate_id_map.json')['runtime_to_canonical_candidate_id']; inverse = {v:k for k,v in mapping.items()}
        predictions = copy.deepcopy(gold['analysis_decisions'])
        for row in predictions:
            row['selected_candidate_ids'] = [inverse.get(x, x) for x in row['selected_candidate_ids']]
            for pooled in row.get('pooled_results', []): pooled['member_candidate_ids'] = [inverse.get(x, x) for x in pooled.get('member_candidate_ids', [])]
        result[folder.name] = {'case_id': folder.name, 'task_type': 'analysis', 'predictions': predictions}
    return result


def write_t4_gold_runs(folder):
    registry = {'runs': []}
    for gold_folder in sorted((ROOT/'evaluation/gold').iterdir()):
        cid = gold_folder.name; run = folder/cid; run.mkdir()
        request = read(ROOT/'cases'/cid/'request.json'); (run/'request.normalized.json').write_text(json.dumps(request))
        sample = read(gold_folder/'screening.json'); extraction = read(gold_folder/'extraction.json'); analysis = read(gold_folder/'analysis.json')
        refs = gold_rows(extraction); gold_ids = {x['article_id'] for x in refs}
        to_runtime = {resolve_article(row['candidate_id'], gold_ids): row['runtime_article_id'] for row in sample['records'] if resolve_article(row['candidate_id'], gold_ids)}
        predictions = []; to_prediction = {}
        key = lambda r: r.get('effect_estimate_id') or r.get('candidate_id') or r['article_id']
        for index, reference in enumerate(refs):
            prediction = copy.deepcopy(reference); prediction['prediction_id'] = 'row_' + str(index)
            prediction['article_id'] = to_runtime[reference['article_id']]; predictions.append(prediction); to_prediction[key(reference)] = prediction['prediction_id']
        selected = gold_selection(analysis, extraction); analyses = []
        for reference in primary_results(analysis):
            aid = reference['analysis_id']; effect = effect_values(reference)
            analyses.append({'analysis': {'analysis_id': aid}, 'status': 'completed',
                'selected_evidence_ids': [to_prediction[key(row)] for row in selected[aid]],
                'statistics': {'effect_type': effect['effect_type'], 'pooled_effect': effect['value'], 'ci_lower': effect['ci_lower'], 'ci_upper': effect['ci_upper'], 'k': len(selected[aid])}})
        files = {
            '01_screening/effective_screening_results.json': {'decisions': [{'candidate_id': r['runtime_article_id'], 'final_status': 'Include' if r['role'] == 'positive_candidate' else 'Exclude'} for r in sample['records']]},
            '02_extraction/case_extraction_submission.json': {'case_id': cid, 'predictions': predictions},
            '05_analysis/analysis_result.json': {'analyses': analyses},
        }
        for name, value in files.items():
            path = run/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))
        registry['runs'].append({'case_id': cid, 'run': str(run), 'system': 'reference'})
    return registry


class AnalysisEvaluatorTests(unittest.TestCase):
    def test_all_task_cohorts_match_canonical_roster_and_reject_unknown_case(self):
        rosters = [{r['case_id'] for r in read(ROOT/f'tracks/{task}/manifest.json')['cases']}
                   for task in ('t1', 't2', 't3', 't4')]
        self.assertEqual(22, len(rosters[0]))
        for roster in rosters:
            self.assertEqual(set(CANONICAL_CASES), roster)
            self.assertIn('ma_0086', roster)
        for directory in ('tracks/t3/cases', 'evaluation/t3_gold'):
            self.assertEqual(rosters[0], {p.name for p in (ROOT/directory).iterdir() if p.is_dir()})
        unknown = {'case_id': 'ma_9999', 'task_type': 'analysis', 'predictions': []}
        with self.assertRaisesRegex(ValueError, 'Unknown T3 case'):
            evaluate_t3(unknown)
        with self.assertRaisesRegex(ValueError, 'Unknown T3 case'):
            evaluate_t3_batch({'ma_9999': unknown})

    def test_ma0086_public_pool_mapping_and_primary_irr_round_trip(self):
        case = ROOT/'tracks/t3/cases/ma_0086'
        candidates = read(case/'inputs/analysis_evidence_candidates.json')['candidates']
        self.assertEqual({f'cand_{i:04d}' for i in range(1, 12)}, {r['candidate_id'] for r in candidates})
        by_id = {r['candidate_id']: r for r in candidates}
        fields = ('intervention_episodes', 'intervention_total', 'control_episodes', 'control_total', 'follow_up_months')
        for cid, article, values in [('cand_0005', 'a_200902', (12, 19, 179, 20, 18)),
                                    ('cand_0006', 'a_200701', (4, 14, 34, 12, 6))]:
            self.assertEqual(article, by_id[cid]['article_id'])
            self.assertEqual(values, tuple(by_id[cid]['raw_data'][key] for key in fields))
        mapping = read(ROOT/'evaluation/t3_gold/ma_0086/candidate_id_map.json')['runtime_to_canonical_candidate_id']
        self.assertEqual(set(by_id), set(mapping))
        self.assertEqual(['ce_0002', 'ce_0003'], [mapping[cid] for cid in ('cand_0005', 'cand_0006')])
        self.assertEqual(read(ROOT/'evaluation/gold/ma_0086/analysis.json'),
                         read(ROOT/'evaluation/t3_gold/ma_0086/analysis.json'))
        submission = read(case/'submission_template.json')
        main = submission['predictions'][0]
        main['selected_candidate_ids'] = ['cand_0005', 'cand_0006']
        main['pooled_results'] = [{'pooled_result_id': 'pr_pfapa_episode_rate',
            'effect': {'effect_type': 'IRR', 'value': .0769, 'ci_lower': .0462, 'ci_upper': .1280},
            'member_candidate_ids': ['cand_0005', 'cand_0006']}]
        report = evaluate_t3(submission); metrics = report['metrics']
        self.assertEqual('1.0.1', report['benchmark_version'])
        self.assertEqual((2, 2, 2, 1.), tuple(metrics['selection'][key] for key in ('matched', 'predicted', 'expected', 'f1')))
        self.assertEqual(1., metrics['pooled_numeric_accuracy'])
        self.assertEqual(1., metrics['pooled_composition_accuracy'])
        self.assertEqual(1, metrics['pooled']['comparative']['direction_matches'])
        self.assertEqual(1, metrics['pooled']['comparative']['ci_category_matches'])

    def test_ma0086_four_subgroups_keep_denominator_when_blocked(self):
        expected = {
            'subgroup_candidate_subgroup_surgical_procedure_tonsillectomy',
            'subgroup_candidate_subgroup_surgical_procedure_adenotonsillectomy',
            'subgroup_candidate_subgroup_pfapa_diagnostic_criteria_stringent_standard',
            'subgroup_candidate_subgroup_pfapa_diagnostic_criteria_less_stringent',
        }
        plan = extension_plan(ROOT/'tracks/t3/cases/ma_0086')
        self.assertEqual(expected, {r['analysis_id'] for r in plan})
        self.assertEqual({'subgroup'}, {r['kind'] for r in plan})
        submission = t3_submissions()['ma_0086']
        submission['predictions'] += [{'analysis_id': aid, 'status': 'insufficient_studies',
                                      'selected_candidate_ids': [], 'pooled_results': []} for aid in sorted(expected)]
        metrics = evaluate_t3(submission)['metrics']
        self.assertEqual(1., metrics['selection']['f1'])
        self.assertEqual((0, 4, 0.), tuple(metrics['extensions'][key] for key in ('covered', 'declared', 'coverage')))

    def test_t3_public_canonical_and_combined_analysis_ids(self):
        canonical = t3_submissions()['ma_0001']['predictions']
        by_id = {row['analysis_id']: row for row in canonical}
        public_names = {'main_pr_any_cv': 'primary_any_cv', 'main_pr_cv_death': 'secondary_cv_death',
                        'main_pr_mi': 'secondary_mi', 'main_pr_stroke': 'secondary_stroke'}
        public = [dict(copy.deepcopy(by_id[aid]), analysis_id=alias) for aid, alias in public_names.items()]
        public += [{'analysis_id': aid, 'pooled_results': [
            {'effect': {'effect_type': 'RR', 'value': .5, 'ci_lower': .4, 'ci_upper': .6}}]}
            for aid in ('secondary_heart_failure', 'secondary_atrial_fibrillation')]
        secondary = copy.deepcopy(public[1:])
        # Distinct extension results must not replace exact main-analysis IDs.
        for row in secondary:
            row['selected_candidate_ids'] = []
            row['pooled_results'] = [{'effect': {'effect_type': 'RR', 'value': .5, 'ci_lower': .4, 'ci_upper': .6}}]
        variants = [('public', public, 54, 4, 5), ('canonical', canonical, 62, 5, 3),
                    ('combined', canonical + secondary, 62, 5, 5),
                    ('combined_reversed', secondary + canonical, 62, 5, 5)]
        for label, predictions, matched, main_count, extension_count in variants:
            with self.subTest(submission=label):
                original = copy.deepcopy(predictions)
                metrics = evaluate_t3({'case_id': 'ma_0001', 'task_type': 'analysis', 'predictions': predictions})['metrics']
                self.assertEqual(original, predictions)
                self.assertEqual(matched, metrics['selection']['matched'])
                self.assertEqual(62, metrics['selection']['expected'])
                self.assertAlmostEqual(2 * matched / (matched + 62), metrics['selection']['f1'])
                self.assertEqual(main_count / 5, metrics['analysis_coverage'])
                self.assertEqual(main_count / 5, metrics['pooled_numeric_accuracy'])
                self.assertEqual(main_count, metrics['pooled']['comparative']['direction_matches'])
                self.assertEqual(main_count, metrics['pooled']['comparative']['ci_category_matches'])
                self.assertEqual(extension_count, metrics['extensions']['by_kind']['secondary_outcome']['covered'])
                self.assertEqual(5, metrics['extensions']['by_kind']['secondary_outcome']['declared'])

    def test_prediction_ids_preserved_and_only_raw_duplicates_rejected(self):
        predictions = [{'analysis_id': 'main_pr_cv_death'}, {'analysis_id': 'secondary_cv_death'}]
        actual = normalize_predictions(predictions, 'ma_0001')
        self.assertEqual({'main_pr_cv_death', 'secondary_cv_death'}, set(actual))
        for aid, row in actual.items():
            self.assertEqual(aid, row['analysis_id'])
        for row in predictions:
            with self.subTest(analysis_id=row['analysis_id']), self.assertRaisesRegex(ValueError, 'Duplicate analysis_id'):
                normalize_predictions([row, {'analysis': dict(row)}], 'ma_0001')

    def test_prediction_lookup_prefers_exact_and_rejects_ambiguous_reverse_aliases(self):
        canonical = {'analysis_id': 'canonical', 'status': 'completed'}
        first = {'analysis_id': 'first', 'status': 'blocked'}
        second = {'analysis_id': 'second', 'status': 'completed'}
        with patch.dict(ANALYSIS_ALIASES, {'example': {'first': 'canonical', 'second': 'canonical'}}):
            actual = {'canonical': canonical, 'first': first}
            self.assertIs(first, lookup_prediction(actual, 'first', 'example'))
            self.assertIs(canonical, lookup_prediction(actual, 'canonical', 'example'))
            self.assertIs(canonical, lookup_prediction({'canonical': canonical}, 'first', 'example'))
            self.assertIs(first, lookup_prediction({'first': first}, 'canonical', 'example'))
            self.assertEqual({}, lookup_prediction({'first': first, 'second': second}, 'canonical', 'example'))

    def compare_t4_run(self, run, cid):
        gold = ROOT / 'evaluation/gold'
        return compare_case(cid, run, {}, read(ROOT/'manifest.json')['release_version'], gold,
                            read(gold/cid/'extraction.json'), read(gold/cid/'analysis.json'))

    def test_t4_per_analysis_selection_counts_with_public_id_and_subgroup(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_t4_gold_runs(Path(tmp)); run = Path(tmp) / 'ma_0054'
            path = run / '05_analysis/analysis_result.json'; payload = read(path)
            primary = payload['analyses'][0]
            primary['analysis']['analysis_id'] = 'primary_ivermectin_all_cause_mortality'
            primary['selected_evidence_ids'] = [primary['selected_evidence_ids'][0], 'missing_evidence']
            payload['analyses'].insert(0, {'analysis': {'analysis_id': 'subgroup_example'}, 'status': 'completed'})
            path.write_text(json.dumps(payload))
            result = self.compare_t4_run(run, 'ma_0054')
        self.assertEqual(1., result['extraction']['f1'])
        row = next(r for r in result['analysis_selection']['analyses'] if r.get('gold_analysis_id'))
        self.assertEqual('primary_all_cause_mortality', row['gold_analysis_id'])
        self.assertEqual((1, 2, 4), (row['matched'], row['predicted'], row['expected']))
        self.assertEqual((1, 1, 3), (row['tp'], row['fp'], row['fn']))
        self.assertEqual((.5, .25), (row['precision'], row['recall']))
        self.assertAlmostEqual(1 / 3, row['f1'])
        self.assertEqual(row['f1'], result['analysis_selection']['f1'])
        self.assertEqual(1, result['pooled']['comparative']['ci_category_matches'])

    def test_t4_missing_main_analysis_has_complete_selection_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_t4_gold_runs(Path(tmp)); run = Path(tmp) / 'ma_0001'
            path = run / '05_analysis/analysis_result.json'; payload = read(path)
            payload['analyses'] = [a for a in payload['analyses'] if a['analysis']['analysis_id'] != 'main_pr_cv_death']
            path.write_text(json.dumps(payload)); result = self.compare_t4_run(run, 'ma_0001')
        self.assertEqual(69, result['extraction']['matched'])
        rows = {r['gold_analysis_id']: r for r in result['analysis_selection']['analyses']}
        missing = rows['main_pr_cv_death']
        self.assertEqual('missing_actual_analysis', missing['comparison_status'])
        self.assertEqual((0, 0, 6), (missing['matched'], missing['predicted'], missing['expected']))
        self.assertEqual((0, 0, 6), (missing['tp'], missing['fp'], missing['fn']))
        self.assertEqual((0., 0., 0.), (missing['precision'], missing['recall'], missing['f1']))
        for aid, expected in [('main_pr_any_cv', 33), ('main_pr_mi', 8), ('main_pr_stroke', 7), ('main_pr_composite', 8)]:
            row = rows[aid]
            self.assertEqual((expected, expected, expected, 1.), (row['matched'], row['predicted'], row['expected'], row['f1']))

    def test_t4_all_public_main_ids_match_with_extra_analyses(self):
        public_ids = {'ma_0010': 'primary_rs763780_heterozygote', 'ma_0026': 'primary_rt_pcr_prevalence',
                      'ma_0054': 'primary_ivermectin_all_cause_mortality',
                      'ma_0055': 'primary_lge_all_cause_mortality',
                      'ma_0064': 'primary_low_volume_nodal_metastasis_recurrence'}
        with tempfile.TemporaryDirectory() as tmp:
            write_t4_gold_runs(Path(tmp))
            for cid, public_id in public_ids.items():
                with self.subTest(case_id=cid):
                    run = Path(tmp) / cid; path = run / '05_analysis/analysis_result.json'; payload = read(path)
                    primary = payload['analyses'][0]; expected = len(primary['selected_evidence_ids'])
                    primary['analysis']['analysis_id'] = public_id
                    extra = {'analysis': {'analysis_id': 'subgroup_example'}, 'status': 'completed'}
                    payload['analyses'] = [extra, primary, copy.deepcopy(primary), copy.deepcopy(extra), {}]
                    path.write_text(json.dumps(payload)); result = self.compare_t4_run(run, cid)
                    selection = result['analysis_selection']
                    self.assertEqual((expected, expected, expected, 1.),
                                     (selection['matched'], selection['predicted'], selection['expected'], selection['f1']))
                    self.assertEqual(1, sum(bool(r.get('gold_analysis_id')) for r in selection['analyses']))
                    self.assertEqual(1, sum(r.get('comparison_status') == 'duplicate_gold_analysis_id' for r in selection['analyses']))
                    pooled = result['pooled']
                    self.assertEqual(1, pooled['comparative']['ci_category_matches'] + pooled['noncomparative']['numeric_delivered'])
                    for row in pooled['noncomparative']['results']:
                        self.assertEqual({'value': 0., 'ci_lower': 0., 'ci_upper': 0.}, row['absolute_error_pp'])

    def test_t4_exact_main_id_takes_priority_over_alias_without_double_counting(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_t4_gold_runs(Path(tmp)); run = Path(tmp) / 'ma_0054'
            path = run / '05_analysis/analysis_result.json'; payload = read(path)
            primary = payload['analyses'][0]; alias = copy.deepcopy(primary)
            alias['analysis']['analysis_id'] = 'primary_ivermectin_all_cause_mortality'
            alias['selected_evidence_ids'] = []; alias['status'] = 'blocked'
            for analyses in ([alias, primary], [primary, alias]):
                with self.subTest(order=[a['analysis']['analysis_id'] for a in analyses]):
                    path.write_text(json.dumps({'analyses': analyses})); result = self.compare_t4_run(run, 'ma_0054')
                    self.assertEqual(4, result['analysis_selection']['matched'])
                    self.assertEqual(4, result['analysis_selection']['expected'])
                    self.assertEqual(1, result['pooled']['comparative']['ci_category_matches'])

    def test_t3_reference_round_trip_and_all_denominators(self):
        report = evaluate_t3_batch(t3_submissions())
        self.assertEqual('1.0.1', report['benchmark_version'])
        summary = report['summary']
        self.assertEqual(253, summary['selection']['micro']['expected'])
        self.assertEqual(1, summary['selection']['micro']['f1'])
        self.assertEqual(30, summary['pooled']['main_analyses'])
        self.assertEqual(25, summary['pooled']['comparative']['denominator'])
        self.assertEqual(25, summary['pooled']['comparative']['direction_matches'])
        self.assertEqual(25, summary['pooled']['comparative']['ci_category_matches'])
        self.assertEqual(5, summary['pooled']['noncomparative']['numeric_delivered'])
        for field in summary['pooled']['noncomparative']['absolute_error_pp'].values(): self.assertEqual(0, field['mean_absolute_error_pp'])

    def test_t3_empty_batch_and_blocked_targets_keep_denominators(self):
        summary = evaluate_t3_batch({})['summary']
        self.assertEqual(253, summary['selection']['micro']['fn'])
        self.assertEqual(25, summary['pooled']['comparative']['denominator'])
        self.assertEqual(0, summary['pooled']['comparative']['direction_matches'])
        self.assertEqual(47, summary['extensions']['declared'])
        submissions = t3_submissions()
        for row in submissions['ma_0001']['predictions']: row['status'] = 'blocked'
        summary = evaluate_t3_batch(submissions)['summary']
        self.assertEqual(25, summary['pooled']['comparative']['denominator'])
        self.assertEqual(20, summary['pooled']['comparative']['direction_matches'])

    def test_all_47_extensions_and_category_counts(self):
        submissions = {}
        for folder in sorted((ROOT/'tracks/t3/cases').iterdir()):
            predictions = [{'analysis_id': r['analysis_id'], 'pooled_results': [{'effect': {'effect_type': 'RR', 'value': 1.2, 'ci_lower': .8, 'ci_upper': 1.5}}]} for r in extension_plan(folder)]
            submissions[folder.name] = {'case_id': folder.name, 'task_type': 'analysis', 'predictions': predictions}
        coverage = evaluate_t3_batch(submissions)['summary']['extensions']
        self.assertEqual((47,47,1.0), (coverage['covered'],coverage['declared'],coverage['coverage']))
        self.assertEqual({'secondary_outcome':9,'subgroup':34,'sensitivity':4}, {k:v['covered'] for k,v in coverage['by_kind'].items()})

    def test_ci_boundaries_invalid_intervals_and_log_ratios(self):
        gold = {'analysis_decisions': [{'analysis_id': 'main', 'pooled_results': [{'effect': {'effect_type': 'RR', 'value': 2, 'ci_lower': 1, 'ci_upper': 3}}]}]}
        def score(effect): return score_pooled([{'analysis_id': 'main', 'pooled_results': [{'effect': effect}]}], gold, 'ma_0005')['comparative']['results'][0]
        self.assertTrue(score({'effect_type':'RR','value':2,'ci_lower':1,'ci_upper':3})['ci_category_match'])
        row = score({'effect_type':'RR','value':2,'ci_lower':2.5,'ci_upper':3})
        self.assertTrue(row['direction_match']); self.assertFalse(row['valid_ci'])
        import math
        self.assertTrue(score({'effect_type':'logRR','value':math.log(2),'ci_lower':0,'ci_upper':math.log(3)})['ci_category_match'])

    def test_noncomparative_percentage_point_errors(self):
        submission = t3_submissions()['ma_0024']
        for row in submission['predictions']:
            for pool in row['pooled_results']:
                for field in ('value','ci_lower','ci_upper'): pool['effect'][field] += .01
        result = evaluate_t3(submission)['metrics']['pooled']['noncomparative']
        for error in result['absolute_error_pp'].values(): self.assertAlmostEqual(1., error['mean_absolute_error_pp'])

    def test_t4_reference_round_trip_and_full_micro_macro(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_t4(write_t4_gold_runs(Path(tmp)))
        summary = result['summary']
        self.assertEqual((342,220), (summary['screening']['positive_total'],summary['screening']['negative_total']))
        self.assertEqual(220, summary['screening']['true_negatives'])
        for name, expected in [('screening',342),('extraction',288),('analysis_selection',253)]:
            self.assertEqual(expected, summary[name]['micro']['matched'])
            self.assertEqual(1.0, summary[name]['micro']['f1']); self.assertEqual(1.0, summary[name]['macro']['f1'])
        self.assertEqual(25, summary['pooled']['comparative']['ci_category_matches'])
        self.assertEqual(5, summary['pooled']['noncomparative']['numeric_delivered'])
        for row in summary['pooled']['noncomparative']['results']:
            self.assertEqual({'value':0.,'ci_lower':0.,'ci_upper':0.},row['absolute_error_pp'])

    def test_t4_missing_case_outputs_keep_full_denominators(self):
        with tempfile.TemporaryDirectory() as tmp: summary = evaluate_t4({'runs':[{'case_id':'ma_0001','run':tmp}]})['summary']
        self.assertEqual(342, summary['screening']['micro']['fn'])
        self.assertEqual(288, summary['extraction']['micro']['fn'])
        self.assertEqual(253, summary['analysis_selection']['micro']['fn'])
        self.assertEqual(25, summary['pooled']['comparative']['denominator'])
        self.assertEqual(0, summary['pooled']['comparative']['ci_category_matches'])

    def test_t3_batch_cli_uses_standard_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'submissions.json'; output = root / 'result.json'
            source.write_text(json.dumps({'submissions': list(t3_submissions().values())}))
            completed = subprocess.run([sys.executable, '-S', str(ROOT / 'evaluate_t3.py'), '--submissions', str(source), '--output', str(output)], text=True, capture_output=True)
            self.assertEqual(0, completed.returncode, completed.stderr)
            summary = read(output)['summary']
            self.assertEqual(253, summary['selection']['micro']['matched'])
            self.assertEqual(25, summary['pooled']['comparative']['ci_category_matches'])

    def test_unresolved_negative_is_not_a_true_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = write_t4_gold_runs(Path(tmp))
            path = Path(registry['runs'][0]['run']) / '01_screening/effective_screening_results.json'
            payload = read(path)
            next(r for r in payload['decisions'] if r['final_status'] == 'Exclude')['final_status'] = 'Uncertain'
            path.write_text(json.dumps(payload))
            result = evaluate_t4(registry)
        self.assertEqual(219, result['summary']['screening']['true_negatives'])
        self.assertEqual(1, result['cases'][0]['screening']['unresolved_negative'])

    def test_ma0026_t4_reference_prevalence_is_preserved(self):
        pooled = primary_results(read(ROOT/'evaluation/gold/ma_0026/analysis.json'))[0]
        self.assertEqual(.12066238836306294, pooled['effect']['value'])
        self.assertEqual([.07817398025945325,.17087006543486227], [pooled['effect']['ci_lower'],pooled['effect']['ci_upper']])


if __name__ == '__main__': unittest.main()
