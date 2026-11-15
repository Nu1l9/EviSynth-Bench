# EviSynth-Bench

## Overview

**EviSynth-Bench v1.0.1** accompanies **TRACE: traceable, reviewable, agentic and cross-stage evidence synthesis for medical meta-analysis**. It evaluates literature screening, evidence extraction, statistical analysis and end-to-end evidence synthesis.

The benchmark is an independent repository of task inputs, reference annotations, schemas and evaluation code. All evaluators use the Python standard library and run independently of the TRACE runtime. Python **3.10+** is required.

## Task Suite & Dataset Statistics

| Task | Cases | Input | Evaluation reference |
| --- | ---: | --- | --- |
| T1 — screening | 22 | 562 candidate-document entries | 342 included and 220 excluded entries |
| T2 — extraction | 22 | 342 included documents and 21 supplementary-file placeholders | 288 quantitative reference records |
| T3 — analysis | 22 | 1,069 structured evidence candidates | 30 main analyses; 253 selected evidence units |
| T4 — end-to-end synthesis | 22 | Candidate documents, protocols and analysis profiles | T1/T2 references; 30 main analyses with 253 selected evidence units |

All four tasks share the same **22 case IDs**, including `ma_0086`. Evidence-selection units are counted within each analysis, so a source used in two analyses contributes two units.

The analysis profiles additionally declare **47 extension analyses**: 9 secondary outcomes, 34 subgroup levels and 4 sensitivity analyses. The 30 main analyses comprise **25 comparative** and **5 noncomparative** analyses. The latter are sensitivity/specificity in `ma_0024` and `ma_0028`, and prevalence in `ma_0026`.

## Literature Retrieval Policy

Publications are listed by **DOI and title**. Retrieve the publications locally and place them at the relative paths in each request or document manifest. Supplementary-file placeholders identify the associated article. The bibliography contains 562 titles and 557 DOI values; the five title-only entries are listed in [references/missing_dois.json](references/missing_dois.json).

Document counts refer to case-document entries. T3 operates on the supplied structured evidence candidates. PDFs, article text, abstracts and source figures are obtained separately.

## Repository Structure

```text
cases/<case>/request.json              T1/T4 requests and document identities
tracks/t1|t2|t3|t4/manifest.json        Task cohorts and file pointers
tracks/t2/cases/<case>/                Extraction task, protocol and document list
tracks/t3/cases/<case>/                Analysis task, profiles and evidence candidates
references/                           DOI/title bibliography
evaluation/gold/<case>/                T1/T2/T4 references
evaluation/t3_gold/<case>/             T3 references and evaluator ID maps
evaluation/t2_contexts/<case>.json     Extraction adjudication task contracts
schemas/                              Public JSON schemas
evaluate.py                           T1/T4 evaluation
evaluate_t2.py                        T2 reference recovery and net score
evaluate_t3.py                        T3 selection, conclusions and coverage
```

## Quick Start & Blind Export

Give each participant an export of its assigned task. The exporter includes that task's inputs and schemas; evaluator references and other tasks are kept in the benchmark checkout.

```bash
python scripts/export_blind.py --task t1 --output ../participant-t1
python scripts/export_blind.py --task t2 --output ../participant-t2
python scripts/export_blind.py --task t3 --output ../participant-t3
python scripts/export_blind.py --task t4 --output ../participant-t4
```

Score a submission or a case registry:

```bash
python evaluate.py --runs runs.json --output results/t1_t4.json
python evaluate_t2.py --submission submission.json --adjudications judgments.json --output results/t2.json
python evaluate_t2.py --submissions t2_submissions.json --adjudications t2_judgments.json --output results/t2_batch.json
python evaluate_t3.py --submission submission.json --output results/t3.json
python evaluate_t3.py --submissions t3_submissions.json --output results/t3_batch.json
```

A batch registry contains `{"submissions": [{"case_id": "ma_0010", "submission": "submissions/ma_0010.json"}]}`. Paths are relative to the registry. Batch evaluation uses the complete 22-case reference cohort. [OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md) specifies submissions, adjudications and result fields.

### T2 semantic adjudication with OpenAI

Reference matching and score arithmetic run locally. Supplementary evidence and strict violations require evaluator judgments supported by source quotations. Supply a judgment JSON as above, or generate judgments with an **OpenAI model ID and OpenAI API key**:

```bash
cp .env.example .env
```

Fill both settings in the repository-root `.env`:

```dotenv
OPENAI_API_KEY=replace_with_your_openai_api_key
PORTABLE_EVALUATOR_MODEL=replace_with_your_openai_judge_model_id
```

Then run:

```bash
python evaluate_t2.py --submission submission.json --output results/t2.json
```

The judge uses the official OpenAI API at `https://api.openai.com/v1`. Select an OpenAI model available to your account that supports structured JSON responses. Judgments and the selected model are recorded with the result. Use the same judge and evaluation settings when comparing systems. API requests send the task contract, reference targets and submitted source quotations to OpenAI and may incur usage charges. Keep `.env` local.

For input validation:

```bash
python evaluate_t2.py --submission tracks/t2/cases/ma_0010/submission_template.json --validate-only
```

## Evaluation & Metrics

| Task | Reported metrics |
| --- | --- |
| T1 | Per-case TP/FP/FN/TN, precision, recall and F1; cohort micro and macro averages; 342 positive and 220 negative references |
| T2 | Deduplicated quantitative-reference hits, recall over 288 targets, precision/F1 and per-case/cumulative extraction net score |
| T3 | Selection micro P/R/F1 over 253 analysis-specific units; direction and 95% CI category agreement over 25 comparative analyses; percentage-point deviations for 5 noncomparative analyses; numeric-result coverage over 47 extensions |
| T4 | Screening and extraction metrics; multiset selection over 253 analysis-specific units; the same 25 comparative and 5 noncomparative pooled-result comparisons |

T2 net scoring awards **+2** for the first hit of each reference target. Within an `(article, target, source)` group, source-supported supplementary records receive **+1**, **+0.5**, then **+0.25 for each subsequent record**. Each source-quoted strict protocol violation receives **−3**. Repeated hits of one reference target receive zero additional credit.

For comparative analyses, direction is evaluated relative to the null value: **1** for ratios and **0** for differences. CI categories are fully above, fully below, or including the null. Missing and blocked analyses remain in the 25-analysis denominator. Noncomparative errors are `100 × |submitted − reference|` for the point estimate and both CI bounds. Extension coverage counts mapped results with a finite point estimate and valid 95% CI. See [DATA_FORMAT.md](DATA_FORMAT.md) for units and tolerances.

### Validation and source archive

```bash
python scripts/check_repository.py
python scripts/validate_release.py
python -m unittest discover -s tests -v
python scripts/build_release.py --output ../releases/EviSynth-Bench-github.zip
```

[VALIDATION.json](VALIDATION.json) records dataset statistics and validation results. `FILE_MANIFEST.json` contains source-file SHA-256 checksums.

## Citation

```bibtex
@misc{evisynthbench2026,
  title = {TRACE: traceable, reviewable, agentic and cross-stage evidence synthesis for medical meta-analysis},
  year = {2026},
  version = {1.0.1},
  howpublished = {EviSynth-Bench: task data, reference annotations and evaluation code},
  url = {https://github.com/Nu1l9/EviSynth-Bench}
}
```

## License

Code is released under the [MIT License](LICENSE). Benchmark annotations, task definitions and dataset documentation are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); see [LICENSE-DATA](LICENSE-DATA) for attribution.
