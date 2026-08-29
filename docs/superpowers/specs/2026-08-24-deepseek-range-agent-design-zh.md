# 基于 DeepSeek 的 CSFD 拟合区间选择智能体设计

## 一、建设目标

在现有“不依赖大模型的 Craterstats 单次定年工具”基础上，新增一个可在
PyCharm 终端中运行的智能体流程，实现：

1. 输入已经识别好的 CRATER Shapefile、配套 AREA Shapefile 和溯源 TIFF；
2. 首先生成不包含年龄拟合、也不限制直径区间的全局差分 CSFD 图；
3. 将确定性的数据处理和定年能力注册为 DeepSeek 可调用工具；
4. 将 pseudo-log 分箱后的结构化 CSFD 数据交给 DeepSeek 分析；
5. 由 DeepSeek 给出最多三个候选拟合直径区间；
6. 暂停流程，等待人工选择、修改或者取消；
7. 只有人工明确确认后，才能执行最终的 buffered-Poisson 定年；
8. 保存状态变化、模型响应、人工确认和生成文件，确保流程可追溯、可复现。

本阶段暂不接入王艺燃撞击坑自动识别模型，也不开发图形交互界面。终端流程测试
稳定后，再继续完成自动识别和 GUI 封装。

## 二、必须保持兼容的现有功能

现有命令：

```text
python -m crater_dating_agent
```

继续用于输入人工确定的 range 并执行一次确定性定年。本次开发不能破坏它现有的
参数和输出格式。

科学配置继续保持：

- 天体：Moon；
- 年代学函数：Neukum (1983)；
- 地质年代系统：Guo et al. (2024)；
- 表示方式：differential；
- 分箱方式：pseudo-log；
- 拟合方式：`b-poisson`；
- 拟合数据符号：`fo`；
- 全局数据图层：`name=plot 2,type=data,psym=o`，不设置 range；
- 平衡函数：None。

本阶段不修改 `wangyiranCode/`、`csfd_code/` 和现有撞击坑检测行为。

## 三、总体架构

采用“轻量 Python 状态机 + OpenAI 兼容 DeepSeek 客户端”的结构，不引入
LangChain 或 LangGraph。

所有确定性功能仍是普通 Python 服务。工具注册表只负责把选定功能转换为大模型
Function Calling 所需的 JSON Schema。整个流程顺序由 Python 状态机控制，而不是
交给大模型自由决定。

PyCharm 中新增独立运行入口：

```text
Module name: crater_dating_agent.agent_main
```

原有单次定年入口保持不变。

## 四、完整运行流程

```text
输入 CRATER + AREA + TIFF
  → validate_case
  → generate_global_csfd
  → get_csfd_summary
  → DeepSeek 工具调用与区间分析
  → Python 校验并对齐候选区间
  → awaiting_confirmation
  → 人工选择、修改或取消
  → 写入人工确认记录
  → run_confirmed_dating
  → 输出最终双 overplot CSFD 图和年龄结果
```

第一次运行的全局 Craterstats 配置只有一个数据 overplot：

```text
source=<CRATER文件>,name=plot 2,type=data,binning=pseudo-log,psym=o
```

其中不包含 `range`，也不包含拟合 overplot，因此不显示拟合年龄。本阶段只要求
Craterstats 生成 PNG、配置文件和日志。

结构化分箱数据不从最终定年 CSV 中提取，因为该 CSV 只保存拟合结果。系统直接
调用 Craterstats 自身的 `Cratercount` 和 `Spatialcount`，从相同的 CRATER/AREA
文件生成 pseudo-log 分箱数据。这样能够复用 Craterstats 的直径边界、缓冲区比例、
面积和差分密度算法，避免重复实现一套可能不一致的科学计算。

人工确认后，调用已有单次定年服务生成最终图。最终图包含两个 overplot：

1. 人工确认 range 的 `b-poisson` 拟合；
2. 不设置 range 的全局 `plot 2`。

## 五、大模型工具注册表

每个工具统一声明：工具名、说明、参数 JSON Schema、执行函数、允许调用的状态、
是否改变会话状态。

### 1. `validate_case`

检查：

- CRATER 和 AREA 文件名是否匹配；
- `.shp/.shx/.dbf/.prj` 是否齐全；
- TIFF 是否存在；
- case ID 是否有效；
- CRATER 数据是否包含撞击坑。

返回绝对路径、case ID、撞击坑数量及输入文件元数据。

允许状态：`created`。

### 2. `generate_global_csfd`

生成并调用只有一个无 range 数据 overplot 的 Craterstats 配置，返回全局 PNG、
配置文件和日志路径。

允许状态：`created`、`inputs_validated`。

### 3. `get_csfd_summary`

调用 Craterstats 原生 pseudo-log 分箱逻辑，返回：

- 统计面积和周长；
- 总撞击坑数量；
- 完整直径范围；
- 每个非空 bin 的下限、上限和中心直径；
- 加权坑数、事件坑数和累积坑数；
- 差分密度及误差。

允许状态：`overview_ready`、`analyzing`。

### 4. `get_session_state`

返回经过脱敏的会话状态、文件路径、警告和确认状态。不得返回 API Key 或环境变量。

允许状态：全部状态。

### 5. `run_confirmed_dating`

使用人工确认的精确 range 调用现有确定性单次定年服务。执行前重新检查：

- `confirmation.json` 是否有效；
- 确认记录是否属于当前会话；
- 输入文件指纹是否一致；
- 确认 range 是否与将要执行的 range 一致。

允许状态：`confirmed`。人工确认前，控制器不会将该工具暴露给模型；即使绕过
控制器直接调用，工具本身也必须拒绝执行。

## 六、DeepSeek API 适配

使用 DeepSeek 官方 OpenAI 兼容接口：

```text
DEEPSEEK_API_KEY       必填，不提供默认值
DEEPSEEK_BASE_URL      默认 https://api.deepseek.com
DEEPSEEK_MODEL         默认 deepseek-v4-flash
```

如果用户账户支持实验模型，可以在环境变量中覆盖：

```text
DEEPSEEK_MODEL=deepseek-v4-flash-vision-exp
```

如果指定模型不可用，程序必须给出明确错误，不得暗中切换到其他模型。会话和已经
生成的全局图需要保留，以便修改模型配置后继续运行。

DeepSeek 思考模式进行多轮工具调用时，需要完整回传 `reasoning_content`。客户端
必须遵循该协议。模型产生的工具参数一律视为不可信输入，必须在本地校验后才能
执行。

第一版只向模型发送文本和 JSON 形式的结构化 CSFD 数据，不上传 PNG。PNG 只供
人工查看。

API Key 仅从环境变量读取，不得写入：

- 源代码；
- 提示词；
- 会话状态；
- 工具调用记录；
- 异常信息；
- 测试输出。

## 七、候选 range 返回格式

DeepSeek 的任务是寻找可能适合生产函数拟合的连续直径区间，需要考虑：

- 小直径端可能存在识别不完整；
- 大直径端可能统计过于稀疏；
- bin 是否连续；
- 数据误差和波动；
- 次生坑、重 resurfacing 等可能造成的异常；
- 数据是否大体符合生产函数趋势。

DeepSeek 不负责直接计算或确认最终年龄。

模型必须返回以下语义结构的 JSON：

```json
{
  "candidates": [
    {
      "range_min_km": 0.06,
      "range_max_km": 0.2,
      "confidence": "high",
      "reason": "基于结构化数据的简明理由",
      "risks": ["具体风险说明"]
    }
  ],
  "overall_observation": "对全局直径分布的简要描述",
  "needs_human_review": true
}
```

要求：

- 返回一至三个候选；
- `confidence` 只能为 `high`、`medium` 或 `low`；
- 如果没有可靠区间，可以返回空候选；
- 空候选只能进入人工输入或取消，不能自动定年。

Python 收到候选后必须：

1. 检查上下限为有限正数，并且上限大于下限；
2. 将上下限映射到实际 pseudo-log bin 边界；
3. 重新计算区间内事件坑数和非空 bin 数；
4. 合并对齐后完全相同的重复候选；
5. 拒绝超出实测直径范围的候选；
6. 为每个候选增加确定性警告。

默认技术阈值：

```text
至少 20 个撞击坑事件
至少 3 个非空 pseudo-log bins
```

该阈值只是程序安全默认值，不表示普遍适用的科学结论。阈值应当可以配置。低于
阈值时默认禁止定年，但允许人工覆盖；覆盖前必须进行第二次明确确认，并把警告
写入会话记录。

## 八、会话状态与人工确认

会话状态包括：

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

只允许预先声明的状态转换。失败不能删除已经生成的文件。

对于认证失败、限流、网络超时或模型不可用等可恢复 API 错误，会话返回
`overview_ready`，用户调整环境变量后可以继续分析，不需要重复生成全局图。

在 `awaiting_confirmation` 状态，终端显示：

- 全局 PNG 路径；
- 每个候选的精确对齐 range；
- 事件坑数和非空 bin 数；
- DeepSeek 给出的理由、风险和置信度；
- Python 产生的技术警告。

人工选项：

```text
1 / 2 / 3   选择候选
e           手工输入其他区间
q           取消，不执行最终定年
```

选择或手工输入后，系统再次显示对齐后的精确 bin 边界。只有输入 `y` 才会写入
确认并执行最终定年。如果候选低于技术阈值，需要先完成额外警告确认。

`confirmation.json` 保存：

- schema 版本和 session ID；
- 输入文件指纹；
- 原始选择；
- 对齐后的精确 range；
- 阈值警告；
- 确认时间；
- 候选选择或人工输入等确认方式。

不保存 API Key，也不推断或记录人工身份。

## 九、输出目录

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

文件统一使用 UTF-8。状态文件尽量采用临时文件加原子替换，避免程序中断产生半个
JSON。记录内容包括：schema 版本、带时区的时间、智能体版本、Craterstats 版本、
模型名称、工具 schema 版本、输入文件大小和修改时间以及新生成文件路径。

保存的 `reasoning_content` 仅限继续完成当前工具调用协议所需的数据，不把隐藏
推理内容当作科学依据。面向用户的科学解释只使用模型明确输出的 `reason` 和
`risks`。

## 十、错误处理

- 缺少 `DEEPSEEK_API_KEY`：在访问网络前停止，提示配置方法，保留已有全局图；
- API 认证失败、限流、超时或模型不可用：写入脱敏错误，会话保持可恢复；
- 工具名称不存在或参数不合法：拒绝执行，不猜测模型意图；
- 模型最终 JSON 格式错误：只允许一次受约束的格式修复请求；
- Craterstats 失败：保留配置、日志和失败状态；
- 候选包含 NaN、Infinity 或超出数据范围：拒绝该候选；
- 确认记录缺失或与输入不一致：拒绝最终定年；
- 用户取消：写入 `cancelled`，不生成最终年龄拟合。

## 十一、测试策略

开发继续采用测试驱动开发。

### 单元测试

- 全局配置只有一个 `data` overplot，并且没有 range；
- 结构化 bin 与独立测试数据一致；
- 工具 JSON Schema 和不同状态下的工具过滤；
- 拒绝不存在的工具和不合法参数；
- range 对齐、去重、坑数统计和阈值判断；
- 所有合法与非法状态转换；
- 人工确认门、输入指纹不一致、阈值覆盖和取消；
- DeepSeek 消息序列化和 `reasoning_content` 回传；
- API 错误与日志脱敏；
- JSON 格式错误只能触发一次修复。

### SID9 集成测试

只使用用户指定的 CRATER、AREA 和 TIFF。真实调用 Craterstats 生成全局图和结构化
数据，DeepSeek 响应使用假的固定数据，避免消耗 API。

测试必须确认：人工确认前不存在最终年龄 CSV/JSON；人工确认后才生成包含拟合
range 和无 range `plot 2` 的最终结果。

### 可选在线测试

只有用户明确要求并且设置了 `DEEPSEEK_API_KEY` 时，才运行一次真实 API 测试。
在线测试使用单独标记，默认测试套件不执行，也不得打印 API Key。

## 十二、验收标准

满足以下条件后，本阶段才算完成：

1. 原有确定性单次定年 CLI 保持兼容并通过全部测试；
2. PyCharm 智能体入口首先生成不显示年龄的全局图；
3. DeepSeek 接收 Craterstats 原生 pseudo-log 结构化数据；
4. DeepSeek 只能调用当前状态允许的注册工具；
5. 系统展示一至三个经过本地校验的候选，或者明确的无候选结果；
6. 没有有效人工确认时，任何路径都无法执行最终定年；
7. 最终图同时包含确认 range 的拟合和无 range 全局数据；
8. API 失败后可以复用已有全局结果继续会话；
9. API Key 不写入磁盘或测试输出；
10. 单元测试和 SID9 集成测试全部通过，默认测试不依赖真实 API。

## 十三、后续阶段

本设计暂不包括：

- 从 AREA 和 TIFF 自动调用王艺燃模型生成 CRATER；
- 将 PNG 上传给多模态模型分析；
- 独立于大模型的自动 range 搜索与科学评分；
- 桌面或 Web 图形界面；
- 多区域批量处理。

## 十四、DeepSeek 官方资料

- OpenAI 兼容调用：
  https://api-docs.deepseek.com/guides/function_calling/
- Tool Calls：
  https://api-docs.deepseek.com/guides/tool_calls/
- Thinking Mode：
  https://api-docs.deepseek.com/guides/thinking_mode/

