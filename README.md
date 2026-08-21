# 抖音对标视频 → 脚本批量生成流水线

从对标账号/关键词采集抖音爆款视频 → ASR 逐字稿 → DeepSeek 结构化拆解 → 赛道聚类 → 按赛道批量生成脚本（Excel 输出）。

## 目录结构

```
dy_pipeline/
├── config/
│   ├── 需求卡模板.yaml          # 每次运行的需求卡模板
│   └── 示例_需求卡.yaml          # 示例需求卡
├── src/
│   ├── common.py               # 路径、日志、工具函数
│   ├── collector.py            # ① 采集：Playwright 接口拦截（登录态复用、验证码暂停、SSR 兜底）
│   ├── transcribe.py           # ② 转写：下载视频 → ASR 逐字稿（转完即删视频）
│   ├── analyze.py              # ③ 分析：DeepSeek 结构化拆解爆款
│   ├── cluster.py              # ④ 聚类：赛道划分
│   ├── generate.py             # ⑤ 生成：脚本批量生成 → xlsx（few-shot + 查重闸）
│   └── run.py                  # 总入口，按需求卡跑全流程
├── tests/                      # 单元测试（采集解析/few-shot解析/xlsx输出/查重）
└── data/                       # 运行产物 + 浏览器登录态 + whisper 模型
```

## 快速开始

```powershell
cd ~\Desktop\dy_pipeline
pip install -r requirements.txt

# 1) 配置 DeepSeek API Key（分析/生成阶段需要，新开终端执行后生效）
setx DEEPSEEK_API_KEY "sk-你的key"

# 2) 完整运行：按需求卡执行全部阶段
python src\run.py config\示例_需求卡.yaml
```

### 首次运行注意事项（实战验证过）

1. **扫码登录**：采集阶段会打开 Chrome 窗口，用抖音 App 扫码一次。登录态保存在 `data\browser_profile`，之后自动复用。
2. **验证码**：采集滚动时抖音可能弹滑块验证码，**人工滑一下**，程序会等 20 秒继续。
3. **whisper 模型**：已预下载到 `data\models\faster-whisper-small`（model.bin + tokenizer.json + vocabulary.txt + config.json），无需再下载。注意该仓库**没有** `vocabulary.json`/`preprocessor_config.json`，不要按这两个名字去下载。
4. **转写引擎**：默认用本地 whisper（CPU，约 1.7 倍速）。配置 `VOLC_ASR_APPID` + `VOLC_ASR_ACCESS_TOKEN` 后自动切换豆包语音识别（快几十倍）。

## 运行方式

每次运行 = 一份需求卡（YAML），描述一个客户的业务、对标账号、关键词和本次预算：

```powershell
python src\run.py config\示例_需求卡.yaml            # 新任务：全部阶段
python src\run.py config\示例_需求卡.yaml --resume   # 继续上次，完成的阶段自动跳过
python src\run.py config\示例_需求卡.yaml --only analyze   # 只跑某阶段
python src\run.py config\示例_需求卡.yaml --only collector --force  # 重采
```

各阶段可单独运行（默认复用上次运行目录，`--fresh` 新建）：

```powershell
python src\collector.py config\示例_需求卡.yaml
python src\transcribe.py config\示例_需求卡.yaml --limit 2   # 先试转 2 条
python src\analyze.py config\示例_需求卡.yaml
python src\cluster.py config\示例_需求卡.yaml
python src\generate.py config\示例_需求卡.yaml
```

## 各阶段产物（`data/<客户>/<run>/`）

| 阶段 | 产物 |
|---|---|
| collector | `candidates.json`（标题/账号/点赞/评论/播放地址）+ `candidates.debug_urls.txt`（诊断） |
| transcribe | `transcripts/<video_id>.txt`（完整逐字稿，视频转完即删） |
| analyze | `analysis.json`（每条视频的 hook/结构拆解/爆点归因/可复用模板） |
| cluster | `tracks.json`（赛道框架） |
| generate | `脚本池.xlsx`（对标链接｜发布文案｜画面｜文案）+ `scripts.json` |

## 需求卡字段说明

- `对标账号`：抖音主页链接（douyin.com/user/... 或分享短链），采该账号作品；留空则只按关键词采
- `关键词`：抖音站内搜索词
- `采集设置`：每个来源最多视频数 / 最低点赞（低于仅保留不推荐）/ 滚动上限
- `生成设置`：赛道数 / 每赛道脚本数 / `fewshot_脚本xlsx`（已有的人工脚本 Excel，教模型学格式和语气）
- `转写设置`：`引擎: auto`（有豆包密钥用豆包，否则本地 whisper）

## 质量红线（生成层内置）

1. 只借结构不抄句子：查重闸比对参考逐字稿，10 字以上整句照搬会打警告
2. 数字/尺寸/价格/材料承诺强制留白，人工核对后再发布
3. 产品植入放解决方案段，前 3 秒必须有钩子
