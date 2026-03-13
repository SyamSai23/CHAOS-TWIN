# Golden Accuracy Evaluation v1

Overall score: **100.00%**

## Overall

- Total checks: 171
- Passed checks: 171
- Failed checks: 0
- Failure kinds: {}

## By Target

- best_target_quality: 100.00% across 6 case(s)
- component_boundaries: 100.00% across 6 case(s)
- infra_detection: 100.00% across 2 case(s)
- request_flow_quality: 100.00% across 3 case(s)
- route_extraction: 100.00% across 10 case(s)
- sequence_quality: 100.00% across 3 case(s)

## Strongest Areas

- route_extraction: 100.00% — This target family is producing a high proportion of correct checks.
- component_boundaries: 100.00% — Top-level boundaries are staying stable across representative repo shapes.
- infra_detection: 100.00% — Datastore and external detection is matching curated expectations consistently.

## Weakest Areas

- No measured target family failed in v1. The current limitation is corpus breadth, not an observed accuracy miss in this baseline.

## Recurring Error Patterns

- No recurring mismatches were observed in the v1 golden set.

## Recommended Next Fixes

- coverage_growth: The current golden set is stable and mostly accurate. Next fix: Expand the corpus with one or two additional manually judged edge cases before AI refinement to keep accuracy pressure high.

## Case Scores

- backend_api_repo: 100.00%
  - route_extraction: 100.00% (7/7)
  - component_boundaries: 100.00% (8/8)
  - infra_detection: 100.00% (1/1)
  - request_flow_quality: 100.00% (14/14)
  - sequence_quality: 100.00% (9/9)
  - best_target_quality: 100.00% (4/4)
- frontend_only_workspace: 100.00%
  - route_extraction: 100.00% (1/1)
  - component_boundaries: 100.00% (7/7)
  - best_target_quality: 100.00% (3/3)
- full_stack_workspace: 100.00%
  - route_extraction: 100.00% (3/3)
  - component_boundaries: 100.00% (11/11)
- python_service_flow: 100.00%
  - route_extraction: 100.00% (4/4)
  - request_flow_quality: 100.00% (11/11)
  - sequence_quality: 100.00% (13/13)
  - best_target_quality: 100.00% (9/9)
- integration_heavy_backend: 100.00%
  - route_extraction: 100.00% (1/1)
  - component_boundaries: 100.00% (3/3)
  - infra_detection: 100.00% (2/2)
  - best_target_quality: 100.00% (6/6)
- mixed_language_monorepo_boundary: 100.00%
  - route_extraction: 100.00% (2/2)
  - component_boundaries: 100.00% (9/9)
- route_false_positive_guard: 100.00%
  - route_extraction: 100.00% (3/3)
  - best_target_quality: 100.00% (5/5)
- degraded_fallback_sequence: 100.00%
  - route_extraction: 100.00% (1/1)
  - sequence_quality: 100.00% (9/9)
- ambiguous_anchor_backend: 100.00%
  - route_extraction: 100.00% (2/2)
  - request_flow_quality: 100.00% (8/8)
  - best_target_quality: 100.00% (13/13)
- sparse_minimal_repo: 100.00%
  - route_extraction: 100.00% (1/1)
  - component_boundaries: 100.00% (1/1)
