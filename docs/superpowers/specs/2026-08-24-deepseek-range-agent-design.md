# DeepSeek CSFD Range Selection Agent Design

## 1. Objective

Extend the existing deterministic Craterstats single-dating package with a
terminal-based agent workflow that:

1. accepts an existing CRATER shapefile, its matching AREA shapefile, and the
   source TIFF;
2. generates a global differential CSFD plot without an age fit or diameter
   range;
3. exposes the deterministic workflow capabilities as DeepSeek-callable tools;
4. sends structured pseudo-log CSFD bin data to DeepSeek for up to three
   candidate fitting ranges;
5. pauses for explicit human selection, editing, or cancellation;
6. runs the final buffered-Poisson age fit only after human confirmation; and
7. records every state transition, model interaction, warning, confirmation,
   and generated artifact for reproducibility.

Automatic crater detection and a graphical user interface are explicitly
outside this phase. They will be connected only after this terminal workflow is
accepted.

## 2. Existing Behavior That Must Remain Stable

The existing entry point, `python -m crater_dating_agent`, continues to perform
one deterministic dating run from an already confirmed range. Its current
arguments and output contract remain compatible.

The existing scientific defaults remain:

- body: Moon;
- chronology system: Neukum (1983);
- epochs: Guo et al. (2024);
- presentation: differential;
- binning: pseudo-log;
- fit type: buffered Poisson (`b-poisson`);
- final fit plot symbol: `fo`;
- final global overview: `name=plot 2,type=data,psym=o`, with no range;
- equilibrium function: none.

The Wang Yiran crater-detection code and `csfd_code` source tree are not
modified in this phase.

## 3. Chosen Architecture

Use a lightweight Python state machine and an OpenAI-compatible DeepSeek client.
Do not introduce LangChain or LangGraph. Deterministic operations remain normal
Python services; a small registry publishes selected services as JSON-schema
function tools.

The Python controller, rather than the model, owns workflow ordering. It filters
the registered tools by session state and validates every tool argument and
result. The model cannot authorize a final dating run.

The interactive PyCharm entry point is:

```text
Module name: crater_dating_agent.agent_main
```

## 4. End-to-End Flow

```text
CRATER + AREA + TIFF
  -> validate_case
  -> generate_global_csfd
  -> get_csfd_summary
  -> DeepSeek tool loop and range analysis
  -> validate and snap candidate ranges
  -> awaiting_confirmation
  -> human chooses, edits, or cancels
  -> write confirmation record
  -> run_confirmed_dating
  -> final two-overplot CSFD and age artifacts
```

The initial global Craterstats configuration contains exactly one data
overplot:

```text
source=<CRATER shapefile>,name=plot 2,type=data,binning=pseudo-log,psym=o
```

It contains no `range` and no fit overplot, so it displays no fitted age. Only a
PNG is required from this invocation. Structured bins are generated separately
through Craterstats' own `Cratercount`/`Spatialcount` implementation from the
same CRATER and AREA files. This preserves the engine's pseudo-log boundaries,
buffer fractions, area, and differential-density calculations instead of
duplicating its scientific binning logic.

After confirmation, the existing deterministic single-dating service performs
the final run with exactly two overplots: the confirmed buffered-Poisson fit and
the no-range global `plot 2`.

## 5. Tool Registry

All tool definitions live in one registry with a name, description, JSON Schema,
executor, allowed states, and whether the tool mutates session state.

### `validate_case`

Validates CRATER/AREA naming, shapefile sidecars, TIFF provenance path, case ID,
and positive input crater count. Returns resolved absolute paths and input
metadata.

Allowed state: `created`.

### `generate_global_csfd`

Writes and invokes the one-overplot, no-range Craterstats configuration. Returns
the fresh PNG, configuration, and log paths.

Allowed states: `created`, `inputs_validated`.

### `get_csfd_summary`

Uses Craterstats' pseudo-log binning to return structured values including area,
perimeter, total crater count, complete diameter extent, and for every occupied
bin: lower/upper/mean diameter, weighted count, event count, cumulative count,
differential density, and uncertainty.

Allowed states: `overview_ready`, `analyzing`.

### `get_session_state`

Returns a redacted snapshot of the session phase, artifact paths, warnings, and
confirmation status. It never returns environment variables or secrets.

Allowed states: all states.

### `run_confirmed_dating`

Runs the existing deterministic final dating service using the exact confirmed
range. It independently verifies a valid confirmation record tied to the same
session, input-file metadata, and normalized range.

Allowed state: `confirmed`. The controller does not expose this tool before
confirmation. Direct premature calls fail closed.

## 6. DeepSeek Adapter

Use the official OpenAI-compatible endpoint and SDK conventions:

```text
DEEPSEEK_API_KEY       required; no default
DEEPSEEK_BASE_URL      default https://api.deepseek.com
DEEPSEEK_MODEL         default deepseek-v4-flash
```

The user may override the model with
`deepseek-v4-flash-vision-exp` if it is enabled for their account. The program
does not silently fall back to another model; an unavailable model produces an
actionable error while preserving the resumable session.

The adapter preserves assistant `reasoning_content` across thinking-mode tool
turns as required by DeepSeek. Tool arguments are treated as untrusted input and
validated locally. API keys are read only from the environment and must never
appear in prompts, persisted messages, exception text, or logs.

The first version sends text/JSON CSFD summaries only. The global PNG is for
human inspection and is not uploaded to the model.

## 7. Range Proposal Contract

DeepSeek receives instructions to identify contiguous diameter intervals that
are plausible for production-function fitting while considering small-diameter
incompleteness, sparse large-diameter bins, secondary cratering, resurfacing
features, bin continuity, and statistical uncertainty. It does not calculate or
claim a final age.

It must return JSON with this semantic shape:

```json
{
  "candidates": [
    {
      "range_min_km": 0.06,
      "range_max_km": 0.2,
      "confidence": "high",
      "reason": "A concise evidence-based explanation",
      "risks": ["A specific limitation"]
    }
  ],
  "overall_observation": "A concise description of the global distribution",
  "needs_human_review": true
}
```

There may be one to three candidates. `confidence` is one of `high`, `medium`,
or `low`. Empty candidates are permitted when the model finds no defensible
interval; this must lead to manual input or cancellation rather than an
automatic fit.

After parsing, Python:

1. requires finite positive bounds with maximum greater than minimum;
2. maps proposed bounds to actual pseudo-log bin boundaries;
3. recalculates weighted/event crater counts and occupied-bin counts;
4. deduplicates equivalent normalized ranges;
5. rejects ranges outside the measured diameter extent; and
6. attaches deterministic warnings to each candidate.

The technical defaults are at least 20 crater events and at least three occupied
pseudo-log bins. These are safety defaults, not a claim of universal scientific
validity. They are configuration values. A human may override them only through
a second explicit warning confirmation, which is recorded.

## 8. Human Confirmation and State Machine

Session phases are:

```text
created
inputs_validated
overview_ready
analyzing
awaiting_confirmation
confirmed
completed
cancelled
failed
```

Only declared transitions are allowed. `failed` records the stage and error but
does not erase existing artifacts. Recoverable API failures return the session
to `overview_ready`, allowing analysis to resume without rerunning Craterstats.

At `awaiting_confirmation`, the terminal displays the global PNG path and all
normalized candidates, including event counts, occupied bins, reasons, risks,
and warnings. The human can:

```text
1 / 2 / 3   select a candidate
e           enter a different range
q           cancel the session
```

A selection or manual range is shown again as exact normalized bin boundaries.
The final fit requires an explicit `y` confirmation. If technical thresholds are
not met, a separate warning confirmation is required first.

`confirmation.json` contains session ID, input-file fingerprints, original
choice, normalized range, threshold warnings, confirmation timestamps, and the
confirmation method. It contains no API key and no inferred identity.

## 9. Artifact Layout

```text
outputs/<case_id>/<session_id>/
├── session_state.json
├── overview/
│   ├── <case_id>_global_csfd.png
│   ├── <case_id>_global.cs
│   ├── csfd_summary.json
│   └── craterstats.log
├── llm/
│   ├── tool_transcript.jsonl
│   ├── raw_response.json
│   └── range_candidates.json
├── confirmation.json
└── final/
    ├── <case_id>_csfd.png
    ├── <case_id>_csfd.csv
    ├── <case_id>_age_result.json
    ├── <case_id>_dating.cs
    ├── <case_id>_csfd.log
    └── run_manifest.json
```

Every write uses UTF-8 and atomic replace where practical. Session and
transcript records include schema versions, timezone-aware timestamps, agent and
Craterstats versions, model name, tool schema version, input sizes/modification
times, and paths to newly generated artifacts.

The raw response record stores only the response needed to reproduce parsing.
Persisted reasoning content is limited to the protocol data required for a live
tool-call turn and is not presented as scientific justification. User-facing
justification comes from the model's explicit `reason` and `risks` fields.

## 10. Error Handling

- Missing `DEEPSEEK_API_KEY`: stop before network access with setup instructions;
  preserve any completed overview artifacts.
- Authentication, rate, timeout, or unavailable-model error: record a redacted
  error and keep the session resumable.
- Invalid or hallucinated tool name/arguments: reject locally, return a concise
  tool error to the model, and never execute a guessed alternative.
- Malformed final JSON: allow one constrained repair request, then stop and
  preserve the raw response.
- Craterstats failure: retain configuration, log, and failed state.
- Candidate outside data or with invalid numbers: reject that candidate; never
  coerce NaN or infinity.
- Missing/mismatched confirmation: refuse final dating.
- Cancellation: write `cancelled` state and perform no final fit.

## 11. Testing Strategy

Development follows test-driven development.

### Unit tests

- global configuration has exactly one no-range data overplot;
- structured bins match fixed independent fixtures;
- registry schemas and state-based tool filtering;
- invalid/hallucinated tool calls are rejected;
- range normalization, deduplication, count calculation, and thresholds;
- every legal and illegal state transition;
- confirmation gate, mismatched inputs, warning override, and cancellation;
- DeepSeek message serialization, including reasoning-content replay;
- API errors and secrets are redacted;
- malformed proposal receives exactly one repair attempt.

### SID9 integration tests

Use only the user-provided CRATER, AREA, and TIFF. Run real Craterstats to create
the global plot and summary, but use a fake DeepSeek response. Verify that no
age CSV/JSON exists before confirmation and that the final two-overplot result
exists only after confirmation.

### Optional live test

A separately marked test may call the real DeepSeek API only when explicitly
requested and `DEEPSEEK_API_KEY` is set. It is excluded from the default test
suite and must never print the key.

## 12. Acceptance Criteria

The phase is complete when:

1. the existing deterministic CLI remains green and backward compatible;
2. the interactive PyCharm entry creates a no-age global plot first;
3. DeepSeek receives structured Craterstats-derived pseudo-log data and can call
   only state-allowed registered tools;
4. one to three validated candidates, or a defensible no-candidate result, are
   displayed with deterministic statistics;
5. final dating is impossible before an auditable human confirmation;
6. final output contains both the confirmed fit and the no-range global plot;
7. API/model failures can resume from existing overview artifacts;
8. no secret is written to disk or test output; and
9. all unit and SID9 integration tests pass without requiring a live API call.

## 13. Deferred Work

- automatic crater detection from AREA and TIFF using Wang Yiran's model;
- image upload or multimodal range assessment;
- automated scientific range scoring/search beyond model suggestions;
- graphical desktop or web interface;
- multi-case batch processing.

## 14. External API References

- DeepSeek OpenAI-compatible API guide:
  https://api-docs.deepseek.com/guides/function_calling/
- DeepSeek tool-call guide:
  https://api-docs.deepseek.com/guides/tool_calls/
- DeepSeek thinking-mode/tool-call guide:
  https://api-docs.deepseek.com/guides/thinking_mode/

