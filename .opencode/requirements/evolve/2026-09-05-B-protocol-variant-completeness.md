# 需求B：协议变体完备性清单
## §1 背景与目标
来源：同上复盘。ICMP type=3 隐藏信道（题目核心线索，内嵌 3KB 引用数据）第 12 轮才被发现——此前仅分析 type 0/8。目标：pcap 取证第 1 轮即完成全变体枚举。
## §2 技术方案
`web-analysis/knowledge-base/web-methodology.md` 补章"协议变体完备性"（约 60 行）：深挖前强制 `tshark -q -z io,phs` + 各层 type/code 直方图；重点表：ICMP 全 type（错误类包引用的原始数据报为独立信息源）、TCP flags 全组合、HTTP 方法、DNS 类型。素材：id 4102。
## §3 实现规范
### §3.1 步骤
1. web-methodology.md 追加章节。验证：含命令模板与判读方法，自包含。
2. 检索 web-analysis 知识库/agent prompt 中既有 pcap 检查清单类文件（`grep -rl "pcap" knowledge-base/ agents/web-analysis.md`）：存在则在清单中追加该章节引用；不存在则记录"无清单"结果并关闭本步。验证：grep 引用可达或有书面关闭记录。
## §4 验收标准
功能：对本案 pcap 按新清单执行，第 1 步即列出 ICMP type 3×32。回归：原方法论章节无损。
## §5 关系
依赖 A 文档的交叉验证理念（互相引用）；不改动代码。
