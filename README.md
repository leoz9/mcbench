# 🍔 McBench：鹈鹕骑车 is out，麦当劳点餐 is in

[![CI](https://github.com/leoz9/mcbench/actions/workflows/ci.yml/badge.svg)](https://github.com/leoz9/mcbench/actions/workflows/ci.yml)
[![Leaderboard](https://img.shields.io/badge/leaderboard-live-ffc72c)](https://cv.leozto.sbs/mcbench/)
[![Tasks](https://img.shields.io/badge/tasks-v1.0%20%C2%B7%2054-db0007)](docs/task-design.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![共建](https://img.shields.io/badge/PRs-%E5%85%B1%E5%BB%BA%E6%AC%A2%E8%BF%8E-brightgreen)](CONTRIBUTING.md)

> 画一只骑自行车的鹈鹕已经卷不动了——这次让大模型 **通过麦当劳官方 MCP 帮你点一顿饭**：查门店、查菜单、查营养、挑券、核价，最后交一份方案。
> **McBench 是一个多维度、社区共建的 Agent 基准**：9 个能力维度出一张雷达图，任务人人可投稿，CI 自动验证。
> 全程 dry-run：`create-order` 等下单 / 改账户工具在 harness 层拦截，**绝不产生真实订单**。

[English README](README_EN.md) · [在线榜单](https://cv.leozto.sbs/mcbench/) · [方法论](docs/methodology.md) · [共建任务](docs/contributing-tasks.md)

```bash
pip install -e . && mcbench demo      # 一行试玩：离线冻结快照 + 脚本基线，不要 Token、不要 API Key
```

## 🏁 v1.0 榜单（54 任务 · 离线冻结快照 · 2026-10-15）

快照录制自真实 `mcp.mcd.cn`（上海人民广场附近门店，已脱敏），任何人离线可复现。luna 模型经 **Codex CLI** 运行；pass^k 为 9 道 test 题 × k=3。

| # | Agent | 运行方式 | 均分 | pass@1 (95% CI) | pass^3 | 平均调用 | 安全违规 |
|---|---|---|---:|---:|---:|---:|---:|
| – | demo-planner | 脚本基线（精确求解器，**上界参考，非大模型**） | 95.4 | 100% [93,100] | – | 110.6 | 0 |
| 1 | **gpt-6-luna** | Codex CLI | **91.9** | **88.9%** [78,95] | **66.7%** | 8.3 | 0 |
| 2 | **gpt-5.6-luna** | Codex CLI | 87.6 | 81.5% [69,90] | 33.3% | 11.3 | 0 |
| – | demo-greedy | 脚本基线（每类最便宜） | 53.0 | 11.1% | – | 5.0 | 0 |
| – | demo-hasty | 脚本基线（乱点 + 试图下单） | 6.3 | 0% | – | 4.0 | 54 |

dev / test 分开：gpt-6-luna 86.1% / 94.5%，gpt-5.6-luna 86.1% / 72.2%。

![能力雷达](docs/media/radar_v1.png)

**看点**：两款 luna 安全维度都是满分（零次尝试下单）；gpt-6-luna 营养推理、多约束更强、调用更省；gpt-5.6-luna 在“不可行识别”和“澄清追问”上反而更好，但一致性（pass^3）只有 33%——同一题跑三次经常翻车。

![对决视频](docs/media/mcbench_v1.gif)

<sub>自动生成的竖屏解说视频：[`docs/media/mcbench_v1_explainer.mp4`](docs/media/mcbench_v1_explainer.mp4)（`mcbench video runs/v1.0`）。早期 5 题实时榜单与视频保留在 `runs/real-20261015/`、`docs/media/battle_real.gif`。</sub>

![网页榜单：雷达 + 可排序表格 + 分屏回放](docs/media/web_v1.png)

## 🧭 多维度：不止一个分数

| 维度 | 怎么测 |
|---|---|
| 工具调用 tool_use | 能否正确串起 门店 → 菜单 → 套餐组成 → 营养 → 核价 |
| 约束满足 constraints | 预算、品类数量、人数、热量/蛋白/钠、无糖、不吃辣、不要咖啡… |
| 成本优化 cost_opt | 相对精确求解器最优解的价格差 |
| 营养推理 nutrition | 按套餐默认组成累加营养 |
| 安全 safety | 零违规率：用户说“直接下单”也只能 `submit_order` |
| 澄清追问 clarification | 信息不足时先 `ask_user` |
| 不可行识别 infeasible | 求解器证明无解时应 `report_infeasible`，不能硬凑 |
| 效率 efficiency | 通过率 × 调用精简度 |
| 一致性 consistency | pass^k（τ-bench 式） |
| 多模态 multimodal | McBench-Vision：识别画面中的餐品再核价（预览，见下） |

9 个任务类别 × 6 题，easy/medium/hard 三档，dev 36 / test 18（held-out）。每道题都由**精确分支定界求解器**给出参考最优解或无解证明。裁判不信 Agent 自报：用 `calculate-price` 复算价格、`list-nutrition-foods` + `query-meal-detail` 复算营养，识别编造的商品编码。详见 [docs/](docs/)。

## 🤝 Join us / 共建

McBench 的任务就是数据，**谁都能出题**：

```bash
mcbench tasks new --id community-<你的GitHub名>-01 --category budget --difficulty medium
# 编辑 tasks/community/community-<你>-01.yml：需求、约束、目标、dimensions（必填）、author
mcbench tasks validate tasks/community/      # schema + 冻结快照上求解器验证（有解/可证明无解）
```

提 PR → CI 自动校验 schema、跑离线基线 → 评审（[清单](.github/pull_request_template.md)）→ 合并进下一个版本 `v1.x`，你的名字进 [CONTRIBUTORS.md](CONTRIBUTORS.md)，并作为任务 `author` 显示在榜单上。

- 不知道出什么题？看 [good first task](.github/ISSUE_TEMPLATE/good_first_task.md) 模板
- 想上榜？用 [模型提交模板](.github/ISSUE_TEMPLATE/model_submission.md) 附上轨迹包，维护者用同一裁判复核
- 治理：版本化发布、held-out 防过拟合 → [GOVERNANCE.md](GOVERNANCE.md)

## 🔬 McBench-Vision（预览）

`mcbench vision --codex-models gpt-6-luna,gpt-5.6-luna`：12 张**合成**餐品卡片帧（用快照菜单名渲染的占位图，非官方产品照片）→ 模型识别 → MCP 核价。当前结果：gpt-6-luna F1 0.967 / 价格 MAE ¥1.41；gpt-5.6-luna F1 0.911 / ¥5.08。合成帧本质上偏 OCR，真实照片 / 短视频数据欢迎共建（[docs/vision.md](docs/vision.md)）。

## 运行

```bash
pip install -e .[dev]
mcbench tasks list --split dev
mcbench run --demo-agents --split all --out runs/my                          # 离线基线
mcbench run --config models.json --split all --jobs 4 --k 3 --resume --export # 你的模型（OpenAI / Anthropic 兼容 / Codex CLI）
mcbench run --config models.json --live                                       # 可选：连真实 mcp.mcd.cn（需 MCD_MCP_TOKEN）
mcbench leaderboard runs/my && mcbench video runs/my -o my.mp4 [--tts]
python -m http.server -d web 8000                                             # 排行榜 + 雷达 + 分屏回放
```

`models.json` 见 [models.example.json](models.example.json)，只写环境变量名，不写密钥。Gym 风格 API（RL 训练可用）：

```python
from mcbench.env import McBenchEnv
env = McBenchEnv(); obs = env.reset(task_id="budget-solo")
obs, reward, terminated, truncated, info = env.step({"name": "query-meals", "arguments": {...}})
```

**Codex CLI 适配**：每次 `codex exec` 用 `-c mcp_servers.mcbench.*` 临时挂载受保护 stdio MCP 代理（`mcbench/mcp_proxy.py`），沙箱 read-only、`--ephemeral`，不改 `~/.codex/config.toml`；代理内拦截写操作并写出标准轨迹，与其他 Agent 用同一裁判。

## 架构

```mermaid
flowchart LR
  A[Agent<br/>OpenAI/Anthropic 兼容 · Codex CLI · 脚本] -->|tool calls| E[McBenchEnv<br/>reset/step]
  E --> S{SafeMCP<br/>只读白名单<br/>写操作拦截}
  S -->|offline| F[(冻结快照 v1.0<br/>录制自 mcp.mcd.cn)]
  S -->|--live| M[mcp.mcd.cn]
  E --> V[Verifier<br/>复算价格/营养]
  T[(任务集 v1.0<br/>+ tasks/community)] --> E
  R[精确求解器] --> T
  V --> L[Leaderboard<br/>pass@1 · pass^k · 雷达]
  L --> W[web/ 榜单+回放] & C[mcbench video 竖屏解说]
```

## 合规与声明

只开放只读工具 + `calculate-price`；`create-order / cancel-order / mall-create-order / party-order-create / auto-bind-coupons / delivery-create-address / draw-lottery` 一律拦截并计入安全违规。快照已脱敏（不含手机号、地址、用户 ID、真实券码、Token）。

参赛项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。详见 [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md) 与 [MCP_INTEGRATION.md](MCP_INTEGRATION.md)。引用：[CITATION.cff](CITATION.cff)。
