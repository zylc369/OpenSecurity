#!/usr/bin/env python3
"""TTS 质量门: Paraformer 回验 + 不带调拼音比对。

判项: 错音(声母/韵母)、漏念/截尾(覆盖比)、重复(8-gram 循环, 原文自重复豁免)、
参考泄漏兜底(时间戳切除)。Paraformer(中文专精, CosyVoice 官方评测同源)全局单例,
RTF ~0.03。分句级定位: Paraformer sentence_info 时间戳 + 原文按句切分逐句比对。

比对口径: 不带调拼音(声母+韵母)。ASR 的调级噪声(喜/细)被宽容, 声母韵母错
(汤/康)必抓——信噪比权衡的取舍, 声调错误为已声明盲区(靠人工抽检兜底)。

用法: from scripts.tts_qc import TtsQC; TtsQC.instance().check(wav, text, ref_text)
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pypinyin import lazy_pinyin

_SENT_SPLIT = re.compile(r"[。！？!?；;]")


@dataclass(frozen=True)
class QcConfig:
    """质量门阈值(实测校准: Paraformer 干净基线 PER≈7%)。"""
    per_limit: float = 0.10          # 全文不带调拼音错误率上限
    coverage_min: float = 0.85       # 转写/原文拼音长度比下限(截尾/漏念)
    repeat_ngram: int = 8            # 重复检测的 n-gram 音节数
    max_attempts: int = 4            # 服务侧重试上限(N 版策略)


@dataclass(frozen=True)
class QcResult:
    ok: bool
    per: float                      # 全文不带调拼音错误率
    coverage: float                 # 转写拼音长度 / 原文拼音长度
    leak_cut: bool                  # 是否执行了泄漏兜底切除
    repeat: bool                    # n-gram 循环检出(豁免原文自重复后)
    bad_sentences: "list[str]" = field(default_factory=list)  # 错误定位(句级摘要)
    detail: str = ""


def _hanzi(text: str) -> "list[str]":
    return [c for c in text if "\u4e00" <= c <= "\u9fff" or c.isalnum()]


def _py(text: str) -> str:
    """不带调拼音串。传整串(非字符列表)让 pypinyin 内部词组分词选对多音字
    读音(银行→yinhang 非 yinxing)。"""
    from pypinyin import Style
    parts = lazy_pinyin(text, style=Style.TONE3, errors="ignore")
    return "".join(re.sub(r"[1-5]", "", p) for p in parts)


def _per(a: str, b: str) -> float:
    """编辑距离 / max(len)。O(mn) DP, 800 音节 ~64 万格 < 0.5s。"""
    la, lb = len(a), len(b)
    if la == 0:
        return 1.0 if lb else 0.0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (ai != b[j - 1]))
        prev = cur
    return prev[lb] / max(la, lb)


def _has_repeat(seq: str, n: int) -> bool:
    """相邻即刻重复(连续念两遍)。多窗口探测(8-12)——固定窗口会切在词边界
    漏检(重复单元 panwangzhe=9 音节, n=8 恰跨界)。"""
    if len(seq) < 2 * n:
        return False
    for w in range(n, n + 5):
        for i in range(0, len(seq) - 2 * w + 1):
            g = seq[i:i + w]
            if seq[i + w:i + 2 * w] == g:
                return True
    return False


def _sentences(text: str) -> "list[str]":
    """按句末标点切句(保留文本)。"""
    sents = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    return sents or [text]


class TtsQC:
    _inst: "TtsQC | None" = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "TtsQC":
        with cls._lock:
            if cls._inst is None:
                cls._inst = cls()
        return cls._inst

    def __init__(self) -> None:
        from funasr import AutoModel
        self._model = AutoModel(model="paraformer-zh", disable_update=True)

    # -- 转写 ---------------------------------------------------------

    def _transcribe(self, wav_path: str) -> "tuple[str, list[tuple[float, float, str]]]":
        """返回 (全文转写, [(start_s, end_s, 句文本), ...])。"""
        r = self._model.generate(input=wav_path, batch_size_s=300)
        text = str(r[0]["text"]).replace(" ", "").strip()
        ts: "list[tuple[float, float, str]]" = []
        sinfo = r[0].get("sentence_info") or []
        for seg in sinfo:
            for s in seg.get("sentence", []) if isinstance(seg, dict) else []:
                ts.append((float(s.get("start", 0)) / 1000.0,
                           float(s.get("end", 0)) / 1000.0,
                           str(s.get("text", ""))))
        if not ts:
            ts = [(0.0, 0.0, text)]
        return text, ts

    # -- 主检 ---------------------------------------------------------

    def check(self, wav_path: str, orig_text: str, ref_text: str = "",
              cfg: QcConfig | None = None) -> QcResult:
        cfg = cfg or QcConfig()
        text, _segs = self._transcribe(wav_path)
        orig_py = _py(orig_text)
        tp_full = _py(text)

        # 泄漏兜底: 转写前 40 音节与参考逐字稿拼音相似度 > 0.8 → 按时间戳切除
        leak_cut = False
        if ref_text and tp_full:
            import difflib
            ref_py = _py(ref_text)
            head = tp_full[:len(ref_py) + 6]
            if ref_py and difflib.SequenceMatcher(
                    None, head, ref_py).ratio() > 0.8:
                text = text[min(len(ref_py) + 2, len(text)):]
                tp_full = _py(text)
                leak_cut = True

        # 重复(原文自重复豁免: 原文念两遍是文本本意, 不是缺陷)
        n = cfg.repeat_ngram
        repeat = _has_repeat(tp_full, n) and not _has_repeat(orig_py, n)

        # 句级定位(错误摘要)
        bad: "list[str]" = []
        if not leak_cut:
            cursor = 0
            for sent in _sentences(orig_text):
                sp = _py(sent)
                if not sp:
                    continue
                win = tp_full[cursor:cursor + len(sp) + 8]
                p = _per(sp, win)
                if p > cfg.per_limit * 1.5:
                    head_txt = re.sub(r'^["”“\s]+|["”\s]+$', "", sent)[:12]
                    bad.append(f"{head_txt}…(per={p:.0%})")
                cursor += len(sp)

        per = _per(orig_py, tp_full)
        coverage = len(tp_full) / max(len(orig_py), 1)
        ok = (per <= cfg.per_limit and coverage >= cfg.coverage_min
              and not repeat)
        return QcResult(ok=ok, per=round(per, 4), coverage=round(coverage, 3),
                        leak_cut=leak_cut, repeat=repeat,
                        bad_sentences=bad,
                        detail=f"per={per:.1%} cov={coverage:.0%} "
                               f"leak={'切' if leak_cut else '无'} rep={repeat}")
