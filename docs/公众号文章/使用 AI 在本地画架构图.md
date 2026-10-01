# 使用 AI 在本地画架构图

> 实测图在最后，好用、便宜。

---

## 流水线上的三个开源项目

一句话流程：**draw.io 负责"图"的格式；Next AI Draw.io 负责"AI 帮你画"；drawio-export 负责"导出高清图"。**

- **draw.io（diagrams.net）**：绘图工具本体，JGraph 团队维护的老牌开源项目。`.drawio` 文件就是它的格式，本质是一份 XML；只要是 draw.io 客户端，哪儿都能打开。
- **Next AI Draw.io**（仓库名 `next-ai-draw-io`）：把 AI 对话接进 draw.io 的本地 Web 应用，作者 DayuanJiang。"AI 帮你画"靠的就是它：你在对话框里描述或提修改意见，AI 直接改图的 XML，画布实时更新。
- **drawio-export**（仓库名 `rlespinasse/drawio-export`）：作者 rlespinasse 做的 Docker 命令行导出工具，内核是 draw.io 官方桌面版的 headless 模式。"一条命令把 .drawio 变成 PNG / SVG"靠的是它。

以上都是他人的开源作品，不是本文作者的创作；下面只讲怎么用。

顺带回答一个常见疑问：为什么不用 Mermaid？流程图、时序图这类结构简单的图，Mermaid 足够；但架构图往往要反复微调排版和配色，还要导出高清大图，画布式工具更趁手。

## 第一步：用 Docker 起一个本地 AI 画图服务

前提：本机装好 Docker（Windows / macOS / Linux 都行）。然后一条命令：

```bash
docker run -d --name next-ai-draw \
  -p 3000:3000 \
  -e AI_PROVIDER=deepseek \
  -e AI_MODEL=deepseek-chat \
  -e DEEPSEEK_API_KEY=sk-替换成你的Key \
  -e TEMPERATURE=0 \
  --restart unless-stopped \
  ghcr.io/dayuanjiang/next-ai-draw-io:latest
```

打开 `http://localhost:3000`，就能看到"对话框 + draw.io 画布"的界面。

几个说明（细节以项目官方文档为准）：

- `AI_PROVIDER` / `AI_MODEL` 决定用哪家模型。项目内置支持 DeepSeek、OpenAI、Anthropic、Google、豆包、GLM、Qwen、Kimi 等一大批，也支持本地 Ollama（注意：默认接的是 Ollama 云，要接自己机器上的 Ollama 需改 `OLLAMA_BASE_URL` 指向本机服务）。
- `TEMPERATURE=0`：可选，让输出更稳定。
- 这类任务对模型能力要求不低：要让模型吐出又长又规矩的 XML，格式错一点图就乱。官方明确建议用能力较强的模型；本地小模型画不好属正常，先换模型再怀疑人生。
- 不想装 Docker 也有官方的在线演示站和桌面应用可选，本文只走本地 Docker 这条。

## 第二步：和 AI 对话，把图"聊"出来

直接在对话框里描述你要的图。经验是一句话：**给规格，别给愿景**。层数、每层放什么、怎么连线、什么颜色、横版竖版、画布多大，说得越具体，一次成型的概率越高。比如：

```
画一张系统架构图（横版，画布约 1600×1000，中文标签）。
从上到下三层，每层用一个带标题的容器框，不同底色区分：
1. 接入层：Web 前端、API 网关
2. 服务层：业务服务、任务队列、定时任务
3. 数据层：MySQL、Redis、对象存储
连线：接入层 → 服务层（实线）；服务层 → 数据层（实线）；服务层 → 外部支付回调（虚线）。
```

然后**小步迭代**：哪里不对改哪里，比如"标题栏太高了""把这个盒子移到右边""这条箭头改成虚线"。它每轮是把你的要求连同当前图的 XML 一起交给模型改写（项目 README 的"工作原理"一节有说明），所以指令越具体，改得越准；"整体再美观一点"这类指令效果最差。

两个自带能力也值得知道：丢一张现有图进去，AI 照着重画；丢一份 PDF，它提取内容画成图。

版本留存：项目自带图表历史（可回看、回滚）；我自己的习惯是每轮存一版 `.drawio`（v1、v2……）并导出一版 PNG 对比。源文件是 XML 文本，放进 Git 后每次改动都看得清楚，改崩了随时退回上一版。

## 第三步：导出高清图

两条路，按需选。

**A. 界面直接导出。** draw.io 编辑器自带导出（PNG / SVG / PDF），也能保存 `.drawio` 源文件。偶尔画一张，这样就够了。

**B. 命令行导出（推荐）。** 高清、批量、脚本化的场景，用 drawio-export 一条命令：

```bash
docker run --rm -v "$PWD":/data \
  rlespinasse/drawio-export \
  -f png -s 2 -b 20 -o . \
  arch.drawio
```

- `-f png`：输出格式，还支持 `svg`、`jpg`、`pdf` 等；
- `-s 2`：2 倍分辨率，要更清晰就调大；
- `-b 20`：图形四周留边距（默认 0，贴边裁剪）；
- `-o .`：输出位置。不写 `-o` 的话，默认在源文件旁边建一个 `export/` 子目录，想和源文件放一起就写 `-o .`。

几个细节：

- 导出按图形内容裁切，画布上多余的空白不会带出来，尺寸由内容大小、`-s` 倍数、`-b` 边距共同决定，别被和画布尺寸的差异吓到。
- 文件名默认带页面名（如 `arch-系统架构.png`）；单页图想要干净文件名，加 `--remove-page-suffix`。
- 整个目录一把梭：把最后的文件名换成目录路径（或省略），目录下（含子目录）的 `.drawio` 会批量导出。
- 透明背景加 `-t`；矢量图用 `-f svg`。
- 中文没问题：镜像内置了 Noto Sans CJK、AR PL 等中文字体，中文标签正常渲染。
- 全量参数看：`docker run --rm rlespinasse/drawio-export --help`。

## 几个实际使用中的经验

- **AI 出草稿，你负责把关。** 结构交给它出，细节自己盯；改图继续用具体指令，比推倒重来快。
- **字体观感两边略有差异。** 浏览器里用你本机字体渲染，导出容器用容器内字体渲染，"网页上好看、导出来略不同"是正常的，以最终导出为准。
- **想更彻底地"本地"。** 用云端模型时，图的内容会发给模型商，敏感的图就换成本地 Ollama；编辑器界面默认从 diagrams.net 的嵌入服务加载，内网部署可通过 `NEXT_PUBLIC_DRAWIO_BASE_URL` 换成自托管 draw.io。
- **进阶：把生成也自动化。** draw.io 图就是 XML，这个项目的玩法本质是"给模型一份 XML 结构说明书、让它按格式输出"，那份说明书就在项目仓库里（`app/api/chat/xml_guide.md`）。想批量生成、批量改图，可以拿它当提示词素材直接调模型 API，产出 `.drawio` 后再用上面的命令批量导出。
- **日常运维。** 不用时 `docker stop next-ai-draw`，下次 `docker start next-ai-draw` 即可；命令里带了 `--restart unless-stopped`，机器重启后它会自动拉起（手动停过则不会）。端口冲突就把 `-p` 的前半段换掉，如 `-p 3001:3000`。

## 相关项目

- Next AI Draw.io：`https://github.com/DayuanJiang/next-ai-draw-io`

## 结尾

工具都是开源现成的，我们要做的只是把它们拼起来、用顺手：**AI 负责初稿和体力活，你负责审美和把关**。下次画架构图，可以不用再拖方块了。

> 可以让 AI 读取 README 文档帮你安装、配置API KEY。
