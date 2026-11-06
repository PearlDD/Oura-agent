# IRON / OURA · Personal Training Agent

本机单用户训练与恢复工具，结合训记训练记录和 Oura 指标，提供中文日报、实验性肌群负荷观察、待确认训练计划与实际 AI 分析。Python 3.10+，零第三方依赖。

## 启动与连接

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

此代码不自行安装定时任务。Codex 中已配置的自动化可每天调用上述流程，具体时间以自动化设置为准。电脑和运行环境需可用。

可选网页 AI 按钮需要自己的 OpenAI API Key 和可用模型 ID；明确授权后，通过 Responses API 发送近 28 天训练、恢复、活动、偏好、计划、反馈和所填症状/周期背景，返回结构化决策。`store:false` 不代表零数据保留，API 可能收费。自由文本 check-in 备注及密钥不进入模型输入；身体背景症状文字会在该授权范围内发送。

## 本机数据与边界

默认运行数据位于源目录上两级的 `work/iron-oura-data/`，可用 `IRON_DATA_DIR` 指定。目录权限 700、文件 600，未额外加密。密钥、原始记录和个人报告不得提交 GitHub；删除本机令牌不等于撤销提供商授权。服务器只绑定 127.0.0.1，有 Host、CSRF 和 CSP 校验，不应直接暴露公网。

默认时区 America/New_York（`IRON_TIMEZONE`），端口 8765（`IRON_PORT`；更改后更新回调白名单）。Oura day 与训记日期直接对齐，旅行需注意日期归属。身体背景与计划均可更正；建议依赖已读取记录与明确反馈，不诊断疾病、不从单次 HRV、分数或停练天数断定恢复。

## 验证

```sh
python3 -m unittest -q
node --check static/app.js
```

测试使用临时目录和模拟响应，不触碰私人缓存。源码与公共站点不包含用户密钥或健康记录。
