# Task Suite

## Objective

EviSynth-Bench evaluates evidence synthesis for medical meta-analysis through four complementary tasks. Participants receive the inputs for one assigned task and submit structured outputs for evaluation against the benchmark references.

## T1 — Literature screening

Screen the candidate documents against the case's population, exposure/intervention, comparator, outcome and study-design criteria. Submit one inclusion or exclusion decision for each candidate document. The 22-case cohort contains 562 entries, of which 342 are reference inclusions and 220 are reference exclusions.

## T2 — Evidence extraction

Extract the requested evidence from the 342 known-included documents and their 21 supplementary-file placeholders. Follow each case's extraction protocol and preserve the source's population, estimand, outcome, follow-up, measurement scale, numerical values and source location.

Provide structured counts, reported effects or summaries in the requested representation. Partial source records retain explicit missing quantities. Cite source quotations for evidence requiring semantic adjudication. Submit the extraction JSON using the case's `submission_template.json` and schema. Evaluation reports recovery of 288 reference targets and the comprehensive extraction net score.

## T3 — Statistical analysis

Use the supplied structured evidence candidates to select eligible evidence and deliver the prespecified main analyses. Explain blocked analyses through their status. Supply pooled estimates, 95% intervals and member candidate IDs for delivered results. Report declared secondary outcomes, subgroup levels and sensitivity analyses with their corresponding analysis IDs.

The cohort contains 1,069 candidate records, 30 reference main analyses and 253 reference selection units. Pooled comparisons comprise 25 comparative and 5 noncomparative analyses. Extension coverage covers the 47 analyses expanded from the supplied profiles.

## T4 — End-to-end evidence synthesis

Starting from the candidate documents and scientific request, perform screening, extraction, evidence selection and synthesis. Preserve document and evidence identities across stages. Submit the screening, extraction and analysis artifacts described in [OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md).

T4 uses the T1/T2 cohort and 30 reference main analyses comprising 253 selected source-report units. Evaluation reports each stage and final pooled conclusions.

## Literature preparation and task isolation

Obtain publications from their DOI/title metadata and restore them at the relative paths in the task's document list. Standalone T3 uses structured evidence directly. Task inputs and evaluator references are distributed separately by `scripts/export_blind.py`; participants should receive their assigned task export.

All four tasks share the same 22 cases, including `ma_0086`. IDs are scoped to their case and task. Consult [DATA_FORMAT.md](DATA_FORMAT.md) for cohort and record definitions, and [OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md) for submission examples.
