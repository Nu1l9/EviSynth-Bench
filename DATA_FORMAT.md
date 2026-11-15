# Data Format

## Task cohorts

T1/T2/T3/T4 share the same 22 cases, including `ma_0086`. Task rosters are authoritative in `tracks/<task>/manifest.json`. There are 22 distinct case IDs across all four tasks.

| Task | Participant inputs | Evaluator references |
| --- | --- | --- |
| T1 | `cases/<case>/request.json`, with the T1 export projection | `evaluation/gold/<case>/screening.json` |
| T2 | `tracks/t2/cases/<case>/{task,protocol,documents}.json` | `evaluation/gold/<case>/extraction.json` |
| T3 | `tracks/t3/cases/<case>/tasks/analysis_main_outcomes.json` and its listed `inputs/` | `evaluation/t3_gold/<case>/analysis.json` and `candidate_id_map.json` |
| T4 | `cases/<case>/request.json`, including analysis profiles | `evaluation/gold/<case>/{screening,extraction,analysis}.json` |

## Literature and identities

The T1/T4 candidate corpus contains 562 entries: 342 included and 220 excluded. T2 receives those 342 included documents plus 21 supplementary-file placeholders. Document metadata provides `article_id`, `title`, `doi` and relative `paths`; associated study and document IDs link records within a case. Five DOI values are null and can be retrieved by title.

Restore publications at the listed relative paths. Main articles and supplementary materials retain their separate path entries. The public repository supplies bibliographic metadata and structured task data. `screening.json` maps participant document IDs to reference corpus membership. T4 evaluators also accept the source or portable filename declared by that mapping.

## Quantitative extraction references

The 288 T2 targets comprise effect estimates, arm counts, diagnostic cells, continuous summaries, genotype tables, allele-frequency summaries and partial binary records. `report_units` contains either `effect_estimates`, `candidates`, or a direct structured record. Reference IDs are the effect-estimate ID, candidate ID, or article ID for a direct record.

Allele-frequency signatures preserve the two sample sizes and both allele-percentage maps. Partial binary signatures preserve named arms and explicit missing entries alongside reported counts. Numeric signatures retain the source orientation and match within article/target context.

T2 matching uses absolute and relative tolerance **0.01**, with the larger tolerance applied to each scalar. T4 source-numeric matching uses absolute tolerance **1e-8** and relative tolerance **1e-6**. T4 extraction precision uses mapped numeric submissions as its prediction denominator; recall uses all 288 reference targets. T2 reports prediction-count precision alongside reference recall and the independently adjudicated net score.

T2 supplementary evidence and strict violations are represented by evaluator judgments, separate from the participant submission. Judgment records cite `prediction_id`; `main_hit` also identifies a reference target. The numeric matcher validates reference-hit claims. Supplementary and violation credit requires a submitted `source_location.source_quote`; supplementary groups use article, target and source IDs. A pending judgment leaves the affected case's net score pending while reference-recovery metrics are reported.

## Analysis references and units

Standalone T3 contains 1,069 candidate records. Evaluator ID maps join public candidate IDs to reference IDs. The 30 main analyses define 253 selected `(analysis, candidate)` units. T4 defines 253 source-report units across its 30 main analyses and scores selection as a multiset within each analysis.

The `ma_0086` T3 input contains 11 candidate records from two randomized studies, one primary PFAPA episode-rate analysis (IRR) and four declared subgroup levels. Its candidate payload and runtime-to-reference mapping are frozen from the standalone input package. Selection scoring uses the explicit ID map; numerical similarity alone does not establish candidate-ID equivalence.

Pooled references use `pooled_results` with `effect.effect_type`, `value`, `ci_lower` and `ci_upper`. T3 also reports pooled-value accuracy using absolute and relative tolerance 0.01, and composition accuracy using the selected member-ID set.

The 25 comparative targets use their effect scale's null: 1 for RR/OR/HR/IRR and other ratio scales, 0 for MD/SMD/RD. Explicit log-ratio submissions are exponentiated before comparison. Direction categories are above, below or at the null. CI categories are above, below or including the null, with boundaries counted as including it. A valid interval has finite bounds, a lower bound below the upper bound, and contains the submitted point estimate; ratio intervals are positive.

Five noncomparative targets are assessed on the proportion scale: sensitivity and specificity in `ma_0024` and `ma_0028`, and prevalence in `ma_0026`. The `OTHER` scale label in the `ma_0026` reference is interpreted as prevalence for this analysis. Point and interval-bound errors are absolute deviations in percentage points. Missing values are null and the delivered-target count accompanies aggregate means.

## Declared extension analyses

Extension coverage expands the public profiles into 47 IDs: 9 secondary outcomes, 34 subgroup levels and 4 sensitivity levels. A v2 profile supplies `secondary_outcomes` and candidate dimension levels. Other cases use additional entries from `analysis_profile.json`; subgroup levels also come from `analysis_extensions.json`.

Dimension levels use `<kind>_<dimension_id>_<level_id>`. The scorer provides the full expanded roster in its coverage output. The `ma_0001` aliases `primary_any_cv`, `secondary_cv_death`, `secondary_mi` and `secondary_stroke` map to the corresponding `main_pr_*` reference IDs. A declared extension is covered when its mapped result has a finite estimate and valid CI. Coverage is reported overall and by extension category.

## Batch evaluation and missing results

Batch T2/T3 registries accept inline submissions or relative paths. Every cohort case contributes its reference denominator. Missing T1/T4 stage outputs are null in per-case reports; cohort recall and agreement use the full reference cohort. Macro precision, recall and F1 are arithmetic means over all 22 cases, with zero for an empty predicted set. T2 cumulative net score is reported when all 22 case submissions have complete adjudications; the score over completed cases is also reported with its case count.

Use [OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md) for JSON examples and [TASK.md](TASK.md) for participant instructions.
