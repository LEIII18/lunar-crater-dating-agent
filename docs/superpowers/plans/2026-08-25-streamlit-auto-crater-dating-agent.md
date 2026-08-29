# Streamlit Automatic Crater Dating Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bilingual Streamlit application that validates AREA/CRATER/TIFF inputs, routes empty CRATER files through automatic crater detection, previews raster/vector overlays with optional manual revision, and then runs the existing DeepSeek-assisted Craterstats dating workflow.

**Architecture:** Add a thin orchestration layer around the two already-validated detection scripts and the existing `agent_service`. New focused modules own input validation, isolated task copies, subprocess execution, overlay rendering, workflow state, localization, and Streamlit presentation. The existing detection scripts remain command-line cores and are not refactored.

**Tech Stack:** Python 3.12, Streamlit, Plotly, Rasterio, PyShp, PyProj, Pillow, Matplotlib, ArcGIS 10.8 ArcPy/Python 2.7 subprocess, ONNX detector Python 3.9 subprocess, Craterstats 3.6.7, DeepSeek OpenAI-compatible API, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-streamlit-auto-crater-dating-agent-design-zh.md`

## Global Constraints

- `part1_code/auto_crater_detection_pipeline.py` and `part1_code/run_wangyiran_model_py3.py` are stable cores; do not refactor their detection, projection, field conversion, or append logic.
- The first version continues to require `C:\Python27\ArcGIS10.8\python.exe` and a separate Python 3.9 detector environment.
- Initial filenames must start with exact uppercase prefixes `AREA_` and `CRATER_`; the complete suffix after each prefix must match exactly.
- Never modify the user's original AREA, CRATER, or TIFF.
- Empty CRATER routes to automatic detection; non-empty CRATER skips detection and routes directly to dating.
- User-visible text says “撞击坑自动识别模型” / “automatic crater detection model”; it does not display a person's name.
- Large TIFF files are downsampled only for preview. Vector validation and dating use original data.
- Automatic and manually revised CRATER results remain separate.
- API keys remain in environment/process memory and are never persisted.
- Git initialization, commits, GitHub authentication, and push are deferred until the user approves the completed application.

## File Structure

- Create `crater_dating_agent/workflow_models.py`: immutable input, workspace, route, phase, statistics, and preview data models.
- Create `crater_dating_agent/workflow_inputs.py`: strict validation and case-ID extraction for initial and manual CRATER inputs.
- Create `crater_dating_agent/workflow_workspace.py`: isolated run directory allocation and shapefile sidecar copying.
- Create `crater_dating_agent/pipeline_runner.py`: environment settings, safe subprocess argv, streamed logs, and output validation.
- Create `crater_dating_agent/overlay_preview.py`: TIFF downsampling, CRS transformation, vector overlay, PNG, and Plotly figure generation.
- Create `crater_dating_agent/workflow_service.py`: deterministic empty/non-empty routing and all pre-dating confirmation transitions.
- Create `crater_dating_agent/i18n.py`: fixed Chinese/English UI strings.
- Create `crater_dating_agent/web_app.py`: Streamlit presentation and button actions only.
- Create `.streamlit/config.toml`: local Streamlit defaults without secrets.
- Modify `crater_dating_agent/agent_service.py`: allow preparing the dating session inside an existing workflow directory.
- Modify `crater_dating_agent/session_store.py`: support safe session initialization at a preallocated directory.
- Modify `crater_dating_agent/deepseek_client.py`: request model prose in the selected UI language without changing the candidate JSON schema.
- Modify `pyproject.toml`: add Streamlit, Plotly, and Rasterio runtime dependencies and Streamlit test support.
- Create tests matching each new module plus an end-to-end Streamlit workflow test.

---

### Task 1: Workflow Input Contract and Smart Route

**Files:**
- Create: `crater_dating_agent/workflow_models.py`
- Create: `crater_dating_agent/workflow_inputs.py`
- Test: `tests/test_workflow_inputs.py`

**Interfaces:**
- Produces: `WorkflowRoute(str, Enum)` with `AUTO_DETECT` and `USE_EXISTING`.
- Produces: `WorkflowInputs(case_id: str, area_shp: Path, crater_shp: Path, image_tif: Path, crater_count: int, route: WorkflowRoute)`.
- Produces: `validate_workflow_inputs(area_shp: Path, crater_shp: Path, image_tif: Path) -> WorkflowInputs`.
- Produces: `validate_manual_crater(area_shp: Path, crater_shp: Path, expected_case_id: str) -> int`.

- [ ] **Step 1: Write failing strict-name, empty-route, non-empty-route, schema, geometry, and CRS tests**

```python
def test_empty_crater_routes_to_automatic_detection(valid_empty_files):
    result = validate_workflow_inputs(*valid_empty_files)
    assert result.case_id == "SID9"
    assert result.crater_count == 0
    assert result.route is WorkflowRoute.AUTO_DETECT

def test_nonempty_crater_routes_directly_to_dating(valid_nonempty_files):
    result = validate_workflow_inputs(*valid_nonempty_files)
    assert result.crater_count == 3
    assert result.route is WorkflowRoute.USE_EXISTING

@pytest.mark.parametrize("area_name,crater_name", [
    ("area_SID9.shp", "CRATER_SID9.shp"),
    ("AREA_SID9.shp", "crater_SID9.shp"),
    ("AREA_SID9.shp", "CRATER_SID10.shp"),
])
def test_names_must_have_exact_prefixes_and_matching_suffixes(
    tmp_path, area_name, crater_name
):
    paths = make_valid_pair(tmp_path, area_name, crater_name, crater_count=0)
    with pytest.raises(DatingError, match="AREA_|CRATER_|任务编号"):
        validate_workflow_inputs(*paths)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflow_inputs.py -v`

Expected: collection/import failure because `workflow_inputs` and `workflow_models` do not exist.

- [ ] **Step 3: Implement immutable models and validation**

Use PyShp to require Polygon geometry and exact fields (`Area`, `Area_Name`; `Diam_km`, `x_coord`, `y_coord`, `tag`). Require `.shp`, `.shx`, `.dbf`, and `.prj`. Parse both `.prj` files with `pyproj.CRS.from_wkt` and require `area_crs.equals(crater_crs)`. Derive `case_id` from the exact prefix and choose the route only from the CRATER record count.

```python
class WorkflowRoute(str, Enum):
    AUTO_DETECT = "auto_detect"
    USE_EXISTING = "use_existing"

@dataclass(frozen=True)
class WorkflowInputs:
    case_id: str
    area_shp: Path
    crater_shp: Path
    image_tif: Path
    crater_count: int
    route: WorkflowRoute
```

- [ ] **Step 4: Run focused and existing path-resolver tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflow_inputs.py tests\test_path_resolver.py -v`

Expected: PASS. Existing dating inputs must still reject empty CRATER; only the new pre-dating workflow accepts it.

- [ ] **Step 5: Record checkpoint evidence**

Save the exact pytest command and summary in the implementation progress note. Do not initialize Git.

### Task 2: Isolated Workspace and Sidecar Copying

**Files:**
- Create: `crater_dating_agent/workflow_workspace.py`
- Modify: `crater_dating_agent/workflow_models.py`
- Test: `tests/test_workflow_workspace.py`

**Interfaces:**
- Consumes: `WorkflowInputs` from Task 1.
- Produces: `WorkflowWorkspace(root: Path, source_dir: Path, detection_work_dir: Path, detection_preview_dir: Path, manual_revision_dir: Path, area_shp: Path, crater_shp: Path, image_tif: Path)`.
- Produces: `create_workflow_workspace(inputs: WorkflowInputs, output_root: Path, clock: Callable[[], datetime] | None = None) -> WorkflowWorkspace`.
- Produces: `copy_shapefile_set(source: Path, destination_dir: Path) -> Path` using case-insensitive sidecar discovery for the same stem.

- [ ] **Step 1: Write failing copy/isolation tests**

```python
def test_workspace_copies_area_and_crater_without_touching_sources(valid_empty_inputs, tmp_path):
    original_empty_shp = valid_empty_inputs.crater_shp.read_bytes()
    workspace = create_workflow_workspace(valid_empty_inputs, tmp_path, clock=fixed_clock)
    assert workspace.area_shp.name == "AREA_SID9.shp"
    assert workspace.crater_shp.name == "CRATER_SID9.shp"
    assert workspace.area_shp.parent == workspace.source_dir
    assert workspace.crater_shp.parent == workspace.source_dir
    assert workspace.root == tmp_path / "SID9" / "20260825_120000_000000"
    assert valid_empty_inputs.crater_shp.read_bytes() == original_empty_shp

def test_copy_includes_uppercase_cpg_sidecar(valid_empty_inputs, tmp_path):
    copied = create_workflow_workspace(valid_empty_inputs, tmp_path, clock=fixed_clock)
    assert (copied.source_dir / "CRATER_SID9.CPG").is_file()
```

- [ ] **Step 2: Run and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflow_workspace.py -v`

Expected: FAIL because workspace functions are absent.

- [ ] **Step 3: Implement safe workspace allocation and copying**

Resolve the output root, allocate `outputs/<case>/<timestamp>` without overwriting, create only the documented child directories, reject symlink source components, and copy sidecars with `shutil.copy2`. Keep `image_tif` as a read-only original path.

- [ ] **Step 4: Run workspace and input tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflow_workspace.py tests\test_workflow_inputs.py -v`

Expected: PASS.

- [ ] **Step 5: Record checkpoint evidence without Git changes**

### Task 3: Safe ArcPy/Detector Subprocess Runner

**Files:**
- Create: `crater_dating_agent/pipeline_runner.py`
- Modify: `crater_dating_agent/workflow_models.py`
- Test: `tests/test_pipeline_runner.py`

**Interfaces:**
- Consumes: `WorkflowWorkspace` from Task 2.
- Produces: `DetectionSettings.from_env(environ: Mapping[str, str] | None = None) -> DetectionSettings`.
- Produces: `build_detection_argv(workspace: WorkflowWorkspace, settings: DetectionSettings) -> tuple[str, ...]`.
- Produces: `run_detection(workspace: WorkflowWorkspace, settings: DetectionSettings, on_line: Callable[[str], None] | None = None, popen_factory=subprocess.Popen) -> DetectionRunResult`.

- [ ] **Step 1: Write failing settings and argv tests**

```python
def test_detection_argv_calls_stable_pipeline_with_task_copy(workspace, settings):
    argv = build_detection_argv(workspace, settings)
    assert argv[0] == str(settings.arcpy_python)
    assert argv[1].endswith("part1_code\\auto_crater_detection_pipeline.py")
    assert argv[argv.index("--area-shp") + 1] == str(workspace.area_shp)
    assert argv[argv.index("--target-shp") + 1] == str(workspace.crater_shp)
    assert argv[argv.index("--work-dir") + 1] == str(workspace.detection_work_dir)
    assert argv[argv.index("--model-python") + 1] == str(settings.model_python)
    assert "--overwrite" in argv

def test_runner_never_uses_shell(workspace, settings, fake_popen):
    run_detection(workspace, settings, popen_factory=fake_popen)
    assert fake_popen.kwargs["shell"] is False
```

- [ ] **Step 2: Run and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_pipeline_runner.py -v`

Expected: FAIL because the runner is absent.

- [ ] **Step 3: Implement environment validation, streaming, and redacted logs**

Defaults:

```python
DEFAULT_ARCPY_PYTHON = Path(r"C:\Python27\ArcGIS10.8\python.exe")
DEFAULT_MODEL_PYTHON = Path(r"C:\ProgramData\Anaconda3\envs\crater_model_py39\python.exe")
DEFAULT_MODEL_DIR = PROJECT_ROOT / "wangyiranCode"
```

Use `subprocess.Popen(argv, shell=False, stdout=PIPE, stderr=STDOUT)`. Decode with the Windows preferred encoding and `errors="replace"`. Write `logs/detection.log`. On nonzero exit, raise `DatingError` with the exit code and log path. On success, reread the copied CRATER and require at least one record.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_pipeline_runner.py -v`

Expected: PASS, including missing interpreter/model/weight and nonzero-exit cases.

- [ ] **Step 5: Run the stable script dependency checks without modifying scripts**

Run the Python 3.9 helper with `--version-check` and `--dependency-check`; run the ArcPy pipeline with `--check-only` against the Task 2 workspace copy. Record outputs; do not edit either script.

### Task 4: Downsampled TIFF/AREA/CRATER Overlay Preview

**Files:**
- Modify: `pyproject.toml`
- Create: `crater_dating_agent/overlay_preview.py`
- Modify: `crater_dating_agent/workflow_models.py`
- Test: `tests/test_overlay_preview.py`

**Interfaces:**
- Produces: `OverlayPreview(png_path: Path, figure: plotly.graph_objects.Figure, width: int, height: int)`.
- Produces: `render_overlay_preview(image_tif: Path, area_shp: Path, crater_shp: Path, output_path: Path, case_id: str, max_dimension: int = 1600) -> OverlayPreview`.

- [ ] **Step 1: Add failing tests with a small georeferenced TIFF and polygon shapefiles**

```python
def test_overlay_is_downsampled_and_uses_dynamic_trace_names(geo_fixture, tmp_path):
    preview = render_overlay_preview(
        geo_fixture.tif, geo_fixture.area, geo_fixture.crater,
        tmp_path / "overlay.png", "Saussure_D", max_dimension=512,
    )
    assert preview.png_path.is_file()
    assert max(preview.width, preview.height) <= 512
    assert [trace.name for trace in preview.figure.data] == [
        "AREA_Saussure_D 定年区域", "CRATER_Saussure_D 撞击坑轮廓"
    ]

def test_overlay_transforms_vectors_to_raster_crs(mixed_crs_fixture, tmp_path):
    preview = render_overlay_preview(
        mixed_crs_fixture.tif,
        mixed_crs_fixture.area,
        mixed_crs_fixture.crater,
        tmp_path / "overlay.png",
        "X",
    )
    assert preview.figure.layout.xaxis.range is not None
```

- [ ] **Step 2: Run and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_overlay_preview.py -v`

Expected: import failure before Rasterio/Plotly and module implementation.

- [ ] **Step 3: Add bounded dependencies and install editable project**

Add `streamlit>=1.40,<2`, `rasterio>=1.4,<2`, and `plotly>=6,<7` to runtime dependencies. Install with:

Run: `.\.venv\Scripts\python.exe -m pip install -e ".[test]"`

- [ ] **Step 4: Implement efficient raster windowing and vector overlay**

Read only the AREA bounding window from Rasterio, cap the largest output dimension at 1600, normalize valid bands to an 8-bit preview, and never load the full-resolution TIFF when a smaller window suffices. Transform PyShp geometry from `.prj` CRS to raster CRS when required. Save a PNG and create Plotly traces with pan/zoom and legend toggles.

- [ ] **Step 5: Run overlay tests and inspect the real SID9 preview**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_overlay_preview.py -v`

Then generate `detection_preview/automatic_overlay.png` from the real SID9 files and visually verify AREA boundary and crater positions.

### Task 5: Deterministic Workflow Controller and Existing-Session Bridge

**Files:**
- Create: `crater_dating_agent/workflow_service.py`
- Modify: `crater_dating_agent/workflow_models.py`
- Modify: `crater_dating_agent/session_store.py`
- Modify: `crater_dating_agent/agent_service.py`
- Test: `tests/test_workflow_service.py`
- Modify: `tests/test_session_store.py`
- Modify: `tests/test_agent_service.py`

**Interfaces:**
- Produces: `WorkflowPhase` values `INPUTS_VALIDATED`, `DETECTION_READY`, `DETECTION_REVIEW`, `MANUAL_REVIEW`, `DATING_READY`, `DATING_STARTED`, `FAILED`, `CANCELLED`.
- Produces: `start_workflow(request: WorkflowRequest, settings: DetectionSettings, output_root: Path, clock=None) -> WorkflowState`.
- Produces: `run_automatic_detection(state: WorkflowState, on_line=None) -> WorkflowState`.
- Produces: `accept_automatic_result(state: WorkflowState) -> WorkflowState`.
- Produces: `import_manual_revision(state: WorkflowState, crater_shp: Path) -> WorkflowState`.
- Produces: `accept_manual_revision(state: WorkflowState) -> WorkflowState`.
- Produces: `start_dating_session(state: WorkflowState, clock=None) -> AgentSession`.
- Produces: `create_session_at(inputs: ResolvedInputs, session_dir: Path, clock=None) -> AgentSession`.
- Extends: `prepare_agent_session(request: AgentRequest, *, output_root: Path | None = None, session_dir: Path | None = None, cli_main=None, cratercount_factory: CratercountFactory | None = None, clock=None) -> AgentSession` while retaining existing behavior when `session_dir` is omitted.

- [ ] **Step 1: Write failing route and confirmation-gate tests**

```python
def test_empty_input_waits_for_detection_and_two_possible_confirmations(empty_request, services):
    state = start_workflow(empty_request, services.settings, services.output_root)
    assert state.phase is WorkflowPhase.DETECTION_READY
    detected = run_automatic_detection(state)
    assert detected.phase is WorkflowPhase.DETECTION_REVIEW
    with pytest.raises(DatingError, match="确认"):
        start_dating_session(detected)

def test_nonempty_input_skips_detector_and_is_immediately_dating_ready(nonempty_request, services):
    state = start_workflow(nonempty_request, services.settings, services.output_root)
    assert state.phase is WorkflowPhase.DATING_READY
    assert services.detector_calls == []

def test_manual_revision_does_not_replace_auto_result(detection_review_state, manual_crater):
    revised = import_manual_revision(detection_review_state, manual_crater)
    assert revised.phase is WorkflowPhase.MANUAL_REVIEW
    assert revised.automatic_crater_shp.is_file()
    assert revised.selected_crater_shp != revised.automatic_crater_shp
```

- [ ] **Step 2: Run and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflow_service.py tests\test_session_store.py tests\test_agent_service.py -v`

Expected: new tests fail while old tests remain green.

- [ ] **Step 3: Implement the state machine and atomic `workflow_state.json`**

Persist non-secret paths, phase, route, counts, chosen data source, timestamps, preview paths, and error details. Reject illegal transitions. Keep the API key and Plotly figure out of JSON. Manual validation failure must leave the automatic result selected and the phase unchanged.

- [ ] **Step 4: Implement safe existing-directory session creation**

`create_session_at` must require an existing empty `llm` destination inside the workflow root, create transcript/state atomically, and keep all existing `load_session` trust-root checks. `prepare_agent_session(session_dir=workspace.root)` uses the selected CRATER and copied AREA without allocating a second timestamp directory.

- [ ] **Step 5: Run service, session, and all existing agent tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflow_service.py tests\test_session_store.py tests\test_agent_service.py tests\test_sid9_agent_integration.py -v`

Expected: PASS.

### Task 6: Language-Aware DeepSeek Requests and Fixed UI Localization

**Files:**
- Create: `crater_dating_agent/i18n.py`
- Modify: `crater_dating_agent/deepseek_client.py`
- Modify: `tests/test_deepseek_client.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Produces: `Language(str, Enum)` with `ZH = "zh"` and `EN = "en"`.
- Produces: `tr(key: str, language: Language, **values: object) -> str`.
- Extends: `DeepSeekRangeClient(settings: DeepSeekSettings, *, sdk_client=None, progress_callback: Callable[[str], None] | None = None, response_language: Language = Language.ZH)`.

- [ ] **Step 1: Write failing localization and prompt-language tests**

```python
def test_dynamic_case_values_are_not_translated():
    assert tr("area_legend", Language.EN, case_id="Saussure_D") == (
        "AREA_Saussure_D dating area"
    )

def test_english_client_requests_english_prose_but_same_json_contract(fake_sdk, session):
    client = DeepSeekRangeClient(settings(), sdk_client=fake_sdk, response_language=Language.EN)
    client.analyze(session, registry(), None)
    user_text = fake_sdk.first_user_text()
    assert "Write overall_observation, reason, and risks in English" in user_text
    assert "range_min_km" in fake_sdk.system_prompt()
```

- [ ] **Step 2: Run and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_i18n.py tests\test_deepseek_client.py -v`

- [ ] **Step 3: Implement complete fixed-string catalogs and prompt instruction**

Raise on missing translation keys during tests. Keep the candidate JSON keys unchanged. In Chinese request Chinese prose; in English request English prose. Switching the UI after a completed API request does not resend DeepSeek or rewrite stored responses.

- [ ] **Step 4: Run focused tests and secret scan**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_i18n.py tests\test_deepseek_client.py -v`

Run: `rg -n "sk-[A-Za-z0-9]{16,}|DEEPSEEK_API_KEY\s*=" crater_dating_agent tests docs`

Expected: tests pass and scan finds no credential value.

### Task 7: Functional Streamlit Application

**Files:**
- Create: `crater_dating_agent/web_app.py`
- Create: `.streamlit/config.toml`
- Test: `tests/test_web_app.py`
- Test: `tests/test_web_app_smoke.py`

**Interfaces:**
- Consumes: Tasks 1–6 and existing `analyze_session`, `confirm_candidate`, `confirm_manual_range`, and `complete_confirmed_session`.
- Produces launch command: `.\.venv\Scripts\python.exe -m streamlit run crater_dating_agent\web_app.py`.

- [ ] **Step 1: Write failing Streamlit rendering/state tests**

```python
def test_new_task_page_has_three_paths_and_language_switch(app):
    assert app.text_input(key="area_path")
    assert app.text_input(key="crater_path")
    assert app.text_input(key="tiff_path")
    assert app.button(key="language_zh")
    assert app.button(key="language_en")

def test_manual_path_requires_validate_preview_before_accept(ui_state):
    ui_state.phase = WorkflowPhase.DETECTION_REVIEW
    ui_state.manual_path = r"D:\manual\CRATER_SID9.shp"
    assert not ui_state.can_accept_manual
    ui_state.mark_manual_preview_valid()
    assert ui_state.can_accept_manual
```

- [ ] **Step 2: Run and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_web_app.py -v`

- [ ] **Step 3: Implement the five-stage page with working buttons**

Use `st.session_state` only for UI handles, language, API key, current `WorkflowState`, and current `AgentSession` path. Each button calls exactly one service transition. Render Plotly overlay with pan/zoom and legend toggles. Hide the manual path and validation button until the user selects the unsatisfied branch. Disable accept buttons until their required validation/preview exists.

The page stages are:

1. input validation and smart route;
2. automatic detection only for empty CRATER, with streamed log status;
3. overlay review and optional manual revision/second preview;
4. global CSFD, DeepSeek observation, three candidates, and manual range;
5. confirmed final age and CSFD output.

- [ ] **Step 4: Implement API-key and advanced-settings controls**

Read `DEEPSEEK_API_KEY` first; otherwise use `st.text_input(type="password")`. Never put the key in `WorkflowState`, `st.query_params`, logs, exceptions, or saved JSON. Advanced settings expose interpreter/model paths and use defaults from `DetectionSettings`.

- [ ] **Step 5: Add headless smoke test and run UI tests**

Start Streamlit headlessly on an ephemeral local port, poll `/_stcore/health`, and stop it in `finally`.

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_web_app.py tests\test_web_app_smoke.py -v`

Expected: PASS and health endpoint returns `ok`.

### Task 8: Regression Suite and Real SID9 Checkpoints

**Files:**
- Create: `tests/test_sid9_workflow_integration.py`
- Modify: `README.md` if present, otherwise create `README.md`
- Modify: `pyproject.toml` integration marker description

**Interfaces:**
- Verifies all prior interfaces against real user-provided files.

- [ ] **Step 1: Run the full offline regression suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all old and new non-live tests pass.

- [ ] **Step 2: Run real empty-CRATER SID9 detection**

Inputs:

```text
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\backup\AREA_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\backup\CRATER_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\3M_DOM\63_61E8_08N.tif
```

Verify the originals remain byte-identical, the task copy becomes non-empty, standard fields remain readable, `automatic_overlay.png` is non-empty, and the workflow stops at `DETECTION_REVIEW`.

- [ ] **Step 3: User checkpoint for visual crater review**

Launch Streamlit and ask the user to inspect the real SID9 overlay, counts, language toggle, satisfied branch, and manual-revision validation button. Do not proceed to a live DeepSeek request until the user accepts this checkpoint.

- [ ] **Step 4: Verify non-empty smart route and existing dating pipeline**

Use the detected task-copy CRATER as input. Assert no detector subprocess starts; verify global CSFD, three candidate previews, confirmation, and final output with the existing offline fake range client.

- [ ] **Step 5: User-triggered live DeepSeek end-to-end test**

The user supplies the API key through environment or the password control and clicks the UI action. Verify the global CSFD image plus structured data are sent, three valid candidates appear, manual/candidate confirmation works, and final age files exist. Do not read, print, or persist the key.

- [ ] **Step 6: Write Chinese-first usage and environment documentation**

Document PyCharm and terminal launch, the three input contracts, exact naming, empty/non-empty routing, the two external Python environments, model directory placement, DeepSeek configuration, outputs, manual revision, troubleshooting, and privacy behavior.

- [ ] **Step 7: Final verification before completion claim**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q crater_dating_agent
.\.venv\Scripts\python.exe -m pip check
rg -n "sk-[A-Za-z0-9]{16,}|data:image/png;base64,[A-Za-z0-9+/]{100}" crater_dating_agent tests docs outputs
```

Expected: all tests pass, compile succeeds, dependencies are consistent, and the secret/Base64 persistence scan has no match.

### Task 9: Deferred Git and Private GitHub Publication

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create or modify: `README.md`
- Inspect: third-party license files under `csfd_code` and `wangyiranCode`

**Interfaces:**
- Produces a clean local Git repository and, only after user approval/authentication, a private GitHub repository.

- [ ] **Step 1: Stop and obtain the user's final publication approval**

Show the exact files proposed for inclusion/exclusion and the license findings. Do not initialize Git before this checkpoint because the user explicitly deferred Git organization.

- [ ] **Step 2: Create ignore rules and scan the staged candidate set**

Ignore `.venv/`, `outputs/`, `.pytest_cache/`, `__pycache__/`, `.superpowers/`, `.env`, user test data, ArcPy work products, raw DeepSeek responses, and ONNX weights. Keep `.env.example` with variable names only.

- [ ] **Step 3: Initialize Git and create reviewed local commits**

Run `git init`, inspect `git status --short`, stage only reviewed first-party files and permitted third-party material, scan staged content for secrets/absolute personal paths, then commit cohesive code, tests, and documentation.

- [ ] **Step 4: Install/authenticate GitHub CLI only with user approval**

The user performs browser authentication; no password, token, or OTP enters chat. Confirm `gh auth status` without printing sensitive values.

- [ ] **Step 5: Create and push the private repository**

Use `gh repo create <user-approved-name> --private --source . --remote origin --push` only after the user confirms the repository name and account. Verify remote visibility is private and the default branch is present.
