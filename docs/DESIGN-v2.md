# test-agent 二次开发设计（v2）

## 1. 现状与定位

当前 test-agent 是一个「通用控制循环框架」：外层 Plan-and-Solve 一次性拆解任务，
内层 ReAct 微循环跑 EXECUTE → REFLECT → DECIDE，配三层闸门（任务级/步骤级/执行器级）
和三重约束（能力掩码、预算感知决策重映射、反思三级降级）。技能走声明式注册表，
模块边界用 Protocol 声明、装配层注入，29 个单测全离线跑通。

对照 GitHub 上 Hercules、QuAIA、蚂蚁 Test-Agent、AgentQA 等项目的调研，这套框架的
「可靠性内核」有竞争力，短板集中在三块：

1. 测试专用感知缺失——没有 Gherkin 输入、DOM 蒸馏、元素自愈定位，导致「能跑闭环但
   跑不深真实测试场景」。
2. 生态接入空白——没有 MCP 工具接入、RAG 知识库、标准报告产物，接不进 CI/CD 和测试
   管理平台。
3. 可观测单薄——只有 trace JSON 落盘，没有 JUnit/Allure/HTML 这些测试行业默认格式。

## 2. 二次开发定位

**内核不动，外围补齐。** 保留「三层闸门 + 三重约束 + Protocol 注入」这套可靠
性内核，在外围补上输入理解层、测试感知层、记忆层、生态接入层、报告层，把框架从
「能跑闭环」推到「能落地真实测试」。

## 3. 补足项与优先级

| 优先级 | 补足项 | 对应短板 | 理由 |
| --- | --- | --- | --- |
| P0 | 感知层（DOM 蒸馏 + 元素自愈） | 测试专用感知 | 测试 Agent 与通用 Agent 的分水岭，Hercules 核心壁垒 |
| P0 | 输入层（Gherkin/自然语言） | 测试专用感知 | 决定可用性，业务方不会写结构化任务 |
| P1 | 记忆层（RAG + 上下文压缩） | 生态/复用 | 历史用例、缺陷、元素语义复用，QuAIA 重投入方向 |
| P1 | 报告层（JUnit/Allure/HTML） | 可观测 | CI/CD 与测试平台硬门槛，投入小见效快 |
| P2 | MCP 工具适配器 | 生态接入 | 接 Jira/禅道/TAPD 等外部系统 |
| P3 | 多 Agent 编排 | — | 暂缓，见 4.6 |

## 4. 设计原则（不变量）

所有新增模块必须遵守，是「内核不动」的具体化：

1. **内核不破坏**——三层闸门、三重约束、Protocol 注入是不变量，新增的都是外围插件，
   经装配层接入，不改 react.py / gates.py 的既有语义。
2. **离线可降级**——每个新能力都有「无 API Key、无外部服务」的降级路径，延续全离线
   可测的工程要求。
3. **可测性优先**——新模块同样走 Protocol + 替身，测试套件保持全离线。
4. **单 Agent 优先**——能力优先于架构复杂度，不为了看起来高级上多 Agent。

## 5. 模块设计

### 5.1 输入层 InputAdapter（P0）

- 问题：现在吃结构化任务，真实输入是 Gherkin、自然语言、Excel 用例表。
- 思路：在 planner 之前加 InputAdapter（Protocol），把各种原始输入转成统一 TestPlan。
- 关键决策：断言显式建模。Given/When 是动作（action），Then 是期望结果（assertion），
  数据模型里分开。动作喂 EXECUTE，断言喂 REFLECT 做校验，而不是把整个用例丢给模型
  自由发挥。这一步决定「断言能否被自动校验、报告能否算出 pass/fail」。
- 扩展点：InputAdapter 是 Protocol，YAML/Excel/Jira 拉需求都是新增一个实现。

### 5.2 感知层 Perception Layer（P0，核心）

- 定位：不是独立 Agent，是 UI 执行器上的能力插件，延续单 Agent 原则，保证它仍受
  执行器超时闸门管控、CancellationToken 能穿透。
- DOM 蒸馏：提取可访问性树（accessibility tree）而非整段 HTML，三档——text_only
  （检索）、input_fields（只留可交互元素）、full（精简全量）。每个元素注入稳定标识
  element_id，模型用 id 引用元素，不碰脆弱 CSS selector。
- 元素自愈定位：多策略降级链 data-testid → aria-label → text → role。定位失败时把
  「DOM 蒸馏快照 + 失败信息」喂回模型重新生成定位策略。命中后写会话级缓存
  （元素语义 → 实际 locator），后续步骤直接复用。
- 取舍：可访问性树 + 稳定 id 注入是 Hercules 验证过的路线，对齐其思路不重复造轮子。

### 5.3 记忆层 Memory（P1）

- 短时上下文压缩：ContextCompressor，上下文超阈值时把历史 trace 蒸馏成摘要。记忆做
  成「能力」而非「独立 agent」，是 Hercules 踩过的坑（引入 mem agent 后又移除）。
- 长期 RAG 知识库：存历史用例、缺陷记录、元素语义缓存、测试规则知识。两个检索时机
  ——Planner 规划时查相关历史用例，REFLECT 反思时查相似缺陷。embedding 走可插拔
  Provider，真实场景接 API，离线测试用特征哈希假 embedding 降级。

### 5.4 生态接入 MCP Adapter（P2）

- 把外部 MCP server 的工具自动转译成技能注册表里的技能（schema 映射 + 运行时调用），
  Jira/禅道/TAPD/TestRail 都能以技能形式被调用，复用现有技能声明机制。
- 三条安全约束（借鉴 QuAIA 但轻量化）：① 工具分只读/写，写操作不自动重试、受闸门
  管控；② 每个外部工具套执行器级超时；③ 会话级连接用完即关，重连恰好一次。

### 5.5 报告层 Report Adapter（P1）

- 关键决策：trace 与 report 分离。trace 是过程记录，report 是结果产物，职责不同。
- ReportAdapter 从「trace + 断言结果」派生统一结果模型，渲染 JUnit XML（CI 友好）、
  Allure（测试平台）、HTML（给人看）。断言通过/失败自动统计。

### 5.6 多 Agent 编排（P3，暂缓）

单 Agent 框架立刻上多 Agent 会破坏三层闸门简洁性。QuAIA 的多 Agent 解决「流程编排」，
本框架解决「单点执行可靠性」，层次不同。先做深单 Agent，多 Agent 留作后续「编排层」
扩展点，只需预留 AgentCard 能力描述接口。

## 6. 目标架构（分层）

```
输入层 Input Layer（新增）     Gherkin / 自然语言 → 结构化测试任务
规划层 Planner（复用）         Plan-and-Solve 任务分解
感知层 Perception（新增）      DOM 蒸馏 + 元素自愈定位（UI 执行器能力插件）
控制循环内核（复用，不变量）    ReAct · 三层闸门 · 三重约束
技能与记忆（扩展）             MCP 工具适配器 + RAG 知识库 + 上下文压缩
执行与报告（扩展）             API/UI/移动执行器 · JUnit/Allure/HTML 报告
```

## 7. 分阶段路线

- Phase 1（P0）：Gherkin 输入 + DOM 蒸馏/元素自愈 → 能跑真实 UI 用例
- Phase 2（P1）：RAG 知识库 + 上下文压缩 + 报告体系 → 能复用、能进 CI
- Phase 3（P2）：MCP 适配器 → 接外部系统
- Phase 4（P3，可选）：多 Agent 编排

## 8. 风险与取舍

- DOM 蒸馏实现成本不低（可访问性树提取、id 注入、三档切换），但这是最大差异化价值，
  值得投入。
- RAG 引入向量库会增加部署复杂度，所以 embedding 和向量存储都要可插拔、可降级。
- 报告层和 MCP 是投入小见效快的项，建议与 Phase 1 并行推进。
