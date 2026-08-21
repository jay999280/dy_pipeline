# dy-pipeline-skill — 抖音对标视频 → 脚本批量生成流水线

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/jay999280/dy-pipeline-skill?style=social)](https://github.com/jay999280/dy-pipeline-skill)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()

从抖音「像人一样刷视频找对标」，到批量产出**可直接开拍**的脚本池 Excel。一条命令跑完：找对标 → 看懂视频（转写+视觉）→ 拆解爆款逻辑 → 聚类赛道 → 批量生成脚本 → 自动质量评审。

> 💡 也可作为 **Codex / Claude Code / WorkBuddy 等 AI 助手的技能**使用：项目根目录的 `AGENTS.md` 是给 AI 的作业手册，AI 进入项目自动加载，说一句"跑流水线"即可全流程执行。

## 功能特性

- **搜索驱动找对标**：按关键词滚动刷视频（像人一样刷），量化预筛（爆款系数/互动率/评论赞比/发布时间）+ AI 五维匹配度分析，一轮人工确认
- **真正"看懂"视频**：ASR 转写带时间戳（本地 faster-whisper / 豆包 ASR）+ GLM 视觉模型看帧，输出真实分镜表（景别/画面内容/画面文字）
- **评论区挖掘**：采集爆款视频评论，提取受众痛点词/争议点/真实语言
- **四维爆款拆解**：钩子设计（前3秒）/ 叙事节奏（带时间轴）/ 情绪共鸣点（带触发秒）/ 结尾互动引导
- **对标改编生成**：1:1 内容跟随改编，保话题保论点换客户语境；分镜表含景别/拍摄提示/字幕音效建议/改编说明
- **自动质量闸**：合规扫描（广告法绝对化用语）、卖点覆盖率、脚本间查重（rapidfuzz）、结构同质化检查、LLM Judge 四维评分（低分自动重生成）
- **越用越贴合客户**：人工改稿自动回写 fewshot、你选视频的偏好沉淀、客户标签/人设档案约束生成
- **测试波-量产波**：`--wave test` 每赛道先出 1 条快速验证方向，复盘后再量产
- **成本可控**：LLM 同 prompt 磁盘缓存，重跑零计费；视觉默认 glm-4v-flash 免费档

## 工作流程

```
run.py 全流程：
video_screen(搜索驱动找对标) → transcribe(转写+抽帧) → vision(视觉看帧)
  → comments(评论挖掘) → analyze(四维拆解) → cluster(聚类+选题库)
  → distill(模式蒸馏) → generate(批量生成+评审+脚本池xlsx)
可选：account_screen(账号深挖模式) | collect_more(语料扩充) | feedback(试水复盘)
```

## 安装（3 步，约 2 分钟）

```bash
# 1. 克隆（或用右上角 "Use this template" 一键复制成自己的仓库）
git clone https://github.com/jay999280/dy-pipeline-skill.git
cd dy-pipeline-skill

# 2. 一键安装（自动建虚拟环境/装依赖/装 Chrome/生成 .env）
#    Windows: 双击 install.ps1 或 powershell -ExecutionPolicy Bypass -File install.ps1
#    Linux/macOS: bash install.sh

# 3. 填 .env（LLM_API_KEY，智谱免费: https://open.bigmodel.cn）
```

依赖：Python 3.10+、ffmpeg（一键脚本会检测/提示安装）、Chrome。

## 快速开始

```bash
# 1. 建需求卡：复制 config/需求卡模板.yaml 或 config/示例_需求卡.yaml
cp config/需求卡模板.yaml config/我的客户_需求卡.yaml

# 2. 查看/跑全流程（首次运行会弹 Chrome，扫码登录抖音一次）
python src/run.py config/我的客户_需求卡.yaml

# 3. 分阶段跑 / 查看进度 / 强制重跑
python src/run.py config/我的客户_需求卡.yaml --only video_screen
python src/run.py config/我的客户_需求卡.yaml --status
python src/generate.py config/我的客户_需求卡.yaml --resume --force
```

### 人工门禁

筛选阶段跑完会以退出码 2 结束，并把候选清单写成 Markdown。把选中的视频 `video_id` 填入 `selected_candidates.json` 后重跑即可继续。也可用 `account_screen` 进入"先选账号再深挖"模式。

### 交付物

脚本池 `脚本池.xlsx` 含：每赛道一个 sheet（对标链接｜发布文案｜分镜表｜口播文案）、拍摄执行 sheet（按场景聚合镜头+道具清单）、发布文案候选、judge 评审得分。

## 目录结构

```
├── config/            # 需求卡模板 + 示例需求卡
├── src/
│   ├── run.py         # 总入口（阶段链/--status/--only/--resume）
│   ├── collector.py   # Playwright 接口拦截采集（登录态复用/验证码暂停/SSR兜底）
│   ├── video_screen.py# 搜索驱动找对标：量化预筛 + 五维匹配度
│   ├── transcribe.py  # 下载→ASR 带时间戳转写→抽帧→删视频
│   ├── vision.py      # GLM 视觉看帧 → 真实分镜表
│   ├── comments.py    # 评论区采集
│   ├── analyze.py     # 四维爆款拆解（LLM 缓存）
│   ├── cluster.py     # 赛道聚类 + 选题库
│   ├── distill.py     # 风格蒸馏 → 爆款模式库
│   └── generate.py    # 对标改编生成 + 质量闸 + 脚本池 xlsx
├── tests/             # pytest 单元测试
└── AGENTS.md          # Codex/Claude Code 等 AI 助手的作业手册
```

## 测试

```bash
python -m pytest tests/ -q
```

## 免责声明

本项目仅用于内容创作学习与研究。采集的抖音数据版权归原平台及创作者所有；请遵守平台规则与当地法律法规，勿将采集能力用于侵权、滥用或干扰平台正常运营。使用本项目产生的一切后果由使用者自行承担。

## 许可证

[MIT](LICENSE) © 2026 jay999280
