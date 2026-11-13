# Mini Science Society

一个可审计的合成科学问题选择 MVP：4 个可计算世界、4 个竞争机制、8 个实验动作、A/B 单 Agent、C/D 规律传递阻断、3-Agent 协作和竞争。目标是验证工程闭环与探索性信号，不把 Mock 或四个案例包装成科学证明。

## 安全边界

默认 provider 是 `mock`，不会联网。真实 API 必须显式使用 `--allow-paid-api`。不要复制 `.env` 或密钥。

旧 API 来源：`E:\master_exp\nature_prj1_cal\from_llm_to_agent`。迁移审计见 [docs/API_PROVENANCE.md](docs/API_PROVENANCE.md)。

## 安装与离线运行

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m mini_science.cli generate --config config/pilot.json
python -m mini_science.cli validate-worlds --config config/pilot.json
python -m mini_science.cli smoke --provider mock --world W001
python -m mini_science.cli pilot --provider mock --worlds all --repeats 1
```

运行结果写入 `runs/`，报告写入对应 run 目录；Mock 报告会明确标记 `NON_EVIDENCE`。

## v2 离线 Gate 0

v2 使用独立的 `data/worlds_v2_dev`、`private/worlds_v2_dev` 和新 run ID，
不会改写旧 `data/worlds` 或 `runs/mock_*`：

```powershell
python -m mini_science.cli generate --config config/pilot_v2.json
python -m mini_science.cli validate-worlds --config config/pilot_v2.json
python -m mini_science.cli plan --config config/pilot_v2.json
python -m mini_science.cli pilot --config config/pilot_v2.json --provider behavioral-mock --behavioral-scenario transfer_sensitive --worlds all --repeats 1
python -m pytest -q
```

`behavioral-mock` 支持 `constant`、`transfer_sensitive`、`transfer_ignored`、
`bad_stage1`、`bad_final` 和 `citation_leak`；所有结果都标记为
`NON_EVIDENCE` / `TEST_FIXTURE`。每个 v2 run 保存
`run_plan.jsonl`、`call_ledger.jsonl`、`attempt_results.jsonl`、
`events.jsonl`、`results.csv`、`paired_deltas.csv` 和 `report.md`。

Oracle 审计命令：

```powershell
python -m mini_science.cli audit-oracle --config config/pilot_v2.json --output reports/v2_oracle_audit.csv
```

## V3 离线 Gate 1

V3 已把 Kimi2.6 的调用协议、响应合约、角色探针和持久化预算门禁复制到
本项目内；运行时不依赖旧项目源码，也不复制密钥。默认配置
`config/real_gate_v3.json` 是 `NOT_AUTHORIZED`、零真实调用额度，且只允许
后续显式授权的 Kimi2.6 分阶段运行。

```powershell
python -m pytest -q
python -m mini_science.cli validate-worlds --config config/pilot_v2.json
python -m mini_science.cli audit-oracle --config config/pilot_v2.json --output reports/v2_oracle_audit.csv
python -m mini_science.cli pilot --config config/pilot_v2.json --provider behavioral-mock --behavioral-scenario transfer_sensitive --worlds W001 --conditions A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK --run-dir runs/v3_offline_behavioral_control
```

结果见 `reports/v3/`：`offline_preflight.md`、`cheap_baselines.csv`、
`go_no_go.md` 以及实际真实调用前保持 `NOT_RUN` 的合同、探针和 pilot
报告。只有在配置授权、`--allow-paid-api`、provider/model、阶段范围、世界/
condition 范围和累计调用/成本门禁全部通过后，真实请求才可能发送；超时或
失败尝试也会持久化计数，且不自动重试。完整 staged protocol 见
`docs/V3_REAL_PILOT_PROTOCOL.md`。

真实调用前必须由操作员执行一次带确认短语的 `authorize-real`，再按
`check-api` → `probe-role` → `pilot` 显式推进阶段；Codex 不会自行生成授权
记录或把 `NOT_AUTHORIZED` 改成 `AUTHORIZED`。

真实 API 仍默认 `NOT_RUN`。付费前只允许在用户明确给出模型、总费用上限
和执行授权后运行一条 `check-api`；`probe-role` 是之后的单角色结构化输出
检查，不应绕过 Gate 0。

## 真实 API（默认不执行）

通用兼容接口沿用旧项目中的 `LLM_*` 环境变量。Kimi2.6 则使用本项目内的独立适配器，固定 `kimi-k2.6`、`https://token.ctflow.cn/v1`、`temperature=0.6`、零重试和本地成本上限；密钥仅从显式 key 文件读取。

```powershell
python -m mini_science.cli check-api --provider kimi26 --allow-paid-api --max-calls 1 --kimi26-key-file E:\\master_exp\\nature_prj1_cal\\from_llm_to_agent\\api_key\\kimi\\kimi-k2.6.txt --kimi26-max-cost-usd 0.10
```

没有 `--allow-paid-api` 时，程序在发送请求前拒绝执行。真实检查最多一次；当前工作阶段没有自动发起付费调用。详细来源和迁移差异见 [docs/API_PROVENANCE.md](docs/API_PROVENANCE.md)。

## 研究解释边界

IG 是在冻结的四个候选机制集合上计算的实验辨识价值。`B-A`、`C-D` 和 `C-B` 只在此合成任务上提供探索性对照；它们不等同于人类科学价值、未知规律发现或普适的 Society 优势。
