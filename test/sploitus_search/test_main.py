# -*- coding: utf-8 -*-
"""sploitus_search.py main() 命令行入口测试。

覆盖：stdout 输出、--output 文件输出、失败时 sys.exit(1)。
"""
import json
import sys
from unittest.mock import patch, MagicMock


def test_main_stdout(sploitus, capsys):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "exploits": [{"id": "E1", "title": "Test Exploit", "type": "exploit", "href": "https://ex.com/1"}],
                "exploits_total": 1,
            },
        )
        sys.argv = ["sploitus_search.py", "test query"]
        sploitus.main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["results"][0]["title"] == "Test Exploit"


def test_main_file_output(sploitus, tmp_path):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"exploits": [], "exploits_total": 0},
        )
        outfile = tmp_path / "results.json"
        sys.argv = ["sploitus_search.py", "test", "--output", str(outfile)]
        sploitus.main()
        data = json.loads(outfile.read_text())
        assert data["success"] is True


def test_main_exit_code_on_failure(sploitus):
    from requests.exceptions import Timeout
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.exceptions = __import__("requests.exceptions", fromlist=["Timeout"])
        mock_req.post.side_effect = Timeout("timed out")
        sys.argv = ["sploitus_search.py", "test"]
        try:
            sploitus.main()
            assert False, "应该 sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1


def test_main_type_parameter(sploitus, capsys):
    """验证 --type tools 传到 API 请求。"""
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200, json=lambda: {"exploits": [], "exploits_total": 0}
        )
        sys.argv = ["sploitus_search.py", "test", "--type", "tools"]
        sploitus.main()
        body = mock_req.post.call_args.kwargs["json"]
        assert body["type"] == "tools"


def test_main_limit_parameter(sploitus, capsys):
    """验证 --limit 传到 search()。"""
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "exploits": [{"id": f"E{i}", "title": f"T{i}", "type": "exploit", "href": ""} for i in range(10)],
                "exploits_total": 10,
            },
        )
        sys.argv = ["sploitus_search.py", "test", "--limit", "3"]
        sploitus.main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["results"]) == 3
