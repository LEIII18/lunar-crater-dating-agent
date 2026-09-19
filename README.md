# 月球撞击坑智能定年系统 / Lunar Crater Intelligent Dating System

本项目把撞击坑自动识别、人工叠加复核、Craterstats CSFD 定年和 DeepSeek 多模态拟合区间推荐整合为一个本机 Streamlit 应用。所有任务使用独立输出目录，用户原始 AREA、CRATER 和 TIFF 不会被修改。

## 输入要求

- `AREA_<编号>.shp`：用户绘制的定年区域；
- `CRATER_<编号>.shp`：与 AREA 同步建立、字段正确的撞击坑文件，可以为空；
- 原始 GeoTIFF。

AREA 与 CRATER 的编号必须完全相同，且 Shapefile 目录中必须包含 `.shp`、`.shx`、`.dbf` 和 `.prj`。空 CRATER 会调用撞击坑自动识别模型；有坑的 CRATER 会跳过识别并直接进入定年。

## 安装与运行（PyCharm）

以下用 `<项目目录>` 表示你克隆本仓库后的本地目录，不要直接照抄其他人的绝对路径。

1. 在 PyCharm 中打开 `<项目目录>`，并使用 Python 3.12 或更高版本创建或选择项目虚拟环境 `.venv`。
2. 在 PyCharm Terminal 中安装项目依赖：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .
   ```

3. 新建 **Python** Run/Debug Configuration：
   - Script path：`<项目目录>\.venv\Scripts\streamlit.exe`
   - Parameters：`run streamlit_app.py`
   - Working directory：`<项目目录>`
   - Environment variables：按本机实际安装位置填写下面的变量。

   ```text
   ARCPY_PYTHON=<ArcGIS 10.8 / ArcPy Python 2.7 的 python.exe 绝对路径>
   CRATER_MODEL_PYTHON=<撞击坑自动识别模型 Python 环境的 python.exe 绝对路径>
   CRATER_MODEL_DIR=<crater_detect_model 目录的绝对路径>
   DEEPSEEK_API_KEY=<可选；建议在此配置，而不要写入代码或提交到 Git>
   ```

   启动时，网页“高级设置”会自动读取前三项环境变量并作为默认值显示，因此无需每次重复输入。若未配置 `DEEPSEEK_API_KEY`，页面仍可临时输入；该值只保存在当前 Streamlit 进程内存。

4. 运行后打开 `http://localhost:8501`。

也可在已设置上述环境变量的终端中运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

> `.env.example` 仅是配置模板；项目不会自动读取 `.env` 文件。若使用该模板，请将实际值配置到 PyCharm 的 **Environment variables** 或操作系统环境变量中。
## 外部依赖：首次安装

本仓库只发布本项目的编排、界面和定年工作流代码；**不包含**撞击坑自动识别模型、模型权重或 CraterstatsGUI 源码。克隆后请按以下步骤完成本机配置。

1. 下载 [CraterstatsGUI](https://github.com/ggmichael/craterstatsGUI)（建议固定记录所用版本）。本项目使用其 Craterstats 能力生成 CSFD 图和定年结果；可通过 `craterstats==3.6.7` Python 包运行定年核心，或按该项目文档配置本地软件。
2. 从原始发布渠道获取撞击坑自动识别工具及其模型权重，并放在本机受控目录，例如：

   ```text
   <本机工具目录>/crater_detect_model/
   ```

   在页面“高级设置”中将 `CRATER_MODEL_DIR` 指向该目录，并设置对应的 `CRATER_MODEL_PYTHON` 解释器。不要将模型代码、权重或数据文件提交到本项目仓库，除非原始许可证明确允许再分发。
3. 按实际情况安装 ArcGIS 10.8 / ArcPy，并在页面中设置 `ARCPY_PYTHON`。自动识别流程当前依赖该本机环境。

推荐的本机目录关系如下（外部目录名称可不同）：

```text
agent_build/                         # 本仓库
├─ crater_dating_agent/              # 本项目代码
└─ .venv/                            # 本项目 Python 环境

<本机工具目录>/
├─ crater_detect_model/                    # 用户从原始渠道获取；不提交到本仓库
└─ craterstatsGUI/                   # 用户从官方仓库获取；不提交到本仓库
```

### 自动识别模型引用

> Wang, Yiran, Miao Zhuo, and Xiaoran Zhang. 2025. *Automatic Crater Detection Tool for Moon, Mars, and Mercury* (V11) [Data set]. Science Data Bank. CSTR: 31253.11.sciencedb.11985. https://cstr.cn/31253.11.sciencedb.11985

更完整的第三方软件和数据说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 工作流

1. 校验输入并创建独立任务副本；
2. 空 CRATER 自动识坑，非空 CRATER 跳过识坑；
3. 在网页中缩放查看 TIFF + AREA + CRATER 叠加结果；
4. 满意则继续，不满意则在外部 GIS 修改后导入人工修订 CRATER，并二次确认；
5. 生成无年龄拟合的全局 CSFD 图；
6. 将全局图和结构化 CSFD 数据交给 DeepSeek，显示 3 个候选区间及拟合图；
7. 用户选择候选或手工输入 range 后，生成最终定年结果。

区间推荐可在网页中选择两种提示词模式：**直接推荐（zero-shot）**使用原始
`range_selector.txt`，也是默认模式；**专家案例引导（few-shot）**使用
`range_selector_v2.txt`，并在当前样区之前向 DeepSeek 附上 SID55 的全局图、
人工拟合图和完整分箱 JSON。两种模式都只提出候选，最终区间仍需人工确认。
会话的 `llm/range_candidates.json` 和原始响应文件会记录所用 `prompt_mode`。
命令行入口 `python -m crater_dating_agent.agent_main` 可通过
`--prompt-mode zero_shot|few_shot` 指定模式；不指定时保持 zero-shot。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q crater_dating_agent streamlit_app.py
.\.venv\Scripts\python.exe -m pip check
```

## 发布边界

`outputs/`、测试数据、虚拟环境、本机 IDE 配置、`crater_detect_model/` 模型代码与权重、以及本地下载的 `csfd_code/` 均已列入 `.gitignore`。本地 Craterstats GUI 源码带 BSD-3-Clause 许可证；当前撞击坑识别模型目录没有附带许可证，因此在权利状态明确前不得上传到 GitHub。项目通过 PyPI 的 `craterstats==3.6.7` 运行定年核心。第三方依赖的引用、许可证和再发布边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## English quick start

Run `.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py`, open `http://localhost:8501`, select **English**, and enter the three local absolute paths. An empty CRATER file triggers automatic detection; a non-empty one proceeds directly to CSFD dating. Original input files are never modified.
