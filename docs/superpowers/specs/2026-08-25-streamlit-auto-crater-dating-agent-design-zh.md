# Streamlit 自动撞击坑识别与智能定年系统设计

日期：2026-08-25

## 1. 目标

在现有 Craterstats 单次定年与 DeepSeek 直径区间推荐能力之前，接入撞击坑自动识别模型，并用 Streamlit 包装为本机交互界面。

用户新建任务时必须提供三个输入：

1. 用户绘制完成的 `AREA_<编号>.shp` 定年区域及其配套文件；
2. 与 AREA 同步建立、字段结构正确的 `CRATER_<编号>.shp` 及其配套文件；CRATER 可以为空，也可以已经包含用户准备好的撞击坑；
3. 覆盖定年区域的原始 GeoTIFF 影像。

系统先读取 CRATER 记录数并自动编排工具流程：空 CRATER 调用撞击坑自动识别模型，非空 CRATER 跳过识坑并直接进入现有智能定年流程。自动识坑结果在 TIFF 叠加预览中由用户检查；不满意时允许导入人工修订 CRATER 并重新预览。确认的数据随后进入全局 CSFD、DeepSeek 多模态区间推荐、候选拟合图、人工选择和最终定年流程。

## 2. 核心约束

- `part1_code/auto_crater_detection_pipeline.py` 和 `part1_code/run_crater_detection_model_py3.py` 已经过实际验证，视为稳定核心，不重构识别、投影、字段转换或写入算法。
- 新功能采用薄编排层，通过参数列表形式的子进程调用既有脚本。
- 第一版继续依赖 ArcGIS 10.8 ArcPy/Python 2.7。
- `crater_detect_model` 中的 ONNX 撞击坑自动识别模型继续使用独立 Python 3.9 环境运行。
- Streamlit 和现有定年智能体运行在项目 `.venv` 中。
- 不修改用户原始 AREA、CRATER 或 TIFF。
- AREA 文件名必须以 `AREA_` 开头，CRATER 文件名必须以 `CRATER_` 开头；两个前缀后的完整任务编号必须严格一致，例如 `AREA_SID9.shp` 对应 `CRATER_SID9.shp`，不能增加 `_AUTO` 等后缀。
- 页面标题、图例、路径和输出名均从用户输入的 `AREA_<编号>.shp` 动态提取编号，不能硬编码 `SID9`。
- 用户可见界面统一使用“撞击坑自动识别模型”，不显示人员姓名。
- 页面支持中文与 English 即时切换；文件名、任务编号、路径和科学数值不翻译。
- 第一版只提供“新建定年任务”页面，不提供历史任务恢复入口；后台仍保留状态文件，以便以后扩展。

## 3. 总体架构

```text
Streamlit 本地界面（项目 .venv）
  |
  +-- 输入验证与任务副本
  |
  +-- CRATER 记录数智能路由
  |     |-- 非空：跳过识坑，直接进入现有定年智能体
  |     `-- 空：ArcPy Python 2.7
  |           `-- auto_crater_detection_pipeline.py
  |                  `-- 模型 Python 3.9
  |                        `-- run_crater_detection_model_py3.py
  |
  +-- TIFF + AREA + CRATER 降采样叠加预览
  |     |-- 满意：使用自动结果
  |     `-- 不满意：导入人工修订 CRATER，校验并重新预览
  |
  `-- 现有 crater_dating_agent
        +-- 无年龄全局 CSFD 图
        +-- 结构化 CSFD 数据
        +-- DeepSeek 多模态区间推荐
        +-- 三个候选拟合图与年龄
        +-- 人工选择或手工 range
        `-- 最终定年结果
```

新增模块的职责边界：

- `crater_dating_agent/web_app.py`：Streamlit 页面、组件布局和用户事件；不包含地学处理逻辑。
- `crater_dating_agent/detection_service.py`：输入验证、任务副本、空/非空智能路由、识坑结果和人工修订结果验证与统计。
- `crater_dating_agent/pipeline_runner.py`：安全启动 ArcPy 子进程、采集输出、写日志、解释退出状态。
- `crater_dating_agent/overlay_preview.py`：对大型 TIFF 只为显示目的降采样，并叠加动态 AREA 边界与 CRATER 轮廓。
- `crater_dating_agent/ui_state.py`：页面阶段、数据来源、语言、幂等按钮和当前任务状态。

已有 `agent_service.py` 继续负责全局图、DeepSeek 推荐、候选预览、确认和最终定年。

## 4. 输入契约

Streamlit 使用本机绝对路径文本框，不通过浏览器上传大型 TIFF 或拆散 Shapefile 配套文件。

启动识坑前必须满足以下条件：

- AREA `.shp`、CRATER `.shp` 和 TIFF 均存在；
- AREA 和 CRATER 至少具有 `.shp`、`.shx`、`.dbf`、`.prj` 配套文件；
- AREA 文件名以 `AREA_` 开头，CRATER 文件名以 `CRATER_` 开头；
- `AREA_<编号>` 与 `CRATER_<编号>` 的 `<编号>` 完全一致；
- AREA 和 CRATER 均为 Polygon；
- AREA 包含 `Area` 和 `Area_Name` 字段；
- CRATER 包含 `Diam_km`、`x_coord`、`y_coord` 和 `tag` 字段；
- AREA 与 CRATER 的空间参考一致且不是 Unknown。

验证通过后读取 CRATER 记录数：

- 记录数为零：自动进入撞击坑识别工具链；
- 记录数大于零：跳过撞击坑识别工具链，直接使用用户提供的 CRATER 进入现有智能定年流程；
- 无论哪条路径，都不能自动清空或覆盖用户原始 CRATER。

## 5. 任务目录与数据保护

每次运行创建独立目录：

```text
outputs/<编号>/<时间戳>/
|-- source_copy/
|   |-- AREA_<编号>.*
|   `-- CRATER_<编号>.*
|-- manual_revision/
|   `-- CRATER_<编号>.*
|-- detection_work/
|   |-- clip/
|   |-- model_output/
|   |-- backup/
|   `-- appended_craters.csv
|-- detection_preview/
|   |-- automatic_overlay.png
|   `-- manual_overlay.png
|-- overview/
|-- previews/
|-- final/
|-- logs/
`-- session_state.json
```

AREA 和 CRATER 的现有配套文件复制到 `source_copy`。空 CRATER 路径中，识坑脚本只接收任务副本中的 CRATER 作为 `--target-shp`；非空 CRATER 路径中，副本直接交给定年智能体。人工修订文件复制到 `manual_revision`，不能覆盖自动识坑结果。TIFF 默认按原绝对路径只读使用；裁剪结果写入 `detection_work`，降采样叠加图写入 `detection_preview`。

任务失败时保留副本、中间文件、状态和日志，不删除用户数据，也不自动清理诊断证据。

## 6. 页面流程

### 6.1 输入数据

用户填写 AREA、CRATER 和 TIFF 路径。页面提供“验证输入”按钮，验证成功后显示从 `AREA_<编号>` 动态提取的任务编号、投影、CRATER 记录数、系统选择的工具路径和目标输出目录。

### 6.2 智能路由

系统读取 CRATER 记录数：

- 非空：显示“已检测到撞击坑，将跳过自动识别”，直接生成全局 CSFD 并进入 DeepSeek 区间推荐；
- 空：显示“CRATER 为空，将调用撞击坑自动识别模型”，进入自动识坑阶段。

路由由确定性程序规则完成，不把是否识坑的判断交给大模型。

### 6.3 自动识坑

用户点击“开始自动识坑”。页面锁定重复提交，创建任务副本并调用现有 ArcPy 自动化脚本。子进程标准输出和错误输出显示在页面，同时写入任务日志。

### 6.4 识坑叠加预览与确认

成功后读取任务副本中的 CRATER，显示：

- 识别撞击坑数量；
- 直径大于等于 1 km 的撞击坑数量；
- 最大直径和最小直径；
- 生成的 CRATER 路径；
- 日志路径及警告。

页面同时生成并显示原始 TIFF、`AREA_<当前编号>` 边界和 `CRATER_<当前编号>` 轮廓叠加图。大型 TIFF 仅为预览降采样，空间校验和定年仍使用原始矢量数据。预览支持适应窗口、放大、缩小以及显示/隐藏坑图层。

零撞击坑、缺少结果文件或结果字段错误视为失败，不能继续。有效结果提供两个分支：

- “满意，直接使用自动结果”：进入智能定年；
- “不满意，导入人工修订文件”：显示人工修订 CRATER 的本机路径输入框。

人工修订 CRATER 必须保持与 AREA 严格配对的名称、Polygon 几何、标准字段、相同投影且至少包含一条记录。用户填写路径后点击“校验并生成新预览”，系统把配套文件复制到 `manual_revision` 并生成新的叠加图；用户再次点击“满意，使用人工修订结果”后才进入定年。自动识坑结果始终保留。

### 6.5 智能推荐与人工选择

智能路由选定并确认定年使用的 CRATER 后，系统调用现有能力：

1. 生成没有年龄拟合的全局 CSFD 图；
2. 将全局图与结构化 CSFD 数据发送给 `deepseek-v4-flash-vision-exp`；
3. 显示 DeepSeek 总体观察；
4. 显示三个候选 range、理由、风险、暂定年龄和候选拟合图；
5. 允许用户选择候选，或手工输入 range 并确认风险。

### 6.6 最终结果

用户确认后生成最终定年结果，页面显示年龄、误差、采用区间、最终 CSFD 图以及输出目录。

### 6.7 中英文切换

页面右上角提供“中文 / English”切换。所有固定步骤、按钮、说明、统计标签、验证错误和最终结果标签均提供双语文本。DeepSeek 总体观察和候选理由按照发起请求时选择的界面语言生成；切换语言不会自动重发 API 请求或改写已经生成的模型文本。文件名、任务编号、绝对路径、原始技术日志和科学数值保持原样。

## 7. 运行环境配置

以下配置具有默认值，同时允许在 Streamlit“高级设置”中修改：

```text
ARCPY_PYTHON=C:\Python27\ArcGIS10.8\python.exe
CRATER_MODEL_PYTHON=C:\ProgramData\Anaconda3\envs\crater_model_py39\python.exe
CRATER_MODEL_DIR=E:\DiHuaSuo\2026\paper\csfd_agent\agent_build\crater_detect_model
```

DeepSeek 配置规则：

- 优先读取环境变量 `DEEPSEEK_API_KEY`；
- 未设置时在 Streamlit 侧边栏显示密码输入框；
- 页面输入的密钥只保存在当前进程内存；
- 密钥不写入日志、状态、错误文本、配置文件或 Git；
- 模型默认为 `deepseek-v4-flash-vision-exp`。

## 8. 子进程与错误处理

- 使用参数数组启动子进程，不使用 `shell=True`，不拼接 shell 命令字符串。
- 启动前验证 Python 解释器、两个既有脚本、模型目录和 ONNX 权重存在。
- 捕获子进程退出码、标准输出和标准错误；日志中记录阶段和时间，但过滤密钥。
- ArcPy 或撞击坑自动识别模型失败时停留在识坑阶段，不调用 DeepSeek。
- DeepSeek 失败时保留识坑和全局图结果，允许在当前页面重新请求，不重复运行识坑。
- 页面状态机防止重复点击造成并发写入同一个 CRATER。
- 每个阶段只允许访问当前任务目录中经过验证的副本和输出。
- 人工修订文件校验或预览失败时保留当前自动结果，不能切换当前定年数据源。

## 9. 测试策略与检查点

实施采用测试驱动开发。

### 9.1 单元测试

- `AREA_`/`CRATER_` 严格前缀和完整任务编号配对；
- Shapefile 配套文件、字段、几何、记录数和投影验证；
- 空 CRATER 自动进入识坑、非空 CRATER 自动跳过识坑；
- 安全复制配套文件和创建任务目录；
- ArcPy/模型命令参数构造；
- 输出统计和零结果拒绝；
- 大型 TIFF 降采样叠加预览、动态图例名称和矢量位置；
- 人工修订 CRATER 校验、独立保存、重新预览和二次确认；
- 中文/English 文案切换及科学数据不翻译；
- UI 状态迁移与重复提交防护；
- API 密钥不持久化。

### 9.2 编排测试

使用模拟子进程验证：

- Streamlit 编排正确传递任务副本和工作目录；
- 已有坑的 CRATER 不启动 ArcPy 或识别模型进程；
- 识坑确认之前不会调用定年服务；
- 人工修订预览确认之前不会切换定年数据源；
- 失败不会越过检查点；
- DeepSeek 重试不会再次运行识坑；
- 候选确认后才生成最终结果。

### 9.3 真实 SID9 集成测试

测试输入：

```text
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\backup\AREA_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\date\backup\CRATER_SID9.shp
E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N\3M_DOM\63_61E8_08N.tif
```

检查点顺序：

1. 输入验证和任务副本；
2. 空 CRATER 路径实际运行撞击坑自动识别模型、统计和叠加预览，由用户检查；
3. 非空 CRATER 路径跳过识坑，以及 Streamlit 双语页面完整交互；
4. 用户使用本机密钥执行 DeepSeek 和最终定年；
5. 全部旧测试和新增测试通过。

## 10. GitHub 发布

Git 整理和 GitHub 发布只在功能、真实测试和文档全部确认后进行。当前不初始化仓库。

最终建立私有 GitHub 仓库。提交前：

- 检查第三方 Craterstats 与 `crater_detect_model` 许可证；
- 不提交 API 密钥、`.env`、`outputs`、缓存、测试数据和本机配置；
- ONNX 权重默认不提交，在 README 说明本地目录结构；
- 移除或配置化需要发布的本机绝对路径；
- 提交智能体代码、Streamlit 页面、测试、配置模板和中英文说明；
- 运行完整测试与敏感信息扫描。

本机目前未安装 GitHub CLI。发布阶段再安装并由用户通过浏览器执行 GitHub 登录，不在对话中传递密码或访问令牌。

## 11. 非目标

第一版不包含：

- 重写两个既有识坑脚本的算法；
- 去除 ArcPy 依赖；
- 历史任务恢复页面；
- 上传到远程服务器运行；
- 自动修改或清空用户原始 CRATER；
- 在 Streamlit 中直接新增、删除、移动或调整撞击坑；第一版只负责叠加检查，人工修改在外部 GIS 工具中完成后重新导入；
- 自动公开第三方源代码或 ONNX 权重。