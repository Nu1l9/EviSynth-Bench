import json,tempfile,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from evaluation.scoring import exact_matches,numeric_signature,same_numbers,source_map
from scripts.export_blind import export
from evaluate import evaluate
class BenchmarkTests(unittest.TestCase):
 def test_all_case_inputs_have_separate_gold_and_identity_mapping(self):
  cases=json.loads((ROOT/'manifest.json').read_text())['cases'];self.assertEqual(22,len(cases));total=0
  for row in cases:
   request=json.loads((ROOT/row['request']).read_text());total+=len(request['documents'])
   g=ROOT/'evaluation/gold'/row['case_id'];self.assertTrue(all((g/name).is_file() for name in ['screening.json','extraction.json','analysis.json']))
   sample=json.loads((g/'screening.json').read_text())
   by_id={x.get('runtime_article_id'):x for x in sample['records']}
   for doc in request['documents']:
    self.assertNotIn('label',doc);self.assertIn(doc['article_id'],by_id)
  self.assertEqual(562,total)
 def test_blind_export_excludes_reference_answers(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=export(Path(tmp)/'blind');self.assertFalse((out/'evaluation').exists())
   self.assertEqual(22,len(list((out/'cases').glob('*/request.json'))))
   self.assertFalse(any('gold' in p.name.lower() for p in out.rglob('*')))
 def test_numeric_match_is_one_to_one_and_oriented(self):
  value={'intervention_events':0,'intervention_total':20,'control_events':4,'control_total':30}
  sig=numeric_signature({'raw_data':value});reverse=numeric_signature({'raw_data':{'intervention_events':4,'intervention_total':30,'control_events':0,'control_total':20}})
  self.assertFalse(same_numbers(sig,reverse));self.assertEqual(1,len(exact_matches([('a',sig,{}),('a',sig,{})],[('a',sig,{})])))
 def test_missing_submission_stays_null(self):
  with tempfile.TemporaryDirectory() as tmp:
   result=evaluate({'runs':[{'case_id':'ma_0024','run':tmp}]})
   self.assertIsNone(result['cases'][0]['metrics'])
 def test_missing_stages_stay_null_when_input_exists(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'request.normalized.json').write_text((ROOT/'cases/ma_0024/request.json').read_text())
   result=evaluate({'runs':[{'case_id':'ma_0024','run':tmp}]})['cases'][0]
   for stage in ['screening','extraction','analysis_selection']:self.assertIsNone(result[stage])
 def test_source_and_portable_filenames_map_to_same_source(self):
  sample=json.loads((ROOT/'evaluation/gold/ma_0001/screening.json').read_text());row=sample['records'][0]
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);results=[]
   for name in [row['source_filename'],Path(row['packaged_path']).name]:
    (p/'request.normalized.json').write_text(json.dumps({'documents':[{'article_id':'chosen','paths':{'pdf':name}}]}))
    results.append(source_map(p,sample,ROOT/'evaluation/gold')['chosen'])
   self.assertEqual(results[0],results[1])
if __name__=='__main__':unittest.main()
