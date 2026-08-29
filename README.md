# 月球撞击坑智能定年系统 / Lunar Crater Intelligent Dating System

本项目把撞击坑自动识别、人工叠加复核、Craterstats CSFD 定年和 DeepSeek 多模态拟合区间推荐整合为一个本机 Streamlit 应用。所有任务使用独立输出目录，用户原始 AREA、CRATER 和 TIFF 不会被修改。

## 输入要求

- `AREA_<编号>.shp`：用户绘制的定年区域；
- `CRATER_<编号>.shp`：与 AREA 同步建立、字段正确的撞击坑文件，可以为空；
- 原始 GeoTIFF。

AREA 与 CRATER 的编号必须完全相同，且 Shapefile 目录中必须包含 `.shp`、`.shx`、`.dbf` 和 `.prj`。空 CRATER 会调用撞击坑自动识别模型；有坑的 CRATER 会跳过识别并直接进入定年。

## 在 PyCharm 中运行

1. 打开项目目录：`E:\DiHuaSuo\2026\paper\csfd_agent\agent_build`。
2. 选择项目解释器：`E:\DiHuaSuo\2026\paper\csfd_agent\agent_build\.venv\Scripts\python.exe`。
3. 新建 **Python** Run/Debug Configuration：
   - Script path：`E:\DiHuaSuo\2026\paper\csfd_agent\agent_build\.venv\Scripts\streamlit.exe`
   - Parameters：`run streamlit_app.py`
   - Working directory：`E:\DiHuaSuo\2026\paper\csfd_agent\agent_build`
4. 运行后打开 `http://localhost:8501`。

也可以在 PyCharm Terminal 中运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

DeepSeek 密钥优先读取环境变量 `DEEPSEEK_API_KEY`。如果没有设置，页面会显示密码输入框；输入值只保存在当前 Streamlit 进程内存，不写入状态、日志或配置文件。

## 本机运行环境

默认配置为：

```text
ARCPY_PYTHON=C:\Python27\ArcGIS10.8\python.exe
CRATER_MODEL_PYTHON=C:\ProgramData\Anaconda3\envs\crater_model_py39\python.exe
CRATER_MODEL_DIR=<项目目录>\wangyiranCode
```

页面“高级设置”允许按本机实际位置修改这些路径。两个已经验证的识别核心脚本保持原有算法和接口，由薄编排层通过安全子进程参数调用。

## 工作流

1. 校验输入并创建独立任务副本；
2. 空 CRATER 自动识坑，非空 CRATER 跳过识坑；
3. 在网页中缩放查看 TIFF + AREA + CRATER 叠加结果；
4. 满意则继续，不满意则在外部 GIS 修改后导入人工修订 CRATER，并二次确认；
5. 生成无年龄拟合的全局 CSFD 图；
6. 将全局图和结构化 CSFD 数据交给 DeepSeek，显示 3 个候选区间及拟合图；
7. 用户选择候选或手工输入 range 后，生成最终定年结果。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q crater_dating_agent streamlit_app.py
.\.venv\Scripts\python.exe -m pip check
```

## 发布边界

`outputs/`、测试数据、虚拟环境、本机 IDE 配置、`wangyiranCode/` 模型代码与权重、以及本地下载的 `csfd_code/` 均已列入 `.gitignore`。本地 Craterstats GUI 源码带 BSD-3-Clause 许可证；当前撞击坑识别模型目录没有附带许可证，因此在权利状态明确前不得上传到 GitHub。项目通过 PyPI 的 `craterstats==3.6.7` 运行定年核心。

## English quick start

Run `.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py`, open `http://localhost:8501`, select **English**, and enter the three local absolute paths. An empty CRATER file triggers automatic detection; a non-empty one proceeds directly to CSFD dating. Original input files are never modified.
