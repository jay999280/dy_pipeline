# dy_pipeline — 抖音对标脚本流水线（Codex 作业手册）

本文件是 Codex 在本项目的操作指南。目标：按客户需求卡跑完整流水线，产出可直接拍摄的脚本池 Excel。

## 环境（执行时必须遵守）

- **Python 必须用**：`C:\Python314\python.exe`（依赖齐全：playwright/requests/pyyaml/openpyxl/faster-whisper/rapidfuzz/pytest）
- **LLM**：环境变量 `LLM_API_BASE`/`LLM_API_KEY`/`LLM_MODEL` 已设（智谱 API，文本 glm-4-flash 免费，视觉 glm-4v-flash 免费）。若 Codex 会话中调用失败，先 `echo $env:LLM_API_KEY` 检查变量是否继承
- **抖音登录态**：`data\browser_profile`（已登录）。失效时采集阶段会弹出 Chrome，需要用户扫码——此时停下等用户操作
- **系统依赖**：ffmpeg、系统 Chrome（Playwright 用 channel="chrome"）
- 数据目录 `data/` 不入 git（含登录态与运行产物）

## 流程速览（9 阶段 + 可选）

```
run.py 全流程：account_screen → video_screen → transcribe → vision → comments
             → analyze → cluster → distill → generate
可选：feedback（试水复盘）| collect_more（语料扩充）
```

两轮人工门禁在 account_screen / video_screen 后，退出码 2 = 等用户确认。

## 命令速查（全部在仓库根目录执行）

```powershell
# 查看当前进度与卡在哪道门禁
C:\Python314\python.exe src\run.py config\<客户>_需求卡.yaml --status

# 全流程（门禁处自动停，确认后重跑继续）
C:\Python314\python.exe src\run.py config\<客户>_需求卡.yaml

# 只跑某阶段
C:\Python314\python.exe src\run.py config\<客户>_需求卡.yaml --only analyze

# 重新生成全部脚本（调 LLM）
C:\Python314\python.exe src\generate.py config\<客户>_需求卡.yaml --resume --force

# 测试波（每赛道1条，验证方向）/ 量产
C:\Python314\python.exe src\generate.py config\<客户>_需求卡.yaml --resume --force --wave test

# 测试
C:\Python314\python.exe -m pytest tests/ -q
```

## 阶段要点

| 阶段 | 产物 | 说明 |
|---|---|---|
| account_screen | 账号候选清单.md + accounts_selected.json | AI 五维打分，等人工选号 |
| video_screen | 爆款视频候选清单.md + videos_selected.json + selected_candidates.json | 量化预筛（爆款系数/互动率/月龄）+ 五维匹配度 |
| transcribe | transcripts/<id>.txt + .json（带时间戳） | whisper 本地 ASR（慢）；下载后自动抽帧 |
| vision | vision/<id>.json（真实分镜表） | GLM 看帧；若下载遇风控 10054 会失败，跳过即可 |
| comments | comments/<id>.json | 评论区 top30，供拆解注入 |
| analyze | analysis.json | 拆解卡 v2：钩子/节奏/情绪点/互动引导 |
| cluster | tracks.json + topics.json | 赛道 + 选题库 |
| distill | distill/模式库.json + 爆款模式库.md | 客户级知识资产 |
| generate | 脚本池.xlsx + scripts.json + 卖点覆盖.json | 含分镜表/评审/标题候选/拍摄执行 sheet |

## 门禁交互（Codex 必须停）

1. account_screen 或 video_screen 退出码 2 → 打开对应 .md 清单，**渲染给用户看**，请用户回复要选中的项（昵称或 video_id），由用户确认后写入 *_selected.json，再重跑
2. 不要自作主张替用户选号/选视频

## 常见问题处理

- **门禁后重跑**：把用户选中的项写入 `accounts_selected.json`（账号：昵称+sec_uid）或 `videos_selected.json`（video_id 数组），重跑对应阶段
- **登录态失效**：采集阶段会开 Chrome 等扫码，告诉用户扫码，最多等 10 分钟
- **播放地址过期**：下载报 403/断连 → 日志提示"需重新采集刷新"；重跑采集阶段刷新数据
- **下载风控 10054**：抖音限制批量下载（转写/视觉）。代码已加重试+随机间隔；仍失败的视频跳过，不影响其余
- **LLM 调用失败**：analyze/generate 有 5 次重试 + 磁盘缓存（同 prompt 重跑零计费）；持续失败检查环境变量
- **需求卡校验失败**：load_card 会明确报缺哪个字段，按提示补

## 交付物检查（generate 后）

- 脚本池.xlsx 有 3+ 个 sheet（每赛道一个 + 拍摄执行）
- 每条脚本头行：对标链接（A 列可点击）+ 对标标题 + 改编说明
- 镜头行：时间/场景/景别 + 精简画面 + 文案
- 检查 run.log 的告警：合规扫描（绝对化用语）、卖点零覆盖、查重/结构同质化

## 质量红线（生成相关，不可放松）

1. 内容跟随改编：话题/论点跟住对标，只换客户品牌/地区/报价
2. 事实留白：数字/价格/材料承诺写"以实测为准/私信发资料"
3. 禁用绝对化用语（最好/第一/100%/全网最低，广告法）
4. 交付前自查 run.log 告警并报告给用户

## 给 Codex 的一句话启动

用户说"跑流水线"时：先 `--status` 看进度 → 卡在门禁就呈现清单等确认 → 否则从待跑阶段继续，用 `run.py` 全流程（后台跑长阶段，完成后检查日志与产物）。
