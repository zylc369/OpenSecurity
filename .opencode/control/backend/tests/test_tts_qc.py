"""tts_qc 纯函数层单测（不加载 Paraformer——模型相关由服务端到端覆盖）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.tts_qc import (  # noqa: E402
    QcConfig, QcResult, _has_repeat, _per, _py, _sentences,
)


class TestPinyin:
    def test_bank_polyphone(self):
        # 词组语境选音: 银行→yinhang(非单字默认 yinxing)
        assert _py("银行") == "yinhang"

    def test_tone_insensitive(self):
        # 同音容错: 声调差不算错(不带调口径)
        assert _per(_py("细那康子们"), _py("喜娜康子们")) == 0.0

    def test_initial_error_caught(self):
        # 声母错必抓: 康k vs 汤t
        assert _per(_py("康子们"), _py("汤子们")) > 0.1

    def test_punct_ignored(self):
        assert _py("吃饭了，呜嘞！") == _py("吃饭了呜嘞")


class TestRepeat:
    def test_no_repeat_normal(self):
        assert not _has_repeat(_py("今天天气真好我们出去玩了一下"), 8)

    def test_adjacent_repeat_detected(self):
        assert _has_repeat(_py("盼望着盼望着盼望着盼望着"), 8)

    def test_short_text_no_crash(self):
        assert not _has_repeat("短", 8)


class TestSentences:
    def test_split_three(self):
        assert len(_sentences("第一句。第二句！第三句？")) == 3

    def test_no_punct_fallback(self):
        assert _sentences("无标点文本") == ["无标点文本"]


class TestDataclasses:
    def test_config_defaults_calibrated(self):
        cfg = QcConfig()
        assert cfg.per_limit == 0.10      # Paraformer 干净基线 ~7% × 余量
        assert cfg.max_attempts == 4

    def test_result_frozen(self):
        r = QcResult(ok=True, per=0.05, coverage=0.97,
                     leak_cut=False, repeat=False, detail="t")
        try:
            r.ok = False  # type: ignore[misc]
            raised = False
        except Exception:
            raised = True
        assert raised
