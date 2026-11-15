import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluate_t3 import evaluate
from scripts.export_blind import export
from scripts.validate_release import check


class PublicReleaseTests(unittest.TestCase):
    def test_data_boundaries_and_reference_integrity(self):
        self.assertEqual([],check()['issues'])

    def test_each_task_exports_only_its_inputs(self):
        for task in ['t1','t2','t3','t4']:
            with self.subTest(task=task),tempfile.TemporaryDirectory() as tmp:
                out=export(Path(tmp)/'participant',task)
                self.assertFalse((out/'evaluation').exists())
                self.assertFalse((out/'references').exists())
                manifest=json.loads((out/'manifest.json').read_text())
                self.assertEqual(22,len(manifest['cases']))
                for row in manifest['cases']:
                    self.assertNotIn('gold',row)
                    self.assertTrue((out/row.get('task',row.get('request'))).is_file())
                for other in {'t1','t2','t3','t4'}-{task}:
                    self.assertFalse((out/'tracks'/other).exists())
                if task=='t1':
                    data=json.loads((out/'cases/ma_0001/request.json').read_text())
                    self.assertNotIn('analysis_profile',data)
                if task=='t2':
                    self.assertFalse((out/'cases').exists())

    def test_t3_all_references_score_perfectly_and_empty_scores_zero(self):
        # Evaluator-only round trip exercises the opaque ID maps for all cases.
        for folder in sorted((ROOT/'evaluation/t3_gold').iterdir()):
            with self.subTest(case=folder.name):
                gold=json.loads((folder/'analysis.json').read_text())
                mapping=json.loads((folder/'candidate_id_map.json').read_text())['runtime_to_canonical_candidate_id']
                inverse={v:k for k,v in mapping.items()}
                predictions=copy.deepcopy(gold['analysis_decisions'])
                for p in predictions:
                    p['selected_candidate_ids']=[inverse.get(x,x) for x in p['selected_candidate_ids']]
                    for pooled in p.get('pooled_results',[]):
                        pooled['member_candidate_ids']=[inverse.get(x,x) for x in pooled.get('member_candidate_ids',[])]
                submission={'case_id':folder.name,'task_type':'analysis','predictions':predictions}
                metrics=evaluate(submission)['metrics']
                self.assertEqual(1.0,metrics['selection']['f1'])
                self.assertEqual(1.0,metrics['pooled_numeric_accuracy'])
                self.assertEqual(1.0,metrics['pooled_composition_accuracy'])
                submission['predictions']=[]
                self.assertEqual(0.0,evaluate(submission)['metrics']['selection']['recall'])

    def test_duplicate_analysis_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate({'case_id':'ma_0001','task_type':'analysis','predictions':[{'analysis_id':'x'},{'analysis_id':'x'}]})


if __name__=='__main__':unittest.main()
