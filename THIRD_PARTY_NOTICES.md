# Third-Party Notices / 第三方声明

This repository integrates external software and a crater-detection data tool through local configuration. The third-party source code, model weights, and data are not included in this repository unless their original licence expressly permits redistribution.

本仓库通过本机配置集成第三方软件与撞击坑自动识别工具。除非原始许可证明确允许再发布，本仓库不包含第三方源码、模型权重或数据。

## CraterstatsGUI / Craterstats

- Upstream project: [ggmichael/craterstatsGUI](https://github.com/ggmichael/craterstatsGUI)
- Copyright and licence: upstream project, [BSD-3-Clause](https://github.com/ggmichael/craterstatsGUI/blob/main/LICENSE.txt)
- Use in this project: CSFD plot generation and crater-age calculation through the Craterstats command-line/Python capability. This project does not modify or redistribute the upstream CraterstatsGUI source tree.

Users who obtain, copy, modify, or redistribute CraterstatsGUI must comply with its complete BSD-3-Clause licence, including its copyright notice, conditions, and disclaimer. The upstream repository remains the authoritative source for its installation and licence terms.

## Automatic Crater Detection Tool for Moon, Mars, and Mercury

- Original data/tool citation:

  > Wang, Yiran, Miao Zhuo, and Xiaoran Zhang. 2025. *Automatic Crater Detection Tool for Moon, Mars, and Mercury* (V11) [Data set]. Science Data Bank. CSTR: 31253.11.sciencedb.11985. https://cstr.cn/31253.11.sciencedb.11985

- Original record: [Science Data Bank / CSTR record](https://cstr.cn/31253.11.sciencedb.11985)
- Use in this project: the workflow invokes a user-configured, locally installed automatic crater detection tool when the supplied `CRATER_<id>.shp` is empty.

The automatic-detection tool, its source code, model weights, runtime environment, and any training or input data are **not distributed** with this repository. They must be obtained from the original publisher and used according to the applicable licence, terms of use, and attribution requirements. A citation alone does not grant a redistribution licence.

## Project boundary

This repository contains only the integration layer, Streamlit application, tests, configuration templates, and documentation created for the Lunar Crater Intelligent Dating System. It deliberately excludes local directories such as `wangyiranCode/`, `csfd_code/`, `outputs/`, model weights, test datasets, API keys, and local environment files.