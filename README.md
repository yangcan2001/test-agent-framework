# 测试 Agent（Plan-and-Solve + ReAct 混合架构）

面向测试场景的自主智能体：读懂需求文档 → 生成测试策略 → 生成并执行 API / UI 用例 → 失败自动分析根因并修复用例后重跑，形成可无人值守的测试闭环。

## 架构

外层 Plan-and-Solve 一次性完成任务分解与策略生成，内层 ReAct 对每个步骤运行 `EXECUTE → REFLECT → DECIDE` 微循环，由模型决策 `continue / retry / fix / abort`。这样规避了纯 ReAct 在长任务里容易跑偏、纯 Plan-and-Solve 不响应执行结果这两个坑。

```
requirement ──> Planner (Plan-and-Solve)
                    │  一次性拆解出 Step 列表
                    ▼
            ReActRunner（逐步骤）
              EXECUTE ──> REFLECT ──> DECIDE
                ▲                        │
                └──── retry / fix ────────┘
```

## 三层闸门

| 层级   | 约束              | 对应失败模式 |
| ---- | --------------- | ------ |
| 任务级  | 全局迭代 + token 上限 | 烧钱     |
| 步骤级  | retry / fix 预算  | 死循环    |
| 执行器级 | 原生超时            | 挂死     |

超时下沉到执行器契约：API 侧 httpx 的 connect / read / write / pool 四级超时，UI 侧 Playwright 页级超时加显式资源释放，`CancellationToken` 贯穿全链路，消除外包线程池导致的假超时。

## 模型不确定性的三重约束

- **能力掩码**：按输入文档类型（openapi / ui / text）禁用不具备执行条件的技能，抑制幻觉用例。
- **预算感知决策重映射**：retry 耗尽降级 fix，fix 耗尽降级 continue。
- **反思三级降级**：模型 → 关键词规则 → 默认决策，模型不可用时任务不中断。

## 声明式技能注册表

技能用 `id / name / description / params_schema / kind / requires` 描述，`kind` 决定是否进反思循环，描述动态渲染进规划 prompt（新增技能不用改 prompt 和调度代码），参数经 JSON Schema 在执行前拦截。

## 记忆层

记忆做成外围能力、经装配层注入，不改内核语义（对齐 `docs/DESIGN-v2.md` 5.3）：

- **长期记忆 `MemoryStore`**：存历史用例 / 缺陷 / 规则 / 元素语义，按语义相似度检索；embedding 走可插拔 `EmbeddingProvider`，真实场景接 API，离线用特征哈希 `HashEmbeddingProvider` 降级，支持 JSON 文件持久化。
- **短时记忆 `ContextCompressor`**：上下文超阈值时蒸馏成摘要，模型不可用则离线降级。
- **两个检索时机**：`Planner` 规划时召回历史用例，`Reflector` 反思时召回相似缺陷；任务结束把通过步骤沉淀为用例、失败步骤沉淀为缺陷，形成读写闭环。

## 环境

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -r requirements-dev.txt   # 含运行时依赖 + pytest
```

> UI 执行器用到 Playwright 浏览器，需额外下载内核（仅跑 API 用例或离线测试可跳过）：  
> `playwright install chromium`

## 运行

离线跑闭环（无需 API Key）：

```bash
PYTHONPATH=src python examples/demo.py
```

跑测试（完全离线）：

```bash
pytest -q
```

接真实模型（OpenAI 兼容协议，chat / vision / embedding 同一 base_url）：

```bash
cp .env.example .env   # 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
uvicorn test_agent.app:app --reload
# POST /run  {"requirement": "...", "document_kind": "openapi"}
```

## 目录

```
src/test_agent/
  agent.py       顶层编排
  planner.py     外层 Plan-and-Solve
  react.py       内层 ReAct 微循环 + 决策重映射
  reflection.py  反思三级降级
  executors.py   API / UI 执行器（超时契约）
  gates.py       三层闸门
  skills.py      声明式技能注册表
  memory.py      记忆管理（长期 RAG + 短时压缩）
  llm.py         OpenAI 兼容客户端 + 离线替身
  app.py         FastAPI 入口
tests/           离线单测（闸门、决策重映射、执行器超时、错误分类、闭环）
```

模块边界用 Protocol 声明、装配层注入，模型 / 执行器 / 浏览器都可替换为替身，测试套件完全离线运行。
