"""Validate task cohorts, reference denominators and participant data boundaries."""
from pathlib import Path
import argparse
import collections
import json
import re
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.numeric import gold_rows
from evaluation.scoring import numeric_signature, gold_selection
from evaluation.analysis_metrics import primary_results, extension_plan
from evaluation.contracts import CANONICAL_CASES
from scripts.export_blind import export

FORBIDDEN_CONTENT={'abstract','source_quote','source_excerpt','evidence_quote','full_text','fulltext','markdown_text','raw_text','ocr_text'}
DOC_FIELDS={'article_id','document_id','study_id','role','title','doi','source_representation','paths','genotype_contrast','supplements'}


def read(path):return json.loads(path.read_text())


def check(root=ROOT):
    errors=[]
    def require(condition,message):
        if not condition:errors.append(message)
    def walk(value,path):
        if isinstance(value,dict):
            for k,v in value.items():
                require(k not in FORBIDDEN_CONTENT,f'{path}: excluded content field {k}')
                if k in {'$schema','schema','submission_schema'} and isinstance(v,str) and v.endswith('.schema.json') and not v.startswith('http'):
                    require((path.parent/v).is_file(),f'{path.relative_to(root)}: missing schema {v}')
                walk(v,path)
        elif isinstance(value,list):
            for v in value:walk(v,path)
        elif isinstance(value,str):
            require(not re.search(r'/(?:Users|home)/[^/\s]+/|[A-Za-z]:\\',value),f'{path.relative_to(root)}: local absolute path')
    manifest=read(root/'manifest.json')
    cohorts={t:{r['case_id'] for r in read(root/f'tracks/{t}/manifest.json')['cases']} for t in ['t1','t2','t3','t4']}
    for t,ids in cohorts.items():require(len(ids)==22,f'{t}: expected 22 distinct cases')
    require(cohorts['t1']==cohorts['t2']==cohorts['t3']==cohorts['t4'],'Task cohorts differ')
    require(cohorts['t3']==set(CANONICAL_CASES),'T3 canonical case roster')
    require(manifest['cohort_difference']=={'t1_t2_t4_only':[],'t3_only':[]},'Cohort difference metadata')
    require(manifest['unique_cases_across_tracks']==len(set.union(*cohorts.values()))==22,'Unique case metadata')
    for directory in ('tracks/t3/cases','evaluation/t3_gold'):
        require({p.name for p in (root/directory).iterdir() if p.is_dir()}==cohorts['t3'],directory+': cohort directory coverage')
    def documents(docs,label):
        ids=[d['article_id'] for d in docs]
        require(len(set(ids))==len(ids),label+': duplicate document ID')
        for d in docs:
            require(set(d)<=DOC_FIELDS,label+': unexpected bibliographic fields')
            require(isinstance(d.get('title'),str) and len(d['title'].strip())>8 and not re.fullmatch(r'Candidate \d+|a_\w+',d['title']),label+': missing/placeholder title')
            doi=d.get('doi')
            require(doi is None or (isinstance(doi,str) and re.fullmatch(r'10\.\d{4,9}/\S+',doi)),label+': invalid DOI')
    n_docs=n_t2=n_candidates=n_supplements=full=supported=0
    positives=negatives=t4_units=t3_units=t4_main=t3_main=0
    extensions=collections.Counter()
    bibliography={(r['case_id'],r['article_id']):r for r in read(root/'references/articles.json')['articles']}
    for row in manifest['cases']:
        cid=row['case_id'];request=read(root/row['request']);docs=request['documents']
        documents(docs,cid);n_docs+=len(docs)
        sample=read(root/'evaluation/gold'/cid/'screening.json')
        positives+=sample['positive_count'];negatives+=sample['negative_count']
        by_runtime={r['runtime_article_id']:r for r in sample['records']}
        require(set(by_runtime)=={d['article_id'] for d in docs},cid+': screening identity coverage')
        require(sum(r['role']=='positive_candidate' for r in sample['records'])==sample['positive_count'],cid+': positive count')
        require(sum(r['role']=='negative_candidate' for r in sample['records'])==sample['negative_count'],cid+': negative count')
        for d in docs:
            b=bibliography.get((cid,d['article_id']),{})
            require(all(b.get(k)==d.get(k)==by_runtime[d['article_id']].get(k) for k in ['doi','title']),cid+': bibliography mismatch')
        t2root=root/'tracks/t2/cases'/cid;t2=read(t2root/'documents.json')['documents'];documents(t2,cid+'/t2');n_t2+=len(t2)
        n_supplements+=sum(len(d.get('supplements',[])) for d in t2)
        require({d['article_id'] for d in t2}=={r['candidate_id'] for r in sample['records'] if r['role']=='positive_candidate'},cid+': T2 source set mismatch')
        for name in read(t2root/'task.json')['input_files']:require((t2root/name).is_file(),cid+': missing T2 input')
        gold=read(root/'evaluation/gold'/cid/'extraction.json');rows=gold_rows(gold)
        full+=len(rows)
        analysis=read(root/'evaluation/gold'/cid/'analysis.json')
        t4_main+=len(primary_results(analysis))
        t4_units+=sum(map(len,gold_selection(analysis,gold).values()))
        supported+=sum(numeric_signature(r) is not None for r in rows)
    for cid in sorted(cohorts['t3']):
        case=root/'tracks/t3/cases'/cid;taskpath=case/'tasks/analysis_main_outcomes.json';task=read(taskpath)
        for name in task['input_files']:require((taskpath.parent/name).is_file(),cid+': missing T3 input')
        candidates=read(case/'inputs/analysis_evidence_candidates.json')['candidates'];ids=[c['candidate_id'] for c in candidates];n_candidates+=len(ids)
        require(len(ids)==len(set(ids)),cid+': duplicate T3 candidate ID')
        for c in candidates:require(not {'selected','is_selected','gold_label','is_gold'} & set(c),cid+': T3 selection label')
        folder=root/'evaluation/t3_gold'/cid;gold=read(folder/'analysis.json');mapping=read(folder/'candidate_id_map.json')['runtime_to_canonical_candidate_id']
        require(not mapping or set(mapping)==set(ids),cid+': incomplete T3 ID map')
        t3_units+=sum(len(d['selected_candidate_ids']) for d in gold['analysis_decisions'])
        t3_main+=len(primary_results(gold))
        extensions.update(row['kind'] for row in extension_plan(case))
        status=read(case/'inputs/analysis_extensions.json')['scoring_status']
        require(status=='declared_numeric_result_coverage',cid+': extension scoring status')
        selected={c for d in gold['analysis_decisions'] for c in d['selected_candidate_ids']}
        require(selected<={mapping.get(c,c) for c in ids},cid+': T3 Gold IDs absent from input')
    contexts=sorted((root/'evaluation/t2_contexts').glob('*.json'))
    require({p.stem for p in contexts}==cohorts['t2'],'T2 adjudication context coverage')
    for p in contexts:
        context=read(p);cid=p.stem
        require(set(context)=={'task'} and context['task']['case_id']==cid,cid+': invalid adjudication context')
        require(set(context['task']['inputs']['included_article_ids'])=={d['article_id'] for d in read(root/'tracks/t2/cases'/cid/'documents.json')['documents']},cid+': adjudication article IDs')
    for directory in ['cases','tracks','evaluation/gold','evaluation/t3_gold','evaluation/t2_contexts','references']:
        for p in (root/directory).rglob('*.json'):walk(read(p),p)
    require(n_docs==562,'T1/T4 candidate count changed')
    require(n_t2==342,'T2 document count changed')
    require(n_supplements==21,'T2 original supplementary-file inventory changed')
    require((full,supported)==(288,288),'Expected 288 supported extraction targets')
    require((positives,negatives)==(342,220),'Screening cohort totals')
    require(n_candidates==1069,'T3 candidate total')
    require((t4_main,t3_main,t4_units,t3_units)==(30,30,253,253),'Main-analysis reference totals')
    require(dict(extensions)=={'secondary_outcome':9,'subgroup':34,'sensitivity':4},'Extension-analysis totals')
    require(manifest['release_version']=='1.0.1','Release version')
    for name in ('LICENSE','LICENSE-DATA'):require((root/name).is_file(),'Missing '+name)
    blind={}
    with tempfile.TemporaryDirectory(prefix='evisynth_validation_') as tmp:
        for task in cohorts:
            folder=export(Path(tmp)/task,task)
            clean=not (folder/'evaluation').exists() and not (folder/'references').exists()
            clean=clean and all(not (folder/'tracks'/other).exists() for other in cohorts if other!=task)
            blind[task]='passed' if clean else 'failed'
            require(clean,task+': participant export isolation')
    return {'cases_per_track':{t:len(ids) for t,ids in cohorts.items()},'unique_cases':len(set.union(*cohorts.values())),
            'candidate_document_occurrences':n_docs,'t2_document_occurrences':n_t2,'t2_supplementary_file_placeholders':n_supplements,'t3_evidence_candidates':n_candidates,
            'extraction_numeric_targets':full,'numeric_matcher_supported_targets':supported,
            'screening_positive_entries':positives,'screening_negative_entries':negatives,
            'main_analyses':{'t3':t3_main,'t4':t4_main},'selection_reference_units':{'t3':t3_units,'t4':t4_units},
            'extension_analyses':{'total':sum(extensions.values()),'by_kind':dict(extensions)},'blind_exports':blind,
            'titles':len(bibliography),'dois':sum(bool(r['doi']) for r in bibliography.values()),
            'data_boundaries':'passed' if not errors else 'failed','issues':errors}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=check();payload=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(payload)
    print(payload,end='')
    raise SystemExit(bool(result['issues']))
