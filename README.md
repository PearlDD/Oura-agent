# IRON / OURA · Personal Training Agent

支持本机与私人 VPS 部署的单用户训练与恢复工具，结合训记训练记录和 Oura 指标，提供中文日报、实验性肌群负荷观察、待确认训练计划与实际 AI 分析。Python 3.10+，零第三方依赖。

## 云端访问与连接

已部署的私人面板：**https://pearloura.duckdns.org/。

网页登录密码与 API Key 分开管理。密码保存在用户本机的私有文件中，不发布到此仓库。云端网页运行在 VPS 上，关闭 Mac 后网页仍可访问。

在云端「连接与设置」填写自己的训记 API Key、Oura Client ID / Client Secret，以及所选 AI 提供商的 API Key 和模型 ID。保存配置后，还需点击「连接 Oura」并完成 Oura 的同意授权流程。

Oura 开发者应用的 Redirect URIs 须新增并保存以下完整地址：

```text
https://pearloura.duckdns.org/oauth/callback
```

本机回调可保留用于开发或回退。GitHub Pages 只提供公共介绍和政策，私人面板与授权回调由 VPS 承载。

云端定时同步与定时 AI 均须在数据源授权、真实同步及配置验证后单独启用；网页部署成功不等于每日任务已经切换。切换时停用旧本机任务，避免重复同步和模型调用。部署与恢复说明见 [VPS 部署文档](deploy/README.md)。

## 本机开发与应急启动

```sh
python3 launch.py
```

打开 http://127.0.0.1:8765 。macOS 也可双击 `启动.command`。在「连接与设置」输入自己的训记训练 API Key，以及 Oura Client ID / Client Secret；Oura 回调白名单必须完全匹配 `http://localhost:8765/oauth/callback`。仅申请 daily 读取权限。

公共介绍和政策页面由 GitHub Pages 的 `docs/` 提供，不承载私人面板或授权回调：

- [介绍](https://pearldd.github.io/Oura-agent/)
- [隐私政策](https://pearldd.github.io/Oura-agent/privacy.html)
- [使用条款](https://pearldd.github.io/Oura-agent/terms.html)

## 分析与计划

- 只读同步最近 7/28 天训记及 Oura sleep、daily_sleep、daily_readiness、daily_activity；保留恢复 contributors、温度偏移、呼吸、活动背景。
- 只计已完成正式组，区分热身、缺值、未知动作与辅助/活动度；个人恢复基线采用此前 28 天中位数，至少 7 个有效夜晚。
- 只用主睡眠参与恢复分析，普通睡眠片段显示待同步，避免把未完成的一夜误报为极短睡眠。
- 实验性肌群模型分别展示主练组、间接组当量、历史周量及残余负荷假设区间，不测量生理恢复百分比。
- 按偏好与历史动作生成未来七天草案，保留已接受计划，新修订另列提案；日志匹配不代替用户确认完成。
- 反馈校准预测主观局部疲劳，需足够反馈/RPE 和留出验证改善才启用，不能声称已经完成个人拟合。
- 首页 AI 决策包含今日结论、证据、保持/减量/休息/轻量活动的条件、肌群复核及短长期调整。来源、时间和数据变化可核对；规则草案不冒充 AI。
- 用户确认的症状、strain 等级和周期背景单独保留日期与来源；当前同步不返回周期阶段或 Symptom Radar 等级，不从温度猜周期，缺失不当作正常。

详见 [肌群模型说明](肌群模型说明.md) 与 [教练 Agent 说明](教练Agent说明.md)。

## 日报和实际 AI 分析

```sh
python3 morning_report.py
python3 morning_report.py --cached
```

脚本无需网页服务器常驻。同步后导出 Markdown 和私有分析上下文。聊天中的 Agent 可依据 `decision.py` 的 PROMPT / SCHEMA 进行推理，用 `agent_decision.py` 校验并保存决策，再缓存导出日报。保存时检查上下文指纹，数据或主计划变化后旧结论显示为历史，禁止采用过期修订。保守修订需用户核对，只可减少原动作组次或增加预留次数，不能新增重量。

本机流程可由 Codex 自动化调用，需要电脑和运行环境可用。云端通过 `cloud.py` 在网页服务的同一进程中运行每日任务，默认关闭；验证完成后通过部署配置启用，时间为 America/New_York 11:00，停机后同日可补跑一次。同步失败或完整主睡眠缺失时不调用定时 AI，报告仍标记缺失数据。

定时 AI 需要独立启用并指定提供商，详见 [部署配置](deploy/README.md)。云端报告保存到私有报告卷；不自动发邮件，也不会自动发送到 Codex 聊天。不要在运行中的云端网页旁另开一个 CLI 进程写入相同数据目录。

可选网页 AI 按钮需要所选提供商的 API Key 和可用模型 ID；明确授权后，通过 OpenAI Responses API 或 Gemini generateContent 发送近 28 天训练、恢复、活动、偏好、计划、反馈和所填症状/周期背景，返回结构化决策。OpenAI 的 `store:false` 不代表零数据保留；Gemini 适用 Google 自身的数据处理条款，API 可能收费。自由文本 check-in 备注及密钥不进入模型输入；身体背景症状文字会在该授权范围内发送。

## 数据保存与访问边界

本机默认运行数据位于源目录上两级的 `work/iron-oura-data/`，可用 `IRON_DATA_DIR` 指定。目录权限 700、文件 600，未额外加密。密钥、原始记录和个人报告不得提交 GitHub；删除本机令牌不等于撤销提供商授权。本机默认只绑定 127.0.0.1，具备 Host、CSRF 和 CSP 校验。云端模板仅公开 Caddy 的 HTTPS/HTTP 端口，要求网页登录；应用端口不映射到公网，并核对代理密钥和域名。云端数据与报告存储在私有 Docker 卷中，容器重建不会清空这些卷。不要将数据卷、私有部署环境文件或备份提交 GitHub。

默认时区 America/New_York（`IRON_TIMEZONE`），端口 8765（`IRON_PORT`；更改后更新回调白名单）。Oura day 与训记日期直接对齐，旅行需注意日期归属。身体背景与计划均可更正；建议依赖已读取记录与明确反馈，不诊断疾病、不从单次 HRV、分数或停练天数断定恢复。

## 验证

```sh
python3 -m unittest -q
node --check static/app.js
```

测试使用临时目录和模拟响应，不触碰私人缓存。源码与公共站点不包含用户密钥或健康记录。


## 可视化面板

首页以当日 AI 建议为主：红色休息、黄色减量/轻活动、绿色保持训练；等待分析、过期数据及未确认安排使用中性色。文字标签始终保留，不单独依赖颜色。颜色不代表恢复百分比或训练许可，也不按 Oura 分数直接套用阈值。

肌群条形图分开显示当前七天主练与间接当量、前七天总当量和个人历史周量标记；优先展示重点肌群，其余及残余负荷在展开表格中查看。覆盖不足明确标记，不将未同步日期视为无训练。恢复图比较两个七天窗口的中位数，样本不足不画比较条。完整分析、计算口径、反馈和计划动作按需展开。

视觉参考：[WHOOP 的恢复颜色](https://www.whoop.com/us/en/thelocker/how-does-whoop-recovery-work-101/) 与 [Oura 的准备度分级](https://ouraring.com/blog/readiness-score/)，仅参考信息层级与颜色表达，不复制其分数算法。


## 网页内问训练 Agent

右下角「问训练 Agent」或今日建议卡片「问问 Agent」打开侧边聊天窗。使用当前选择的 OpenAI 或 Gemini 模型；每次发送均需聊天区授权勾选。服务端附加最新所选日期报告上下文、过去28天训练与恢复、肌群估计、偏好/计划、明确保存的身体背景，以及已存 AI 决策的新鲜度。发送最近6轮对话；完整会话按报告日期保存在应用数据目录的私有 `chats/`，不与 Codex 聊天记录自动互通。自由文本 check-in 备注和密钥不进入上下文；聊天中输入的内容会发送给模型。

切换报告日期切换对应会话并重置授权；旧回答之后若数据改变会明确标注。失败不追加半条对话，问题留在输入框供重试。对话版本校验与每日期忙碌锁避免重复提交和并发覆盖；「新对话」将旧会话归档在应用服务器。最多60轮后需新开会话。

聊天仅解释和提出建议，没有修改计划/反馈、同步或校准工具，不声称已执行操作。需要持久更正或接受修订时，仍使用相应表单与计划入口。历史基础草案的每动作两组上限不等于个体最优组数或症状专门减载。

Responses API 使用 `store:false`，但不保证零数据保留或免除费用。额度不足、授权或网络问题会明确提示；未完成模型回复不当作成功回答。没有进行健康数据的无授权真实模型测试。


## AI 配置：当前使用 OpenAI / GPT

当前部署选择 **OpenAI**，模型 ID 为 **`gpt-6.1-sol`**。在「连接与设置 → AI 提供商 → OpenAI」保存 OpenAI API Key 和模型 ID；同一配置用于网页问答和结构化日报。配置保存成功不等于已经完成真实模型调用，生成报告或聊天前仍需确认页面的数据发送授权。

OpenAI 使用 Responses API，并设置 `store: false`；该参数不等于零数据保留，API 按账户实际用量计费。训练记录、Oura 授权与 AI 提供商分别配置，修改 AI 提供商不会替代 Oura 授权。

### 可选备用：Google / Gemini（当前未使用）

下面仅说明如何主动切换到 Gemini；保留这项接入能力不代表当前报告使用 Gemini。系统不会自动将 OpenAI 请求转交给 Gemini。

「连接与设置 → AI 提供商 → Google / Gemini」输入 Gemini API Key 和该项目可用的模型 ID，再确认项目已启用付费服务并保存。密钥只保存在应用服务器端（本机或 VPS），不回传浏览器，不放 URL。Google 免费服务条款要求不提交敏感/个人信息；本应用含私人健康背景，因此发送前须确认使用付费服务。

同一提供商配置用于网页问答和结构化日报。切换提供商后清除发送授权，页面显示实际接收方；服务端也核对提供商，避免旧页面把原先授权发送给另一家。不会自动降级发送给其他提供商。Gemini 使用原生 generateContent、systemInstruction、多轮 user/model 内容和 responseJsonSchema；不会声称 Gemini 支持 OpenAI 的 store:false。

参考：[Gemini API](https://ai.google.dev/api/generate-content)、[Google 数据处理条款](https://ai.google.dev/gemini-api/terms)。实际模型和额度须以用户项目为准。未提供 Gemini Key 时仅完成模拟测试，不能宣称真实调用已成功。
