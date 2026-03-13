Golden-set accuracy evaluation

Purpose
- This corpus measures output correctness for product-defining CHAOS-TWIN outputs.
- It is intentionally smaller and more manually judged than the broad backend stability matrix.
- It is designed for regression tracking before, during, and after later AI refinement work.

Primary evaluator
- Run `scripts/evaluate_golden_accuracy.py`.
- The evaluator reads `scripts/golden_set/corpus.v1.json`, materializes any generated fixtures, runs the real scan/route/sequence pipeline, compares outputs, and emits a reusable report.

Recommended usage
- JSON report:
  `/Users/syamsaichippala/Projects/chaos-twin/backend/.venv/bin/python scripts/evaluate_golden_accuracy.py --json-output docs/evaluation/golden_accuracy_v1_baseline.json`
- Markdown report:
  `/Users/syamsaichippala/Projects/chaos-twin/backend/.venv/bin/python scripts/evaluate_golden_accuracy.py --markdown-output docs/evaluation/golden_accuracy_v1_baseline.md`

Corpus structure
- `version`: corpus version string.
- `cases[]`: representative golden cases.

Case fields
- `id`: stable case identifier.
- `repo_shape`: human-readable repo category.
- `source`: where the evaluator should load the repo from.
  - `kind: workspace` with a repo-relative `path`.
  - `kind: generated` with a named `fixture` builder.
- `notes`: optional human guidance.
- `targets`: expected judgments for specific output families.

Supported target families in v1
- `route_extraction`
  - `min_total` or `exact_total`
  - `expected_routes[]`
  - `forbidden_routes[]`
- `component_boundaries`
  - `exact_total`
  - `expected_components[]`
- `infra_detection`
  - `components[]`
  - Each component locator can use `name`, `index`, or `exact_empty`
  - Each entity can assert `must_be_present`, `kind`, and `entity_type`
- `request_flow_quality`
  - `routes[]`
  - Each route can assert stage ordering, required stages, confidence floor, and inferred-step ceiling
- `sequence_quality`
  - `routes[]`
  - Each route can assert `expected_sequence_source`, `expected_degraded`, required participants, required message labels, required warning substrings, and a minimum count of anchored messages
  - Use `route` for scanned routes or `route_body` to exercise a manual route payload
  - Use `stored_route_analysis` when you intentionally want to test `route_analysis_fallback` without deterministic `request_flow`
- `best_target_quality`
  - `component_targets[]`
  - `route_targets[]`
  - `infra_targets[]`
  - `request_flow_stage_targets[]`
  - Best-target expectations can also assert `expected_symbol` for symbol-sensitive anchor cases

Scoring model
- The evaluator uses pragmatic check-based scoring, not academic benchmark scoring.
- Each target contributes a set of explicit checks.
- Each check is labeled as either:
  - `accuracy`
  - `product_semantics`
- Reports aggregate by:
  - overall score
  - per-target score
  - recurring mismatch patterns
  - strongest areas
  - weakest areas
  - recommended next fixes

Design rules
- Prefer representative manual truth over large synthetic breadth.
- Use partial or graded expectations where exactness would be misleading.
- Keep the corpus stable enough to compare regressions over time.
- Add new cases only when they sharpen product-quality signal.
- Keep at least one judged case for each known failure mode that would materially damage product trust.