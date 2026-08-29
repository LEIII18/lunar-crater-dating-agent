# DeepSeek CSFD Range Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable PyCharm terminal agent that creates a no-age global CSFD plot, lets DeepSeek analyze structured Craterstats bins, requires human confirmation of a candidate range, and only then runs the existing final dating service.

**Architecture:** A deterministic state machine owns workflow order and publishes selected services through a state-filtered JSON-schema tool registry. Craterstats produces both the global plot and its native pseudo-log statistics; an OpenAI-compatible DeepSeek adapter performs tool-call turns and returns validated range candidates, while a confirmation record gates the final existing dating service.

**Tech Stack:** Python 3.12, craterstats 3.6.7, OpenAI Python SDK 3.2.0, PyYAML, dataclasses/enums/pathlib/json, pytest 8.4, real SID9 shapefiles for integration tests.

**Spec:** `docs/superpowers/specs/2026-08-24-deepseek-range-agent-design-zh.md` (canonical Chinese review copy), with `docs/superpowers/specs/2026-08-24-deepseek-range-agent-design.md` as the English reference.

## Global Constraints

- Preserve the behavior and arguments of `python -m crater_dating_agent`.
- Add the interactive entry as `python -m crater_dating_agent.agent_main`.
- Do not modify `wangyiranCode/`, `csfd_code/`, or crater-detection behavior.
- First-stage global configuration has exactly one `type=data` pseudo-log overplot with `name=plot 2`, `psym=o`, and no `range` or age fit.
- PNG files are visible to the user but are never sent to DeepSeek in this phase.
- Structured bins must come from Craterstats 3.6.7 `Cratercount`/`Spatialcount`, not a duplicated binning implementation.
- Default model is `deepseek-v4-flash`; `DEEPSEEK_MODEL` may override it without silent fallback.
- Read the API key only from `DEEPSEEK_API_KEY`; never persist or print it.
- Candidate defaults are at least 20 crater events and at least three occupied pseudo-log bins; an explicit second confirmation may override warnings.
- Final dating is impossible without a matching persisted human confirmation.
- Default tests never call the live DeepSeek API.
- This workspace is not a Git repository. Replace commit steps with file-scope inspection and green-test checkpoints; do not initialize Git.

---

## File Structure

- Modify `pyproject.toml`: pin OpenAI SDK and package prompt/config resources.
- Create `crater_dating_agent/agent_models.py`: phases, session, bins, candidates, confirmation, and agent result types.
- Create `crater_dating_agent/session_store.py`: atomic session/transcript persistence and legal transitions.
- Create `crater_dating_agent/overview.py`: global-only configuration, Craterstats invocation, and native bin extraction.
- Create `crater_dating_agent/range_candidates.py`: proposal parsing, bin-boundary normalization, statistics, warnings, and deduplication.
- Create `crater_dating_agent/tool_registry.py`: JSON-schema registration, state filtering, argument validation, and guarded execution.
- Create `crater_dating_agent/deepseek_client.py`: environment configuration, message/tool loop, reasoning-content replay, redaction, and proposal repair.
- Create `crater_dating_agent/configs/range_agent.yaml`: schema version, thresholds, model defaults, and retry limit.
- Create `crater_dating_agent/prompts/range_selector.txt`: versioned range-analysis system instructions.
- Create `crater_dating_agent/confirmation.py`: confirmation creation and independent final-gate verification.
- Create `crater_dating_agent/agent_service.py`: complete resumable orchestration.
- Create `crater_dating_agent/agent_main.py`: PyCharm terminal arguments and human interaction.
- Create focused tests under `tests/` plus `tests/fixtures/deepseek_range_response.json`.

---

### Task 1: Agent Domain Models and Atomic Session State

**Files:**
- Create: `crater_dating_agent/agent_models.py`
- Create: `crater_dating_agent/session_store.py`
- Create: `tests/test_session_store.py`

**Interfaces:**
- Produces: `SessionPhase`, `AgentRequest`, `GlobalOverview`, `CsfdBin`, `CsfdSummary`, `RawRangeCandidate`, `RangeProposal`, `ValidatedRangeCandidate`, `HumanConfirmation`, `AgentSession`.
- Produces: `create_session(inputs, output_root, clock=None) -> AgentSession`, `load_session(path) -> AgentSession`, `save_session(session) -> None`, `transition(session, target, *, error=None) -> AgentSession`, `append_transcript(session, event) -> None`.
- Consumes: existing `ResolvedInputs` and `DatingError`.

- [ ] **Step 1: Write failing state and persistence tests**

```python
def test_session_is_atomic_and_timezone_aware(resolved_inputs, tmp_path):
    session = create_session(resolved_inputs, tmp_path,
        clock=lambda: datetime(2026, 8, 24, 21, 0).astimezone())
    loaded = load_session(session.state_path)
    assert loaded.phase is SessionPhase.CREATED
    assert loaded.session_id == "20260824_210000_000000"
    assert loaded.started_at.utcoffset() is not None
    assert not session.state_path.with_suffix(".tmp").exists()

def test_illegal_transition_fails_closed(session):
    with pytest.raises(DatingError, match="非法状态转换"):
        transition(session, SessionPhase.COMPLETED)
```

Also assert collision suffix `_01`, JSON `schema_version == 1`, valid transitions, cancellation, failed error metadata, and JSONL transcript append.

- [ ] **Step 2: Run the tests and verify RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_session_store.py -v`

Expected: collection fails because `agent_models` and `session_store` do not exist.

- [ ] **Step 3: Implement immutable models and explicit transition table**

Use these exact phases:

```python
class SessionPhase(str, Enum):
    CREATED = "created"
    INPUTS_VALIDATED = "inputs_validated"
    OVERVIEW_READY = "overview_ready"
    ANALYZING = "analyzing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

Define `AgentRequest` with `crater_shp: Path`, `area_shp: Path`,
`image_tif: Path`, and optional `output_dir: Path | None`; unlike
`DatingRequest`, it intentionally has no range. `GlobalOverview` owns the PNG,
configuration, log, and summary paths. `RangeProposal` owns zero to three raw
candidates plus `overall_observation` and `needs_human_review`.

Persist through `<name>.tmp` followed by `Path.replace()`. Serialize paths and enums explicitly; reject unknown schema versions and timezone-naive stored timestamps.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command. Expected: all session tests pass.

- [ ] **Step 5: Inspect the checkpoint**

Run: `rg -n "DEEPSEEK_API_KEY|sk-" crater_dating_agent/agent_models.py crater_dating_agent/session_store.py tests/test_session_store.py`

Expected: no secret or secret-shaped literal.

---

### Task 2: Global No-Age CSFD Plot

**Files:**
- Create: `crater_dating_agent/overview.py`
- Create: `tests/test_overview.py`
- Modify: `crater_dating_agent/craterstats_wrapper.py`

**Interfaces:**
- Produces: `render_global_cs(inputs, output_stem, config=None) -> str`.
- Produces: `generate_global_overview(inputs, overview_dir, *, cli_main=None) -> GlobalOverview`.
- Modify wrapper to support `required_formats: tuple[str, ...] = ("png", "csv")` while preserving existing callers.

- [ ] **Step 1: Write failing configuration and invocation tests**

```python
def test_global_config_has_one_unrestricted_data_plot(inputs, tmp_path):
    args = shlex.split(render_global_cs(inputs, tmp_path / "SID9_global_csfd"))
    plots = [args[i + 1] for i, value in enumerate(args) if value == "-p"]
    assert len(plots) == 1
    assert "name=plot 2" in plots[0]
    assert "type=data" in plots[0]
    assert "binning=pseudo-log" in plots[0]
    assert "psym=o" in plots[0]
    assert "range=" not in plots[0]
    assert "b-poisson" not in plots[0]
```

The fake CLI writes PNG only. Assert success does not require CSV, cwd is restored, and the returned config/log/PNG paths are fresh files.

- [ ] **Step 2: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_overview.py tests/test_craterstats_wrapper.py -v`

Expected: import failure for `overview`.

- [ ] **Step 3: Implement the minimal global renderer and reusable wrapper contract**

Render `-f png` and exactly one quoted overplot. In the wrapper, derive and verify only the requested suffixes; keep the default PNG+CSV behavior unchanged for final dating.

- [ ] **Step 4: Run GREEN and regression tests**

Run the Task 2 command. Expected: overview and all prior wrapper tests pass.

- [ ] **Step 5: Confirm no image-to-model code exists**

Run: `rg -n "base64|image_url|data:image" crater_dating_agent tests`

Expected: no match in agent implementation.

---

### Task 3: Craterstats-Native Structured CSFD Summary

**Files:**
- Modify: `crater_dating_agent/overview.py`
- Create: `tests/test_csfd_summary.py`

**Interfaces:**
- Produces: `extract_csfd_summary(inputs, *, cratercount_factory=None) -> CsfdSummary`.
- `CsfdSummary.bins` contains occupied bins only, ordered by increasing diameter.

- [ ] **Step 1: Write failing tests with an independent fake Cratercount object**

Provide literal arrays for `d_min`, `d_max`, `d_mean`, `n`, `n_event`, `ncum`, `bin_width`, area `10.0`, and perimeter `4.0`. Assert differential density is `n / bin_width / area`, uncertainty is density divided by `sqrt(n_event)`, and zero-count bins are omitted.

```python
assert summary.bins[0].d_min_km == pytest.approx(0.06)
assert summary.bins[0].event_count == 21
assert summary.bins[0].differential_density == pytest.approx(525.0)
assert summary.total_event_count == 63
```

Add rejection tests for non-finite values, zero area, mismatched array lengths, and no occupied bins.

- [ ] **Step 2: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_csfd_summary.py -v`

Expected: missing `extract_csfd_summary`.

- [ ] **Step 3: Implement using Craterstats itself**

Default factory must call:

```python
count = craterstats.Cratercount(str(inputs.crater_shp), str(inputs.area_shp))
count.apply_binning("pseudo-log")
```

Read values from `count.binned`, validate all scientific numbers, and write `csfd_summary.json` through the overview service.

- [ ] **Step 4: Run GREEN**

Run the Task 3 command. Expected: all summary tests pass.

- [ ] **Step 5: Run prior suite**

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all existing deterministic tests plus Tasks 1–3 pass.

---

### Task 4: Candidate Parsing, Normalization, and Threshold Warnings

**Files:**
- Create: `crater_dating_agent/range_candidates.py`
- Create: `crater_dating_agent/configs/range_agent.yaml`
- Create: `tests/fixtures/deepseek_range_response.json`
- Create: `tests/test_range_candidates.py`
- Modify: `pyproject.toml` package-data list to include prompts/configs.

**Interfaces:**
- Produces: `load_agent_config() -> RangeAgentConfig`.
- Produces: `parse_proposal_json(text) -> RangeProposal`.
- Produces: `validate_candidates(proposal, summary, config) -> tuple[ValidatedRangeCandidate, ...]`.

- [ ] **Step 1: Create fixed proposal fixture and failing tests**

Use candidates `[0.061, 0.198]`, `[0.06, 0.20]`, and `[0.4, 0.5]`. Assert the first two normalize to the same bin-boundary range and are deduplicated. Assert event/occupied-bin counts are computed from `CsfdSummary`, not accepted from model text.

Add cases for NaN/Infinity, negative/reversed bounds, outside extent, more than three candidates, invalid confidence, empty candidates, fewer than 20 events, and fewer than three occupied bins.

- [ ] **Step 2: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_range_candidates.py -v`

Expected: missing module.

- [ ] **Step 3: Add exact versioned configuration**

```yaml
schema_version: 1
default_model: deepseek-v4-flash
default_base_url: https://api.deepseek.com
min_event_count: 20
min_occupied_bins: 3
proposal_repair_attempts: 1
```

- [ ] **Step 4: Implement strict parser and deterministic normalization**

Use `json.loads`, reject booleans as numbers, require `needs_human_review is True`, and map lower/upper values to enclosing real bin boundaries. Warning codes are exactly `LOW_EVENT_COUNT` and `LOW_OCCUPIED_BINS`.

- [ ] **Step 5: Run GREEN and package-resource test**

Run the Task 4 command, then run `& '.\.venv\Scripts\python.exe' -c "from crater_dating_agent.range_candidates import load_agent_config; print(load_agent_config())"`.

Expected: tests pass and configuration loads from the editable package.

---

### Task 5: State-Filtered Tool Registry and Final-Run Gate

**Files:**
- Create: `crater_dating_agent/tool_registry.py`
- Create: `crater_dating_agent/confirmation.py`
- Create: `tests/test_tool_registry.py`
- Create: `tests/test_confirmation.py`

**Interfaces:**
- Produces: `ToolDefinition`, `ToolContext(session, inputs, services)`, `ToolRegistry.register()`, `schemas_for(phase)`, `execute(name, arguments, context)`.
- Produces: `write_confirmation(session, candidate, method, *, warning_override, clock=None) -> HumanConfirmation`.
- Produces: `verify_confirmation(session, inputs, requested_range) -> HumanConfirmation`.

- [ ] **Step 1: Write failing registry tests**

Register all five exact names. Assert `run_confirmed_dating` is absent before `CONFIRMED`, present at `CONFIRMED`, unknown tools fail, missing/additional/wrong-type arguments fail before executor invocation, and executor exceptions become redacted tool errors.

- [ ] **Step 2: Write failing confirmation tests**

```python
def test_final_gate_rejects_unconfirmed_session(session, inputs):
    with pytest.raises(DatingError, match="尚未人工确认"):
        verify_confirmation(session, inputs, (0.06, 0.2))
```

Also test matching confirmation, changed input size/mtime, changed range, wrong session ID, normal confirmation, warning override requiring a separate affirmative flag, and cancellation.

- [ ] **Step 3: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_tool_registry.py tests/test_confirmation.py -v`

Expected: both modules missing.

- [ ] **Step 4: Implement registry validation and independent confirmation fingerprints**

Use a deliberately small JSON-Schema subset: object, properties, required, additionalProperties=false, string/number/boolean. Fingerprints contain resolved path, size, and `modified_ns`; never accept a model-supplied confirmation flag.

- [ ] **Step 5: Run GREEN**

Run the Task 5 command. Expected: all registry and confirmation tests pass.

---

### Task 6: DeepSeek Tool-Calling Adapter and Proposal Repair

**Files:**
- Modify: `pyproject.toml` to add `openai==3.2.0`
- Create: `crater_dating_agent/deepseek_client.py`
- Create: `crater_dating_agent/prompts/range_selector.txt`
- Create: `tests/test_deepseek_client.py`

**Interfaces:**
- Produces: `DeepSeekSettings.from_env(environ=None) -> DeepSeekSettings`.
- Produces: `DeepSeekRangeClient.analyze(session, registry, context) -> RangeProposal`.
- Client constructor accepts `sdk_client` for tests; production creates `OpenAI(api_key=..., base_url=...)`.

- [ ] **Step 1: Write failing environment and secret-redaction tests**

Assert missing key raises before constructing the SDK client; defaults are official base URL and `deepseek-v4-flash`; model override is preserved; serialized session/transcript never contains the supplied literal fake key.

- [ ] **Step 2: Write failing multi-turn tool tests**

Use fake SDK responses: first assistant calls `get_csfd_summary` with `reasoning_content="protocol-token"`; second returns proposal JSON. Assert the second request includes the assistant tool call, its non-null content, the same reasoning content, and the tool result with matching `tool_call_id`.

Add tests for multiple tool calls, disallowed tool, malformed arguments, API exception redaction, unavailable model without fallback, and exactly one malformed-JSON repair request.

- [ ] **Step 3: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_deepseek_client.py -v`

Expected: missing module/dependency.

- [ ] **Step 4: Install pinned SDK and verify dependency state**

Run: `& '.\.venv\Scripts\python.exe' -m pip install -e '.[test]'`

Expected: OpenAI SDK 3.2.0 installs and `pip check` reports no broken requirements.

- [ ] **Step 5: Implement prompt and adapter**

The prompt explicitly says images are unavailable, age must not be calculated, tools cannot authorize confirmation, all numerical claims must cite supplied bins, and final content must match the proposal contract. Pass state-allowed tool schemas only. Persist redacted API metadata and tool transcript events.

- [ ] **Step 6: Run GREEN**

Run the Task 6 test command. Expected: all fake-client tests pass without network access.

---

### Task 7: Resumable Agent Service

**Files:**
- Create: `crater_dating_agent/agent_service.py`
- Create: `tests/test_agent_service.py`

**Interfaces:**
- Produces: `prepare_agent_session(request: AgentRequest, *, output_root=None, cli_main=None, clock=None) -> AgentSession`.
- Produces: `analyze_session(session_path, *, client=None) -> AgentSession`.
- Produces: `confirm_candidate(session_path, selection, *, manual_range=None, warning_override=False, clock=None) -> AgentSession`.
- Produces: `complete_confirmed_session(session_path, *, cli_main=None, clock=None) -> AgentSession`.

- [ ] **Step 1: Write failing end-to-end service test with real filesystem and fake external boundaries**

Assert prepare validates inputs, creates global PNG and summary, but no final CSV/age JSON. Fake model returns two candidates; analyze enters `AWAITING_CONFIRMATION`. Confirm selection 1 writes confirmation. Complete invokes existing `run_single_dating`, places outputs under `final/`, and enters `COMPLETED`.

- [ ] **Step 2: Add failure/resume tests**

Assert API timeout returns to `OVERVIEW_READY` and reuses unchanged overview PNG; cancellation never invokes final service; a final service call before confirmation fails; changed input metadata invalidates confirmation; and repeated completion does not create a second age result.

- [ ] **Step 3: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_agent_service.py -v`

Expected: missing module.

- [ ] **Step 4: Implement orchestration by composing prior tasks**

Do not place scientific calculations in the service. Each state transition is persisted immediately. Register the five tool executors through closures bound to the current session context. The final executor calls `verify_confirmation` immediately before the existing `run_single_dating`.

- [ ] **Step 5: Run GREEN and full regression suite**

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all old and new non-live tests pass.

---

### Task 8: PyCharm Terminal Interaction

**Files:**
- Create: `crater_dating_agent/agent_main.py`
- Create: `tests/test_agent_main.py`

**Interfaces:**
- Produces: `main(argv=None, *, input_fn=input, output_fn=print, services=None) -> int`.
- Required CLI arguments: `--crater-shp`, `--area-shp`, `--image-tif`; optional: `--output-dir`, `--resume-session`.

- [ ] **Step 1: Write failing terminal tests**

Drive the CLI with iterator-backed `input_fn`. Test selection `1` then `y`, manual `e` with two numeric bounds then `y`, `q` cancellation, invalid selection retry, low-threshold candidate requiring the extra warning confirmation, and missing API key error code 2.

```python
answers = iter(["1", "y"])
code = main(argv, input_fn=lambda _: next(answers), services=fakes)
assert code == 0
assert "最终定年完成" in rendered_output
```

- [ ] **Step 2: Run RED**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_agent_main.py -v`

Expected: missing module.

- [ ] **Step 3: Implement concise Chinese terminal UI**

Print stage numbers, global PNG path, normalized candidate ranges, model reasons/risks, deterministic counts/warnings, and final artifact paths. Never print raw reasoning content, full API responses, or environment variables. `--resume-session` skips input regeneration and resumes from the persisted legal phase.

- [ ] **Step 4: Run GREEN and real help command**

Run the Task 8 tests, then:

`& '.\.venv\Scripts\python.exe' -m crater_dating_agent.agent_main --help`

Expected: exit 0 and all input/resume options are documented.

---

### Task 9: Real SID9 Acceptance Without Live API

**Files:**
- Create: `tests/test_sid9_agent_integration.py`
- Output only: `outputs/SID9/<new-session-id>/`.

**Interfaces:**
- Consumes the three exact user-provided SID9 inputs and a fake DeepSeek client.
- Produces fresh global and final artifacts through public agent services.

- [ ] **Step 1: Write the SID9 integration test**

Use only:

```text
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\CRATER_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\AREA_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\3M_DOM\63_61E8_08N.tif
```

The fake model proposes `0.06–0.2 km`. Assert input count 1545, global PNG exists before confirmation, no final age exists before confirmation, summary bins are finite and ordered, confirmation records the normalized range, and final result has a positive age with two correct overplots.

- [ ] **Step 2: Run the integration test and fix only concrete boundary regressions through RED→GREEN**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_sid9_agent_integration.py -v -m integration`

Expected: PASS after any narrowly tested Craterstats boundary corrections.

- [ ] **Step 3: Run a public terminal rehearsal with fake DeepSeek**

Provide a test-only injected client through the service test harness, not an environment switch in production. Confirm the global plot visually contains hollow global data and no age annotation; after confirmation, confirm the final plot contains the 60–200 m fit plus global plot 2.

- [ ] **Step 4: Run complete verification**

Run these independently and inspect every exit code:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -v
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m compileall -q crater_dating_agent
& '.\.venv\Scripts\python.exe' -m crater_dating_agent --help
& '.\.venv\Scripts\python.exe' -m crater_dating_agent.agent_main --help
```

Expected: all tests pass, no broken dependencies, compilation succeeds, and both old and new CLIs exit 0.

- [ ] **Step 5: Perform security and scope scans**

Run:

```powershell
rg -n "sk-[A-Za-z0-9]{10,}|DEEPSEEK_API_KEY\s*=" . -g '!\.venv/**' -g '!outputs/**'
rg -n "base64|image_url|data:image" crater_dating_agent tests
```

Expected: no embedded API key and no code that uploads the PNG. Confirm `wangyiranCode/` and `csfd_code/` were not modified.

- [ ] **Step 6: Optional live DeepSeek smoke test only after explicit user authorization**

With a newly rotated key set only in the PyCharm environment, run one separately marked `live_api` test. Verify tool calls and one proposal response, then report token usage if returned. This step is skipped unless the user explicitly requests it; all acceptance criteria are already testable without it.
