# Craterstats 单次定年工具设计

## 1. 目标

在不启动 Craterstats GUI、不依赖大模型的前提下，开发一个可测试、可复现的 Python 单次定年工具。工具接收一套配对的月球 `CRATER_xxx.shp` 与 `AREA_xxx.shp`，按用户提供的直径范围调用 Craterstats，输出 CSFD 图、Craterstats 原始结果、结构化年龄结果和完整运行记录。

本阶段建立后续 range 搜索、人机确认及大模型编排所调用的确定性工具层。

## 2. 范围

### 2.1 本阶段实现

- 从命令行或 Python API 接收 `CRATER_xxx.shp`、range 下限、range 上限和输出目录。
- 根据 `CRATER_` 文件名自动寻找同目录的 `AREA_` 配套 shapefile。
- 校验 shapefile 主文件与必要的 `.dbf`、`.shx` 配套文件。
- 生成可复现的 Craterstats `.cs` 配置。
- 直接在 Python 中调用 `craterstats.cli.main(argv)`，不启动 GUI。
- 每次创建两个 overplot：一个 buffered-Poisson 拟合层和一个无 range 的全局数据层。
- 输出 PNG、CSV、统一 JSON 结果和运行清单。
- 为路径解析、配置生成、Craterstats 调用边界、CSV 解析及失败场景编写自动化测试。
- 使用人工构造的最小 CSV fixture 测试结果解析，不读取测试目录中以前运行产生的 `.cs`、`.csv` 或 `.png`。

### 2.2 本阶段不实现

- 自动搜索或推荐最佳 range。
- 拟合质量综合评分。
- DeepSeek、通义或其他大模型 API。
- 对话状态、人机确认界面和网页界面。
- HTML/PDF 综合报告。
- 修改王怡然模型推理逻辑、ArcPy 裁剪逻辑或撞击坑追加逻辑。

## 3. 项目布局

```text
agent_build/
├── part1_code/                     # 已有检测流程，仅更新模型默认路径
├── wangyiranCode/                  # 王怡然模型、权重和投影文件
├── csfd_code/                      # 第三方 craterstatsGUI 源码，保持原样
├── crater_dating_agent/            # 新的确定性单次定年工具
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py
│   ├── models.py
│   ├── path_resolver.py
│   ├── config_generator.py
│   ├── craterstats_wrapper.py
│   ├── result_parser.py
│   └── configs/
│       └── moon_neukum.yaml
├── tests/
│   ├── fixtures/
│   ├── test_path_resolver.py
│   ├── test_config_generator.py
│   ├── test_craterstats_wrapper.py
│   ├── test_result_parser.py
│   └── test_cli.py
├── outputs/
└── docs/
```

`crater_dating_agent` 不导入 `part1_code` 或 `wangyiranCode`。两个阶段只通过 `CRATER/AREA` 文件交接。

## 4. 路径管理

### 4.1 已有模型

`auto_crater_detection_pipeline.py` 中的 `DEFAULT_MODEL_DIR` 更新为：

```text
E:\DiHuaSuo\2026\paper\csfd_agent\agent_build\wangyiranCode
```

除这一默认路径外，不修改已有检测流程。

### 4.2 Craterstats

`csfd_code` 是 craterstatsGUI 外壳，其 `requirements.txt` 声明官方 `craterstats` 核心包依赖。项目使用独立 Python 环境安装核心包。单次定年工具通过公开的 `craterstats.cli.main(argv)` 调用它，不自动点击 GUI，也不修改第三方源码。

启动时必须验证 `craterstats` 可导入；不可导入时返回包含安装指引的明确错误，不静默回退到 GUI。

### 4.3 输入输出

输入文件可位于项目之外，由 `--crater-shp` 显式传入。默认输出位置为：

```text
agent_build/outputs/<case_id>/<YYYYMMDD_HHMMSS>/
```

可通过 `--output-dir` 覆盖。工具不修改输入 shapefile。

## 5. 输入接口与验证

命令行形式：

```powershell
python -m crater_dating_agent \
  --crater-shp "...\CRATER_SID9.shp" \
  --area-shp "...\AREA_SID9.shp" \
  --image-tif "...\63_61E8_08N.tif" \
  --range-min 0.8 \
  --range-max 3.0
```

Python API 形式：

```python
result = run_single_dating(request)
```

请求包含：

- `crater_shp: Path`
- `area_shp: Path`
- `image_tif: Path`
- `range_min_km: float`
- `range_max_km: float`
- `output_dir: Path | None`

验证规则：

- 输入文件名必须以 `CRATER_` 开头且扩展名为 `.shp`，大小写不敏感。
- `area_shp` 必须与 `crater_shp` 位于同一目录，且其余文件名不变、前缀由 `CRATER_` 替换为 `AREA_`；自动推导结果必须与显式输入一致。
- `image_tif` 必须存在且扩展名为 `.tif` 或 `.tiff`。TIFF 不传递给 Craterstats，只作为同一测试样区的上游影像来源写入运行清单。
- 两套 shapefile 至少具有 `.shp`、`.shx`、`.dbf`。
- `range_min_km > 0`。
- `range_max_km > range_min_km`。
- CRATER 数据表必须至少有 1 条记录；空数据在调用 Craterstats 前失败。
- 输出目录不得与输入 shapefile 主文件重名。

遥感 TIFF 不参与本阶段 Craterstats 定年计算，只保留为上游检测流程的输入与运行清单中的必填溯源信息。本阶段不会再次裁剪 TIFF 或运行王怡然检测模型。

## 6. Craterstats 固定科学配置

- Body：Moon
- Chronology system：Moon, Neukum (1983)
- Epochs：Moon, Guo et al (2024)
- Equilibrium function：None
- Presentation：differential
- Binning：pseudo-log
- 输出格式：PNG 与 CSV

所有科学默认值集中保存在 `moon_neukum.yaml`，生成配置时使用 Craterstats 接受的规范标识。

## 7. 双 overplot 设计

每次运行按以下顺序创建两个 overplot。

### 7.1 Overplot 1：年龄拟合层

- source：输入 `CRATER_xxx.shp`
- type：`b-poisson`
- range：用户传入的 `[range_min_km, range_max_km]`
- binning：`pseudo-log`
- symbol：filled circle，Craterstats 标识 `fo`
- show age：是
- error bars：是

### 7.2 Overplot 2：全局数据层

- source：与 overplot 1 相同；配置文件中显式写出，避免依赖 carry-over 隐式状态
- name：`plot 2`
- type：`data`
- 不写入 range
- binning：`pseudo-log`
- symbol：circle，Craterstats 标识 `o`
- show age：否

第二层不参与年龄拟合，只用于让图形自动缩放时保留完整直径分布视野。

任意 SID9 range 为 `[d_min,d_max]` 时，配置结构等价于：

```text
-ep MoonGuoetal2024
-p source=CRATER_SID9.shp,range=[d_min,d_max],type=b-poisson,binning=pseudo-log,psym=fo
-p source=CRATER_SID9.shp,name=plot 2,type=data,binning=pseudo-log,psym=o
```

## 8. 调用边界

`config_generator` 只生成结构化参数及 `.cs` 文本，不执行计算。`craterstats_wrapper` 接收参数列表并调用 `craterstats.cli.main(argv)`。

包装器负责：

- 在受控工作目录中运行并在结束后恢复原工作目录。
- 捕获 Craterstats 通过 `SystemExit` 表达的非零退出状态。
- 捕获标准输出和标准错误，写入运行日志。
- 验证预期 `.cs`、`.png`、`.csv` 是否实际生成。
- 不吞掉异常；统一转换为带阶段、输入路径和原因的工具错误。

为避免测试依赖真实 Craterstats 计算，调用函数通过依赖注入接收 CLI callable。集成测试再使用真实 `craterstats.cli.main`。

## 9. 结果解析

`result_parser` 从本次运行新生成的 Craterstats CSV 中按列名读取拟合行，不按固定列号读取。输出 JSON 至少包含 `case_id`、三项输入绝对路径、年代学配置、方法、range、撞击坑数量、年龄及其上下置信边界、上下误差和本次生成的图、CSV、配置路径。

`Age-` 与 `Age+` 在 Craterstats CSV 中是年龄置信区间边界；统一 JSON 同时保存边界和由边界计算的上下误差，避免误解字段含义。

## 10. 运行清单与可复现性

每次运行写入 `run_manifest.json`，记录：

- 工具版本与 Craterstats 版本。
- 输入和输出绝对路径。
- 输入 shapefile 各组件的大小与修改时间。
- 完整科学配置和两个 overplot。
- 传给 `craterstats.cli.main` 的实际参数列表。
- 开始时间、结束时间和执行状态。
- 生成文件清单。

本阶段不计算输入文件哈希，以避免对大型科研数据增加不必要开销；后续如论文归档需要可单独开启。

## 11. 错误处理

以下情况必须在终端显示中文可操作错误，同时返回非零退出码：

- CRATER 或 AREA shapefile 缺失组件。
- 未找到配对 AREA 文件。
- CRATER 数据为空。
- range 非法。
- 无法导入 craterstats。
- Craterstats 执行失败。
- Craterstats 未生成 CSV 或 PNG。
- CSV 中没有 `b-poisson` 拟合结果或关键年龄字段无法转换。

失败运行仍保留日志和标记为 `failed` 的运行清单，但不生成看似有效的年龄 JSON。

## 12. 测试与验收

### 12.1 单元测试

- 从 `CRATER_SID9.shp` 正确解析 `SID9` 并匹配 `AREA_SID9.shp`。
- 缺失 AREA、缺失 sidecar、空 CRATER 和非法 range 均被拒绝。
- 配置包含两个 overplot，且第二层明确没有 range。
- 配置使用 `MoonGuoetal2024`、`b-poisson`、`fo`、`data`、`pseudo-log` 和 `o`。
- Craterstats CLI 收到精确参数列表。
- 人工构造的最小 CSV fixture 可被解析为预先写入的撞击坑数量、年龄和上下置信边界。
- CSV 缺失列、无拟合行或非数值年龄时给出明确错误。

### 12.2 集成测试

- 在安装 craterstats 的独立 Python 环境中真实调用 `craterstats.cli.main`。
- 使用非空的 SID9 `CRATER/AREA` 配套数据执行 `0.8–3.0 km` 单次定年。
- 确认 `.cs`、`.png`、`.csv`、年龄 JSON 和运行清单均生成。
- 将解析结果与 Craterstats 原始 CSV 逐字段核对。

### 12.3 指定的 SID9 测试输入

测试及运行只允许读取以下三项输入：

```text
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\AREA_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\CRATER_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\3M_DOM\63_61E8_08N.tif
```

同目录中以前运行生成的 `.cs`、`.csv`、`.png` 不是本阶段输入、fixture 或预期答案，程序和测试不得读取它们。

替换后的数据已核查：`AREA_SID9.dbf` 有 1 条记录，`CRATER_SID9.dbf` 有 1545 条记录；CRATER 表包含 `Diam_km`、`x_coord`、`y_coord`、`tag` 字段。AREA/CRATER 的 `.shp`、`.shx`、`.dbf`、`.prj` 均存在，TIFF 可读，因此满足真实端到端定年测试的数据前提。

## 13. 后续扩展边界

后续 range 搜索、人机确认与大模型编排只能调用本阶段稳定的 `run_single_dating(request)` 接口。它们不得绕过验证直接调用 Craterstats，也不得修改单次定年的科学默认配置；需要变化时通过显式配置版本实现。
