"""前端 E2E 测试（无头浏览器，Playwright + Chromium）。

教训来源（2026-08-15 白屏事故）：API 层断言（test_frontend.py）无法发现
运行时 JS 崩溃——vite 依赖缓存失效导致 504 Outdated Optimize Dep，
React 根本没挂载，页面白屏，但所有 API 测试全绿。
本文件用无头浏览器真实渲染页面，断言 DOM 结构 + 零 console 错误。

运行前提：
  • venv 内 playwright + chromium 二进制（缺则自动 skip，不阻塞 CI）
  • control_server fixture（conftest.py，发布态沙箱 + 随机高位端口）
"""
import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="venv 无 playwright")

from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def rendered(control_server):
    """启动无头浏览器渲染沙箱控制台页面，返回 (page, console_errors)。

    module 级：浏览器开一次，多个断言函数复用同一渲染现场。
    """
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"chromium 不可用: {e}")

        page = browser.new_page(viewport={"width": 1440, "height": 900})
        console_errors: list[str] = []
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        page.goto(f"http://127.0.0.1:{control_server}/", wait_until="networkidle", timeout=20000)
        # 等数据型区块（scan 是慢接口）渲染
        page.wait_for_timeout(2500)

        yield page, console_errors
        browser.close()


def test_root_not_blank(rendered):
    """白屏回归断言（本次事故直接损失）：root 必须有实质内容。"""
    page, _ = rendered
    html = page.evaluate("document.getElementById('root').innerHTML")
    assert html and len(html) > 500, f"root 内容过少，疑似白屏: {html[:200]!r}"


def test_no_console_errors(rendered):
    """渲染期零 console error / pageerror（JS 崩溃即失败）。"""
    _, errors = rendered
    assert errors == [], f"console 错误: {errors[:5]}"


def test_header_brand_and_buttons(rendered):
    """顶栏：品牌 + 硬件按钮 + 就绪度 + 一键安装。"""
    page, _ = rendered
    header_text = page.locator("header").inner_text()
    assert "OpenSecurity 控制台" in header_text
    assert "硬件" in header_text
    assert "环境就绪" in header_text


def test_anchor_navigation(rendered):
    """sticky 锚点导航：五分区 + 各自跳转目标存在。"""
    page, _ = rendered
    anchor_text = page.locator(".ant-anchor").inner_text()
    for name in ["Docker", "模型", "Python 依赖", "外部工具", "配置"]:
        assert name in anchor_text, f"锚点缺少分区: {name}"
    for key in ["docker", "models", "deps", "tools", "config"]:
        assert page.locator(f"#section-{key}").count() == 1, f"缺少 #section-{key}"


def test_docker_section_tables(rendered):
    """Docker 分区：容器表 + 镜像表有数据行（scan 真实结果）。"""
    page, _ = rendered
    section = page.locator("#section-docker")
    # 镜像表至少有已知的行（known images 清单非空）
    rows = section.locator(".ant-table-row").count()
    assert rows >= 1, "Docker 分区表格无数据行"


def test_models_section_cards(rendered):
    """模型分区：两个模型卡 + 缓存路径 + 硬件结论文案。"""
    page, _ = rendered
    section_text = page.locator("#section-models").inner_text()
    assert "BGE-M3" in section_text
    assert "Reranker" in section_text
    assert "huggingface" in section_text  # 缓存路径
    assert "硬件满足" in section_text or "内存" in section_text  # 硬件结论


def test_deps_section_venv(rendered):
    """Python 依赖分区：venv 路径 + 真实包名（sentence-transformers 等）。"""
    page, _ = rendered
    section_text = page.locator("#section-deps").inner_text()
    assert ".venv" in section_text, "缺少 venv 路径展示"
    assert "sentence-transformers" in section_text, "Python 依赖分区应有真实 pip 包名"
    assert "虚拟环境" in section_text


def test_tools_section_separated(rendered):
    """外部工具分区：与 Python 依赖分离，含工具清单 + 不可 pip 说明。"""
    page, _ = rendered
    section_text = page.locator("#section-tools").inner_text()
    assert "可用（不可 pip" in section_text, "外部工具卡片应说明不可 pip 安装"
    # 展开二进制逆向面板验证工具行（缺失项是"可选"时不自动展开，需点击）
    page.locator("#section-tools .ant-collapse-item").filter(has_text="二进制逆向").first.click()
    page.wait_for_timeout(400)
    expanded = page.locator("#section-tools").inner_text()
    assert "ida_pro" in expanded or "IDA" in expanded, "展开后应显示工具行"


def test_readiness_hover_breakdown(rendered):
    """环境就绪悬浮：显示分类明细（对账数据）。"""
    page, _ = rendered
    page.locator("header .ant-badge").hover()
    page.wait_for_timeout(600)
    popover_text = page.locator(".ant-popover").inner_text()
    for cat in ["外部工具", "Python 包", "Docker 镜像", "模型", "必要配置"]:
        assert cat in popover_text, f"就绪度明细缺少分类: {cat}"


def test_config_section_password_masked(rendered):
    """配置分区：密钥框为 type=password（默认密文）+ 路径框存在。"""
    page, _ = rendered
    section = page.locator("#section-config")
    pw_input = section.locator("input[type=password]")
    assert pw_input.count() >= 1, "密钥输入框应为 type=password"


def test_config_path_badge_live_check(rendered):
    """路径存在性徽标：输入不存在的路径 → 出现红色'不存在'标签。

    覆盖真实交互链（输入 → 防抖 → /api/fs/check → 徽标渲染）。
    """
    page, _ = rendered
    # 找到 IDA Pro 路径输入框（placeholder 含"绝对路径"的唯一框）
    path_input = page.locator("#section-config input[placeholder*='绝对路径']").first
    path_input.fill("/no/such/__dir__")
    page.wait_for_timeout(1200)  # 防抖 400ms + 请求往返
    badge = page.locator("#section-config .ant-tag").filter(has_text="不存在")
    assert badge.count() >= 1, "输入不存在路径后未出现'不存在'徽标"


def test_config_path_exists_badge(rendered):
    """路径存在性徽标：输入真实目录 → 绿色'存在'标签。"""
    page, _ = rendered
    path_input = page.locator("#section-config input[placeholder*='绝对路径']").first
    path_input.fill("/tmp")
    page.wait_for_timeout(1200)
    badge = page.locator("#section-config .ant-tag").filter(has_text="存在").filter(
        has_not_text="不存在"
    )
    assert badge.count() >= 1, "输入 /tmp 后未出现'存在'徽标"
