# TTS 听书系统·完整进度台账（压缩恢复用）

> 更新: 2026-10-14 凌晨（上下文压缩前快照）
> 关联需求: 2026-10-13-tts-cosyvoice3-plus.md
> 本文件是压缩后恢复工作的唯一权威——包含全部状态/数据/决策点/纪律

## 一、当前系统状态（一句话）

**质量门已生产化上线（Paraformer 回验+N 版重试+兜底, commit 23e4f51）+ 泄漏根因已修（ref_text system 前缀, 上游 64685e8 同源）+ plus 服务链已接回（资产 8bit/uv 自愈/remote_node 对齐）**。待办: ①用户耳朵终审(e2e_qc.wav+prefixfix 三版) ②MacMini 侧验证(依赖闭包 63 包已自愈装, P2P 夜间断线挡住远程验证——用户在 MacMini 控制台直接点试听即可验证本地链, 不依赖 P2P)。
HF_HUB_OFFLINE=1 根因闭环(10-14 深夜): server.py L26 setdefault 离线加速设计 → worker 继承 → MacMini cache 空组件崩。修复=spawn 覆盖 =0(与 2026-08-15 '下载子进程剥离'同一模式)+诊断日志双行铁证。stderr 176KB 二进制污染=HF tqdm 进度条已静音。依赖 --no-deps 漏传递依赖的根治=services/tts_deps.py 63 包钉主控版本闭包。

## 二、用户环境（不变事实）

- **MacBook（主控）**: M4 Pro 48GB, localhost:9776 控制台
- **MacMini（节点）**: 192.168.3.3, M4 基础版 16GB, node=OpenSecurityServer —— **当前 offline**（新代码启动失败或睡眠，需用户物理/ssh 干预: `./start-remote-node.sh --model-tags security,tts`）
- VPS: 74.120.173.111（relayd 41000, PSK 在 .ai_env）; ssh 凭据已失
- 手机: Android + Legado（听书端）
- 局域网 AP 隔离（两机互 ping 不通, P2P 走外网打洞）
- 听书文本: ~/Downloads/捞尸人（全本完结）.txt; 测试段 test_short(L19-38, 368字)/test_full(L19-75); seg1(L39-57,413字)/seg2(L58-75,520字)
- 临时工作区: /var/folders/sk/rm7bl2ks67g7n849g_bsh0nw0000gn/T/opencode/tts-shootout/（out/ 全部试听样本）

## 三、控制台启动命令（每次重启用这个）

```bash
kill $(ps aux | grep "control/backend/server.py" | grep -v grep | awk '{print $2}') 2>/dev/null; pgrep -f tts_worker.py | xargs kill 2>/dev/null; sleep 2; cd /Users/aserlili/Documents/Codes/OpenSecurity/.opencode && OPENCODE_ROOT="$(pwd)" OPENSECURITY_HOME="$HOME/bw-security-analysis" nohup "$HOME/bw-security-analysis/.venv/bin/python" control/backend/server.py >> ~/bw-security-analysis/logs/control-stdout.log 2>> ~/bw-security-analysis/logs/control-stderr.log & disown
```

⚠️ 路径是 `~/bw-security-analysis`（无点前缀）——已两次因写成 `~/.bw-...` 导致"重启失败+控制台死亡假象"。

## 四、TTS 引擎演进终局（plus 回归的完整原因链）

| 引擎 | 状态 | 关键事实 |
|------|------|---------|
| Kokoro | 已删 | 质量不达标 |
| torch 官方栈 | **已放弃修复** | 4.51.3+CPU 可用(RTF 1.1-1.55)是唯一确定可用栈; 5.17(transformers) token 翻倍时长崩(126s vs 64s), 修了 4 个假设全排除(fp16/attn/mask/dtype)未根治; 用户裁决不再尝试 |
| drmse/tts-funaudio | vendor 子模块保留 | fork: git@github.com:zylc369/tts-funaudio-cozyvoice3.git → vendor/tts-funaudio; 它的 RAS 官方实现(cosyvoice/utils/common.py L138)是补丁参考源 |
| **plus (mlx-audio-plus)** | **当前引擎** | 用户裁决回归。MLX/Metal GPU、内存 2.84GB、RTF 0.28-0.39、主 venv 直跑（不碰 transformers）|

**plus 主 venv 依赖状态**: 已装 `mlx-audio==0.2.10` + `mlx-audio-plus==0.1.8`（--no-deps）+ `mlx-lm`（--no-deps）到主 venv（~/bw-security-analysis/.venv）——import 链已验证 OK。另装了 pypinyin、torchcodec、HyperPyYAML、onnxruntime、wetext、modelscope、conformer、diffusers、hydra-core、inflect、lightning、omegaconf、x-transformers、torchaudio、gdown、wget、matplotlib、pyworld、setuptools<81（部分为 torch 栈残留，plus 不全需要）。

**torch 栈全量清除(10-14 用户裁决"失效全删")**: 保险基线 venv(vendor/tts-funaudio/.venv-ttsfun)、torch 模型 5.1GB、vendor/tts-funaudio 子模块、v4/v5 遗留音色(torch/plus 时代产物, plus 下内容泄漏 cov 450% 实锤)全部删除。音色库唯一保留 official_female(官方真人参考, 同时是默认音色——修正了此前"默认=v4 泄漏版"的暗雷)。若重启 torch 路线: 4.51.3 默认 attn 是 SDPA 非 eager(review 验证——勿按"对齐 4.51.3"打 eager 补丁。

## 五、模型文件

| 模型 | 路径 | 状态 |
|------|------|------|
| CosyVoice3-8bit (plus 用) | ~/bw-security-analysis/models/cosyvoice3-8bit/ (1.3GB) | ✅ 就绪 |
| CosyVoice3-torch (fp32, 5.1GB) | ~/bw-security-analysis/models/cosyvoice3-torch/ | 保留（保险基线用）|

模型资产注册(services/model_assets.py): 现为单资产 cosyvoice3-torch（TtsAsset cache_state 检测 torch 目录）——**需要改回/兼容 8bit 目录**（plus 引擎用 8bit——TtsAsset.cache_state 的 need 按 id 分支代码被删了, 现在只查 torch 目录）。

## 六、音色库(backend/assets/voices/voices.json)

| id | 参考 | 用户判定 |
|----|------|---------|
| official_female | 官方女声 3.5s 真人录音 | 好; **rasfix_official_2 用它=音色速度双满意的标准卡** |
| official_female_v4 | cv3_full_female 前17.1s(torch产物) | 8成复刻(torch 时代); plus 下 39s 偏短 |
| official_female_v5 | cv3_female_s0.92 前15.1s(torch产物) | plus 下三版全有重复/吃字——torch 合成音做参考对 plus 不友好 |

**结论性偏好数据**: 用户速度舒适带极宽(0.121-0.185 s/字都可), 关键只有质量(无重复/无错字/无泄漏)——速度筛选不做。

## 七、RAS 补丁(已验证有效)

plus 的 ras_sampling 移植缺陷: 触发重复检测后(a)不屏蔽原 token(可能重采同一个)(b)全词表随机重采(吃字来源)。修复: scripts/tts_worker.py 里的 `_patch_ras()`(屏蔽 -inf + top-k 受限重采 + 双命名空间 patch llm 模块和 cosyvoice3 模块)。**实测 rasfix 三版零重复零吃字(用户确认)**; 但 seg2_v6(修后)仍出现过一次重复——概率降低未根除, 需质量门兜底。

⚠️ **scripts/tts_worker.py 当前状态**: 从 git 历史(4d83765)恢复的纯 plus 版(154行) + RAS patch——**可用**; 但 TtsService(services/tts_service.py)和 install 脚本仍是 torch 时代配置(WORKER_VENV_PY=主 venv sys.executable ✓, 但模型目录 TTS_MODEL_DIR 指向 cosyvoice3-torch——需改回 8bit; _venv_healthy 的 probe 代码是 vendor CosyVoice3 import——需改回 plus import; _bootstrap_venv 调 install_tts_torch.sh——需改)。

## 八、参考句泄漏(当前最高优先级 bug)

plus zero-shot 随机把参考逐字稿念出来(开头"希望你以后能够做的比我还好呦"): rasfix 三版全泄, seg1 六版 1 泄, seg2 六版 0 泄——概率性。**解法已设计未实施**: whisper segment 时间戳定位泄漏结束点 → ffmpeg 切头 → 交付干净音频。

## 九、质量门(已落地: Paraformer 回验+N 版重试, 见 2026-10-14 需求文档; 下列历史决策记录保留)

- whisper small/medium 中文基线噪声 PER 21-31%(把"呼唤声下"听成"可患生下")——**不可用作错字质检**(信号被噪声淹没)
- scripts/tts_qc.py 已写好(泄漏模糊切除✓/不带调拼音比对/8gram重复/覆盖比)——ASR 换型即可复用
- **方案 A**: 换 FunASR/Paraformer(中文专精, FunAudioLLM 同门, ~1GB 模型, ~1h 集成)——完整质量门
- **方案 B**: whisper 只做泄漏定位(时间戳切头)+覆盖检测; 错字靠用户耳朵, 每段 2 版用户挑
- 拼音口径: 不带调(whisper 调级噪声>>TTS调错收益); 原文→pypinyin; 泄漏=前缀相似度>0.8 切除

## 十、git/推送状态

- 分支 feature/multi_agents_evolve_v4, 最后推送 e4c4703 之后有本地未提交: vendor submodule(tts-funaudio)+RAS patch worker+voices.json(v5)+tts_qc.py 等
- 节点 offline(见二)——节点恢复前不部署
- 前端 ModelsSection 已统一网格+TTS角标; VoiceSection(音色面板)已在 App.tsx 挂载

## 十一、关键文件地图

```
backend/scripts/tts_worker.py      # plus worker+RAS patch(可用; torch 分支已删)
backend/scripts/tts_qc.py          # 质量门(whisper 版, 待换 ASR)
backend/scripts/install_tts_torch.sh # torch 安装脚本(需重写为 plus 版或并存)
backend/services/tts_service.py    # 服务层(配置是 torch 时代——需切回 plus: TTS_MODEL_DIR→8bit, probe→plus import)
backend/services/voice_library.py  # 音色库(✓可用)
backend/services/model_assets.py   # 资产注册(现为 torch 单资产——需加回 8bit)
backend/assets/voices/             # official_female.wav/v4/v5 + voices.json
vendor/tts-funaudio/               # fork submodule(+.venv-ttsfun 保险基线)
~/bw-security-analysis/models/cosyvoice3-8bit|torch/  # 模型
tts-shootout/out/                  # 全部试听样本(rasfix_*/seg*/plus_v5_*等)
```

## 十二、用户工作纪律(压缩后必须保持)

1. 用户没让改就先讨论, "先别动手"必须遵守
2. 方案未验证成型前, 绝不删旧方案/旧环境(plus 删早了导致事故)
3. 遇 bug 修复而非绕行回退(用户:"躲避问题")
4. 持续维护的依赖优先于冻结旧版(用户:"有人维护很重要")——但 transformers 5.17 例外(实证不兼容)
5. 不替用户挑: 机器筛时长两次都失败, 用户耳朵是终审
6. 说做了之前先问产物; 未验证断言=说错(尤其"我们在用 GPU"这类)
7. 本机先验证再上节点(远程试错一轮 2-5 分钟)
8. 错误面完整透传(截断导致盲修的教训)
9. 数据模型: tts-shootout 是临时区; 正式产物在仓库/OPENSECURITY_HOME

## 十三、待办队列(按优先级)

1. **用户决策: 质量门 A(FunASR 完整版) or B(泄漏切除+耳朵)**
2. 实施泄漏自动切除(whisper 时间戳+ffmpeg 切头)——两方案共需
3. TtsService 配置切回 plus(TTS_MODEL_DIR→8bit, probe import, install 脚本)
4. model_assets 加回 cosyvoice3-8bit 资产(或双资产)
5. 服务链路端到端验证(POST /api/tts → plus → 质量门 → 缓存)
6. 用户听两段新书内容验收(seg3/seg4 已备概念: L76+ 取两段)
7. 节点恢复(用户干预)后: 节点 plus 化部署
8. git commit 当前本地改动(vendor submodule+worker+qc)
9. 台账更新

## 2026-10-15 凌晨: TTS 控制台重建(听书深度测试台)——完成

详见 2026-10-15-tts-console-rebuild.md。要点: 段级协议(Legado 模式)/segmentText 断句器(12 用例)/useTtsPlayer 流式接力/三通道试听/默认音色 .ai_env/执行期修 3 真 bug(探测 import 名错误/ASR 毒句重试黑洞 73.5s→19.7s/abort 重试)。CI 全绿。待用户晨验: 控制台 TTS 页真实听感 + Legado 直配实测。


## 2026-10-15: instruct 模式集成完成(短段语速问题终局)

- 根因链条(三轮深挖): zero-shot 短文本慢(净语速154 vs 长文102)+跨次方差±25-30%+懒加载首次慢30-45% —— **instruct 模式**(官方既有多路径,零下载零依赖)一次解决: 指令控制语速/LLM 不看参考 token/预加载消首次慢
- 用户验收: 指令"请用正常语速说一句话"→ 209-212ms/字(满意档); 长文 182ms/字; 方差±5%
- 已落地(commit 9bc84f5+f7160f4): worker 默认 instruct+预加载+seed 参数; 传递链全透传; 测试台(指令分组选择/seed/分段设置); 清理(快节奏/复刻A/B/v2v3)
- 待办: MacMini 可达后 update-restart 同步; 用户在测试台真机验收(指令选择/seed/分段调节)
- 教训: ①官方 instruct2 一直存在——场景路径评估缺失是最大弯路根源 ②"参考韵津传染"解释被数据推翻(输出比参考快)——机制未明处不编解释 ③三次"归因错误"均由实验纠正——实验优先
