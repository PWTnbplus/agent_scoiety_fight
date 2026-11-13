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

## 真实 API（默认不执行）

通用兼容接口沿用旧项目中的 `LLM_*` 环境变量。Kimi2.6 则使用本项目内的独立适配器，固定 `kimi-k2.6`、`https://token.ctflow.cn/v1`、`temperature=0.6`、零重试和本地成本上限；密钥仅从显式 key 文件读取。

```powershell
python -m mini_science.cli check-api --provider kimi26 --allow-paid-api --max-calls 1 --kimi26-key-file E:\\master_exp\\nature_prj1_cal\\from_llm_to_agent\\api_key\\kimi\\kimi-k2.6.txt --kimi26-max-cost-usd 0.10
```

没有 `--allow-paid-api` 时，程序在发送请求前拒绝执行。真实检查最多一次；当前工作阶段没有自动发起付费调用。详细来源和迁移差异见 [docs/API_PROVENANCE.md](docs/API_PROVENANCE.md)。

## 研究解释边界

IG 是在冻结的四个候选机制集合上计算的实验辨识价值。`B-A`、`C-D` 和 `C-B` 只在此合成任务上提供探索性对照；它们不等同于人类科学价值、未知规律发现或普适的 Society 优势。
