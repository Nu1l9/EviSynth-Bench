# Submission and Evaluation Contract

## T1/T4 case registry

```json
{"runs": [{"system": "system_name", "case_id": "ma_0010", "run": "runs/ma_0010"}]}
```

Paths are relative to the registry. Each system/case pair is unique. A case directory contains:

| File | Contents |
| --- | --- |
| `request.normalized.json` | `documents` with submitted article IDs and benchmark IDs or source/portable PDF filenames |
| `01_screening/effective_screening_results.json` | `decisions` with `candidate_id` and `final_status` (`Include` or `Exclude`) |
| `02_extraction/case_extraction_submission.json` | Extraction `predictions`, each with a unique `prediction_id` and `article_id` |
| `05_analysis/analysis_result.json` | `analyses`, each with `analysis.analysis_id`, `selected_evidence_ids`, `status`, and `statistics` |

Analysis statistics use `effect_type`, `pooled_effect`, `ci_lower`, `ci_upper` and optional `k`. Selected evidence IDs refer to extraction prediction IDs. A screening document has one decision. T4 source-report selection is matched within each reference analysis.

```bash
python evaluate.py --runs runs.json --output results/t1_t4.json
```

The report contains `cases` and per-system `summaries`. A single-system report also exposes `summary`. Each summary includes screening/extraction/selection `micro` and `macro` metrics, plus `pooled.comparative` and `pooled.noncomparative`. Full cohort denominators are 342 screening positives, 220 negatives, 288 extraction targets, 253 selection units and 25 comparative analyses.

## T2 extraction submission

```json
{
  "case_id": "ma_0010",
  "task_type": "extraction",
  "predictions": []
}
```

Populate `predictions` using `schemas/t2-submission.schema.json`. Each record requires a distinct `prediction_id`, the source `article_id`, and the requested target and numerical fields. Structured quantities belong in `raw_data` or `source_data`; reported effects may use `used_effect`. Source support belongs in `source_location`, including `source_id` and `source_quote` for semantically adjudicated evidence.

Evaluator judgments are supplied separately:

```json
{
  "case_id": "ma_0010",
  "judgments": [
    {
      "prediction_id": "candidate_1",
      "label": "supplementary",
      "gold_effect_estimate_id": null,
      "reason": "The quoted source supports this supplementary estimand."
    }
  ]
}
```

Labels are `main_hit`, `supplementary`, `strict_violation`, and `neutral_or_uncertain`. A reference hit names a valid reference ID and must satisfy numerical matching. Exact reference matches and their grouped supporting records are resolved by the scorer. Other records require judgments; incomplete adjudication is indicated by `pending_prediction_ids` and `net_score: null`.

```bash
python evaluate_t2.py --submission submission.json --adjudications judgments.json --output results/t2.json
python evaluate_t2.py --submission submission.json --model OPENAI_MODEL_ID --output results/t2.json
python evaluate_t2.py --submission submission.json --validate-only
```

The OpenAI route reads `OPENAI_API_KEY` and an explicitly selected model from `.env`, the environment or `--model`. Its API URL is fixed to the official OpenAI endpoint. Returned judgments are included in the result for reuse.

A case report contains `metrics.reference` (matched/predicted/expected counts and P/R/F1), `reference_ids_matched`, `net_score`, component points and `candidate_scores`. The score is `2H + S − 3V`, where H is unique reference hits, S is the sum of within-source supplementary credits (1, 0.5, 0.25, 0.25, …), and V is source-quoted strict violations.

## T3 analysis submission

```json
{
  "case_id": "ma_0024",
  "task_type": "analysis",
  "predictions": [
    {
      "analysis_id": "primary_dr_detection_sensitivity",
      "selected_candidate_ids": [],
      "pooled_results": []
    }
  ]
}
```

Each analysis ID is unique. A pooled result supplies `pooled_result_id`, `effect` (`effect_type`, `value`, `ci_lower`, `ci_upper`) and `member_candidate_ids`. Use the task's analysis IDs and public candidate IDs. Include declared secondary/subgroup/sensitivity results in the same predictions array. A blocked analysis may be submitted with its status and empty pooled results.

```bash
python evaluate_t3.py --submission submission.json --output results/t3.json
```

Case metrics include `selection`, `selection_by_analysis`, `pooled` and `extensions`; `benchmark_version` identifies the evaluated release. Comparative outputs give submitted/reference direction and CI categories, match flags and numeric delivery status. Noncomparative outputs give absolute percentage-point errors for the estimate and both interval bounds.

## T2/T3 batches

```json
{
  "submissions": [
    {"case_id": "ma_0010", "submission": "submissions/ma_0010.json"},
    {"case_id": "ma_0024", "submission": "submissions/ma_0024.json"}
  ]
}
```

Inline submission objects are also accepted. Alternatively, `--submissions` can name a directory containing one JSON submission per case. A T2 batch judgment file uses `{"cases": [{"case_id": "ma_0010", "judgments": []}]}`.

```bash
python evaluate_t2.py --submissions t2_submissions.json --adjudications t2_judgments.json --output results/t2_batch.json
python evaluate_t3.py --submissions t3_submissions.json --output results/t3_batch.json
```

T2 `summary.reference.micro.recall` uses all 288 targets. `net_score_total` aggregates 22 completely adjudicated submissions; `net_score_observed` and `net_score_cases` describe the completed subset. T3 summaries use 253 selection units, 25 comparative targets, 5 noncomparative targets and 47 extension analyses. Missing cohort cases retain their reference denominators.
