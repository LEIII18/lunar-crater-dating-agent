# Craterstats Single Dating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Python tool that validates the three SID9 inputs, creates the two-overplot Craterstats configuration, runs one buffered-Poisson dating calculation without the GUI, and writes reproducible PNG, CSV, JSON, log, and manifest outputs.

**Architecture:** A small `crater_dating_agent` package separates path/data validation, configuration rendering, the Craterstats CLI boundary, CSV parsing, orchestration, and the user-facing CLI. Craterstats remains an external scientific engine invoked through `craterstats.cli.main(argv)`; all new logic is testable without GUI automation or an LLM.

**Tech Stack:** Python 3.12, standard-library dataclasses/pathlib/csv/json, PyYAML, pytest, official `craterstats` Python package.

**Spec:** `docs/superpowers/specs/2026-08-24-craterstats-single-dating-design.md`

## Global Constraints

- Do not modify `run_crater_detection_model_py3.py` or any detection/model behavior.
- The only permitted change in `auto_crater_detection_pipeline.py` is replacing `DEFAULT_MODEL_DIR` with `E:\DiHuaSuo\2026\paper\csfd_agent\agent_build\crater_detect_model`.
- Do not modify files under `crater_detect_model/` or `csfd_code/`.
- Do not launch or automate CraterstatsGUI; call `craterstats.cli.main(argv)` from Python.
- Only the three user-specified SID9 paths are real integration-test inputs; historical `.cs`, `.csv`, and `.png` files in that directory must not be read as fixtures or expected results.
- Overplot 1 is buffered-Poisson with the requested range and `psym=fo`; overplot 2 is `name=plot 2,type=data,binning=pseudo-log,psym=o` and has no range.
- Scientific defaults are Moon, Neukum (1983), Guo et al (2024), differential, no equilibrium, and pseudo-log binning.
- API keys and LLM integrations are outside this plan.
- The workspace root is not a Git repository, so implementation checkpoints are test runs and diff reviews rather than commits.

---

## File Structure

- Create `pyproject.toml`: package metadata, runtime/test dependencies, pytest settings.
- Create `crater_dating_agent/__init__.py`: public package version and exports.
- Create `crater_dating_agent/__main__.py`: `python -m crater_dating_agent` entry.
- Create `crater_dating_agent/models.py`: immutable request, input, invocation, and result dataclasses plus domain error.
- Create `crater_dating_agent/path_resolver.py`: sidecar checks, DBF record count, case-ID derivation, three-input validation.
- Create `crater_dating_agent/config_generator.py`: load scientific defaults and render `.cs` text.
- Create `crater_dating_agent/configs/moon_neukum.yaml`: versioned scientific defaults.
- Create `crater_dating_agent/craterstats_wrapper.py`: controlled direct call to `craterstats.cli.main` and output verification.
- Create `crater_dating_agent/result_parser.py`: parse the newly generated Craterstats CSV into typed age values.
- Create `crater_dating_agent/service.py`: compose validation, config, invocation, parsing, JSON, and manifest writing.
- Create `crater_dating_agent/main.py`: argparse interface and exit-code/error presentation.
- Create `tests/fixtures/craterstats_minimal.csv`: hand-written CSV with independently chosen values for parser tests.
- Create `tests/test_path_resolver.py`, `tests/test_config_generator.py`, `tests/test_craterstats_wrapper.py`, `tests/test_result_parser.py`, `tests/test_service.py`, `tests/test_cli.py`.
- Modify `part1_code/auto_crater_detection_pipeline.py`: update only `DEFAULT_MODEL_DIR`.

---

### Task 1: Package Setup, Domain Models, and Input Validation

**Files:**
- Create: `pyproject.toml`
- Create: `crater_dating_agent/__init__.py`
- Create: `crater_dating_agent/models.py`
- Create: `crater_dating_agent/path_resolver.py`
- Create: `tests/test_path_resolver.py`
- Modify: `part1_code/auto_crater_detection_pipeline.py:40`

**Interfaces:**
- Produces: `DatingError`, `DatingRequest`, `ResolvedInputs`, `resolve_inputs(request) -> ResolvedInputs`, `read_dbf_record_count(path) -> int`.
- Consumes: standard-library `pathlib`, `dataclasses`, and `struct` only.

- [ ] **Step 1: Create package metadata and the failing validation tests**

Create `pyproject.toml` with:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "crater-dating-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "PyYAML>=6.0,<7",
]

[project.optional-dependencies]
test = ["pytest>=8,<9"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Write tests using temporary real sidecar files. The primary success test creates `CRATER_SID9.shp/.shx/.dbf/.prj`, `AREA_SID9.shp/.shx/.dbf/.prj`, and `63_61E8_08N.tif`; the DBF helper writes a valid 32-byte header with a literal record count. Assert `case_id == "SID9"`, all returned paths are resolved absolute paths, and `crater_count` equals the literal header count. Add separate tests for missing AREA sidecar, mismatched AREA name, missing TIFF, zero CRATER records, `range_min <= 0`, and `range_max <= range_min`.

Example behavioral assertion:

```python
request = DatingRequest(
    crater_shp=crater,
    area_shp=area,
    image_tif=image,
    range_min_km=0.06,
    range_max_km=0.2,
)
resolved = resolve_inputs(request)
assert resolved.case_id == "SID9"
assert resolved.crater_count == 63
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_path_resolver.py -v
```

Expected: collection fails because `crater_dating_agent.models` and `path_resolver` do not exist.

- [ ] **Step 3: Implement the minimal domain models and resolver**

Implement immutable dataclasses with these exact fields:

```python
class DatingError(RuntimeError):
    pass

@dataclass(frozen=True)
class DatingRequest:
    crater_shp: Path
    area_shp: Path
    image_tif: Path
    range_min_km: float
    range_max_km: float
    output_dir: Path | None = None

@dataclass(frozen=True)
class ResolvedInputs:
    case_id: str
    crater_shp: Path
    area_shp: Path
    image_tif: Path
    crater_count: int
```

`read_dbf_record_count` must read bytes 4–7 as an unsigned little-endian integer and reject headers shorter than 32 bytes. `resolve_inputs` must verify the filename relationship, `.shp/.shx/.dbf/.prj` sidecars, TIFF suffix, range boundaries, and positive crater count before returning `ResolvedInputs`.

- [ ] **Step 4: Run the resolver tests and verify GREEN**

Run the same pytest command. Expected: all `test_path_resolver.py` tests pass with no warnings.

- [ ] **Step 5: Update the model path without changing detection behavior**

Change only the `DEFAULT_MODEL_DIR` literal in `part1_code/auto_crater_detection_pipeline.py` to:

```python
DEFAULT_MODEL_DIR = u"E:\\DiHuaSuo\\2026\\paper\\csfd_agent\\agent_build\\crater_detect_model"
```

Run:

```powershell
rg -n "DEFAULT_MODEL_DIR|crater_detect_model" part1_code/auto_crater_detection_pipeline.py
```

Expected: the new E-drive path appears in the constant and existing argument wiring remains unchanged.

- [ ] **Step 6: Review the task diff checkpoint**

Run `git diff --no-index NUL pyproject.toml` only as a readable new-file view if useful, then inspect `Get-ChildItem crater_dating_agent,tests`. Do not initialize Git or alter unrelated files.

---

### Task 2: Scientific Defaults and Two-Overplot Configuration

**Files:**
- Create: `crater_dating_agent/configs/moon_neukum.yaml`
- Create: `crater_dating_agent/config_generator.py`
- Create: `tests/test_config_generator.py`

**Interfaces:**
- Consumes: `DatingRequest`, `ResolvedInputs` from Task 1.
- Produces: `ScientificConfig`, `load_scientific_config() -> ScientificConfig`, `render_cs(request, inputs, output_stem) -> str`.

- [ ] **Step 1: Write the failing configuration behavior tests**

Build a real `DatingRequest`/`ResolvedInputs` using a temporary path containing a space. Assert the rendered configuration:

- selects `MoonNeukum1983`, `MoonGuoetal2024`, and differential presentation;
- requests PNG and CSV at the supplied output stem;
- contains exactly two `-p` definitions;
- first overplot contains the literal requested `[0.06,0.2]`, `type=b-poisson`, `binning=pseudo-log`, and `psym=fo`;
- second contains the temporary absolute CRATER source path, `name=plot 2`, `type=data`, `binning=pseudo-log`, and `psym=o`;
- second overplot substring does not contain `range=`;
- the spaced source survives `shlex.split` as one overplot argument.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_config_generator.py -v
```

Expected: import failure because `config_generator` does not exist.

- [ ] **Step 3: Add the versioned YAML defaults**

Create:

```yaml
schema_version: 1
body: Moon
chronology_system:
  label: "Moon, Neukum (1983)"
  cli: MoonNeukum1983
epochs:
  label: "Moon, Guo et al (2024)"
  cli: MoonGuoetal2024
equilibrium: null
presentation: differential
binning: pseudo-log
fit:
  type: b-poisson
  symbol: fo
overview:
  name: "plot 2"
  type: data
  symbol: o
formats:
  - png
  - csv
```

- [ ] **Step 4: Implement minimal loading and rendering**

Load the packaged YAML with `importlib.resources`, validate required keys, and return an immutable `ScientificConfig`. Render a `.cs` string using `shlex.quote` for output and complete overplot expressions. Format numeric range values with `format(value, ".12g")` so `0.0600` becomes `0.06` without scientific-noise digits.

The semantic line order must be:

```text
-o <quoted-output-stem>
-f png csv
-cs MoonNeukum1983
-ep MoonGuoetal2024
-pr differential
-p <quoted-fit-overplot>
-p <quoted-overview-overplot>
```

- [ ] **Step 5: Run configuration tests and verify GREEN**

Run the Task 2 pytest command. Expected: all configuration behavior tests pass.

- [ ] **Step 6: Run Tasks 1–2 regression tests**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_path_resolver.py tests/test_config_generator.py -v
```

Expected: all tests pass.

---

### Task 3: Direct Craterstats Python Invocation Boundary

**Files:**
- Modify: `crater_dating_agent/models.py`
- Create: `crater_dating_agent/craterstats_wrapper.py`
- Create: `tests/test_craterstats_wrapper.py`

**Interfaces:**
- Consumes: a generated `.cs` path and expected output stem.
- Produces: `InvocationResult(config_path, plot_path, csv_path, log_path, stdout, stderr)` and `invoke_craterstats(config_path, output_stem, cli_main=None) -> InvocationResult`.

- [ ] **Step 1: Write failing tests against a specific fake external boundary**

Use a fake `cli_main(argv)` that requires the exact argument list `['-i', '<absolute-config-path>']`, writes `<output_stem>.png` and `<output_stem>.csv`, prints one line, and deliberately changes the current directory. Assert the real wrapper restores the caller working directory, captures stdout, writes the log, and returns existing absolute output paths. Add separate fakes for nonzero `SystemExit(2)` and success-without-CSV; assert both raise `DatingError` and the missing-output error names the absent path.

The fake exists only at the slow third-party `craterstats.cli.main` boundary; filesystem, cwd restoration, output verification, and log creation remain real.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_craterstats_wrapper.py -v
```

Expected: import failure because `craterstats_wrapper` does not exist.

- [ ] **Step 3: Implement the invocation result and wrapper**

Add the immutable `InvocationResult` dataclass. In `invoke_craterstats`:

1. Resolve config and output paths.
2. Import `craterstats.cli.main` only when `cli_main` is `None`; convert `ImportError` into a Chinese `DatingError` with the missing package name.
3. Capture stdout/stderr with `redirect_stdout`/`redirect_stderr`.
4. Save and restore `Path.cwd()` in `finally`, because Craterstats `-i` changes the process directory.
5. Treat `SystemExit(None)` and `SystemExit(0)` as success; reject other codes.
6. Write combined execution text to `<output_stem>.log`.
7. Require `<output_stem>.png` and `<output_stem>.csv` to exist.

- [ ] **Step 4: Run wrapper tests and verify GREEN**

Run the Task 3 pytest command. Expected: all wrapper tests pass and each temporary test directory is cleaned by pytest.

- [ ] **Step 5: Run all current unit tests**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_path_resolver.py tests/test_config_generator.py tests/test_craterstats_wrapper.py -v
```

Expected: all tests pass.

---

### Task 4: Craterstats CSV Result Parsing

**Files:**
- Modify: `crater_dating_agent/models.py`
- Create: `crater_dating_agent/result_parser.py`
- Create: `tests/fixtures/craterstats_minimal.csv`
- Create: `tests/test_result_parser.py`

**Interfaces:**
- Consumes: a CSV freshly produced by the current invocation.
- Produces: `AgeEstimate` and `parse_age_csv(csv_path) -> AgeEstimate`.

- [ ] **Step 1: Create an independent hand-written CSV fixture and failing tests**

The fixture must include Craterstats-style preamble rows, then this literal header and result:

```csv
Name,Area,Binning,d_min,d_max,Method,Resurf,N,N_event,Sort_order,Age,Age-,Age+,Source
CRATER_TEST,10.7,pseudo-log,0.06,0.2,b-poisson,0,63,63,0,0.376,0.331,0.425,C:/fixture/CRATER_TEST.shp
```

Assert parsing returns `crater_count=63`, `age_ga=0.376`, `age_lower_ga=0.331`, `age_upper_ga=0.425`, `age_minus_ga=0.045`, and `age_plus_ga=0.049`. Add generated temporary CSV tests for a missing `Age+` column, no `b-poisson` row, and nonnumeric `Age`; each must raise `DatingError` naming the problem.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_result_parser.py -v
```

Expected: import failure because `result_parser` does not exist.

- [ ] **Step 3: Implement a header-driven parser**

Read with `encoding="utf-8-sig"` and `csv.reader`. Locate the first row whose first cell is exactly `Name` and which contains `Method`, `Age`, `Age-`, and `Age+`. Feed that row plus later rows to `csv.DictReader`, select exactly one `Method == "b-poisson"` row, and parse values using field names. Compute errors as `age - lower` and `upper - age` without rounding the stored floats.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run the Task 4 pytest command. Expected: all parser tests pass.

- [ ] **Step 5: Mutation-check parser behavior**

Temporarily change the selected method string locally to `data`, run the success test and confirm it fails with no fit row; restore `b-poisson` and rerun to green. Do not leave the mutation in the worktree.

---

### Task 5: Single-Dating Service, JSON Result, and Manifest

**Files:**
- Modify: `crater_dating_agent/models.py`
- Create: `crater_dating_agent/service.py`
- Create: `tests/test_service.py`

**Interfaces:**
- Consumes: `DatingRequest`, resolver, config renderer, invoker, and parser.
- Produces: `DatingResult` and `run_single_dating(request, *, clock=None, cli_main=None) -> DatingResult`.

- [ ] **Step 1: Write the failing end-to-end service test with only Craterstats replaced**

Create real temporary AREA/CRATER sidecars and TIFF. Supply a fixed clock returning `2026-08-24 20:00:00`. The fake Craterstats boundary must parse the generated `.cs` using `shlex.split`, assert the two overplot semantics, then write a real minimal PNG byte file and a real CSV result. Assert service outputs are under `outputs/SID9/20260824_200000`, JSON contains the literal parsed age values and all three absolute inputs, and manifest contains both overplots, exact CLI argv, status `success`, and generated files.

Add a failure test whose fake raises `SystemExit(3)`; assert the manifest exists with status `failed`, the log remains, and no age JSON is created.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_service.py -v
```

Expected: import failure because `service` does not exist.

- [ ] **Step 3: Implement the minimal orchestration flow**

Implement this order:

```text
resolve_inputs
→ choose/create output directory
→ write {case_id}_dating.cs
→ write initial run_manifest.json(status=running)
→ invoke_craterstats
→ parse_age_csv
→ write {case_id}_age_result.json
→ rewrite manifest(status=success, generated_files=[the newly created artifact paths])
```

On any exception after output-directory creation, rewrite the manifest with `status="failed"`, `error_type`, and `error_message`, then re-raise. Serialize JSON as UTF-8 with `ensure_ascii=False`, `indent=2`, and a trailing newline. Use `dataclasses.asdict` only on owned dataclasses; convert `Path` values explicitly to strings.

- [ ] **Step 4: Run service tests and verify GREEN**

Run the Task 5 pytest command. Expected: success and failure behavior tests pass.

- [ ] **Step 5: Run the full unit suite**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -v
```

Expected: all unit tests pass with no warnings.

---

### Task 6: User-Facing CLI

**Files:**
- Create: `crater_dating_agent/main.py`
- Create: `crater_dating_agent/__main__.py`
- Modify: `crater_dating_agent/__init__.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_single_dating` from Task 5.
- Produces: `main(argv: list[str] | None = None) -> int` and `python -m crater_dating_agent`.

- [ ] **Step 1: Write failing CLI behavior tests**

Call `main(argv, _run=fake_run)` with the complete six-option argv using three real-looking temporary paths and range `0.06`, `0.2`. Assert success returns 0 and prints the JSON/PNG paths from a real `DatingResult`. Assert a `DatingError("CRATER 数据为空")` returns 2, writes the Chinese error to stderr, and does not print success output. Repeat with the same complete argv but `--range-min 0.2 --range-max 0.06`, and assert validation returns nonzero.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_cli.py -v
```

Expected: import failure because `main.py` does not exist.

- [ ] **Step 3: Implement argparse and module entry**

Required options:

```text
--crater-shp PATH
--area-shp PATH
--image-tif PATH
--range-min FLOAT
--range-max FLOAT
--output-dir PATH   (optional)
```

`main` constructs `DatingRequest`, calls the service, prints concise Chinese output with age and artifact paths, returns 0 on success, and returns 2 for `DatingError`. `__main__.py` must use `raise SystemExit(main())`.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run the Task 6 pytest command. Expected: all CLI tests pass.

- [ ] **Step 5: Exercise help as a real module**

Run:

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m crater_dating_agent --help
```

Expected: exit 0 and all six options are documented.

---

### Task 7: Install Craterstats and Run the Real SID9 Acceptance Test

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_sid9_integration.py`
- Output only: `outputs/SID9/{YYYYMMDD_HHMMSS}/` and its newly generated artifacts.

**Interfaces:**
- Consumes: the public CLI from Task 6 and official Craterstats package.
- Produces: fresh SID9 `.cs`, `.png`, `.csv`, `.log`, `_age_result.json`, and `run_manifest.json` generated only from the three specified inputs.

- [ ] **Step 1: Add the pinned Craterstats dependency**

Add the exact released Craterstats version used by the 2026 test environment to `pyproject.toml`:

```toml
"craterstats==3.6.7"
```

Record the resolved Craterstats version in the manifest. A moving `main` dependency is not acceptable for paper reproducibility.

- [ ] **Step 2: Install the project in an isolated environment**

Create `agent_build/.venv` with the bundled Python, then install editable test dependencies. Network access requires user approval when the installation command requests it.

```powershell
& 'C:\Users\LDH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -e '.[test]'
```

Expected: installation exits 0 and `.venv\Scripts\python.exe -c "import craterstats"` exits 0.

- [ ] **Step 3: Write the integration test before running the real calculation**

Mark the test `@pytest.mark.integration`. It must read only these paths:

```text
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\AREA_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\CRATER_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\3M_DOM\63_61E8_08N.tif
```

Use range `0.06–0.2 km`, run into pytest `tmp_path`, and assert fresh output existence, `crater_count > 0`, `age_ga > 0`, ordered confidence bounds, correct three input paths, and a second overplot with no range. Do not assert any historical age value.

- [ ] **Step 4: Run integration test and observe the first real failure**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_sid9_integration.py -v -m integration
```

Expected on the first run: either PASS if the external contract matches, or a concrete boundary failure naming a Craterstats argument/output assumption. Do not weaken assertions. For any boundary failure, add the narrowest regression test reproducing it before changing production code, then rerun RED→GREEN.

- [ ] **Step 5: Run the public CLI on SID9**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m crater_dating_agent `
  --area-shp 'E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\AREA_SID9.shp' `
  --crater-shp 'E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\CRATER_SID9.shp' `
  --image-tif 'E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\3M_DOM\63_61E8_08N.tif' `
  --range-min 0.06 `
  --range-max 0.2
```

Expected: exit 0; terminal reports a positive age and paths to newly generated artifacts under `agent_build/outputs/SID9/<timestamp>/`.

- [ ] **Step 6: Verify fresh outputs and scientific configuration**

Open only the new run directory. Confirm:

- `.cs` contains exactly two overplots;
- fit overplot is `b-poisson` with `[0.06,0.2]`;
- overview overplot has `type=data`, `name=plot 2`, and no range;
- PNG is nonempty and visually shows the global data distribution plus local fit;
- CSV contains a `b-poisson` row;
- JSON numbers match that fresh CSV row;
- manifest records 1545 input crater records and the exact three inputs.

- [ ] **Step 7: Run complete verification**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -v
& '.\.venv\Scripts\python.exe' -m crater_dating_agent --help
```

Expected: all tests pass, help exits 0, and there are no warnings or errors.

- [ ] **Step 8: Review the final workspace diff and scope**

Confirm only the files listed in this plan changed, plus generated `outputs/` and `.venv/`. Confirm `csfd_code/`, `crater_detect_model/`, and detection behavior remain unchanged. Do not claim completion until verification output is freshly read and all design requirements are checked line by line.