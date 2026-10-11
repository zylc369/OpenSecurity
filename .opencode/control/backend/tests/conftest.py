
# test_control.py 是自包含直跑脚本（自带极简测试框架），非 pytest 用例——
# 其 def test(name) 注册器会被 pytest 误收集（fixture 'name' not found），
# 且 @test 装饰的 wrapper 也非 pytest 形态。整体排除收集;消费方
# （test_api_guard 等）`from tests.test_control import test, ...` 不受影响。
collect_ignore = ["test_control.py"]
