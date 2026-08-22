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
    # 品牌为双行排版（OpenSecurity / 控制台 分行）
    assert "OpenSecurity" in header_text and "控制台" in header_text
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
    """Python 依赖分区：venv 路径 + 真实包数据（分页后第一页取当前行验证）。"""
    page, _ = rendered
    section_text = page.locator("#section-deps").inner_text()
    assert ".venv" in section_text, "缺少 venv 路径展示"
    assert "虚拟环境" in section_text
    # 分页默认 5 行/页——数据真实性由 API 测试覆盖（test_api_scan_coexists），
    # 此处验证表格确有包行 + 分页汇总文案
    assert "条/页" in section_text, "应显示分页信息"


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
    """环境就绪悬浮：每类显示 X/Y + 单位 + 缺失项（对账数据），且用词与卡片标题一致。"""
    page, _ = rendered
    page.locator("header .ant-badge").hover()
    page.wait_for_timeout(600)
    popover_text = page.locator(".ant-popover:not(.ant-popover-hidden)").first.inner_text()

    # 每类必须有 X/Y 数字（曾因自定义组件包 Descriptions.Item 导致内容区不渲染）
    import re
    for cat, unit in [("Docker", "镜像"), ("模型", "就绪"), ("Python 依赖", "已装"),
                      ("外部工具", "可用"), ("配置", "完整")]:
        assert cat in popover_text, f"就绪度明细缺少分类: {cat}"
        assert re.search(rf"{cat}\n\d+/\d+ {unit}", popover_text), (
            f"{cat} 行应含 X/Y {unit}，实际:\n{popover_text}"
        )
    # 用词与卡片标题一字不差（收口验证）
    for key, title in [("docker", "Docker"), ("models", "模型"), ("deps", "Python 依赖"),
                       ("tools", "外部工具"), ("config", "配置")]:
        card_title = page.locator(f"#section-{key} .ant-card-head-title").inner_text().strip()
        assert card_title.startswith(title), f"卡片 {key} 标题 {card_title!r} 与常量 {title!r} 不一致"

    # 总数对账：Popover 标题的总数 = Σ 各类 total（缺失时）
    m = re.search(r"环境就绪 (\d+)/(\d+)", popover_text)
    assert m, "Popover 标题应含 环境就绪 X/Y"
    totals = [int(g[1]) for g in re.findall(r"(\d+)/(\d+) (?:镜像|就绪|已装|可用|完整)", popover_text)]
    assert sum(totals) == int(m.group(2)), "总数应等于各类之和（对账闭合）"


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


# ─── 迭代 3（2026-08-15 用户反馈 UI 打磨）─────────────────


def test_install_button_disabled_readable(rendered):
    """一键安装按钮文字可读（两态断言：enabled 主色白字 / disabled 墨色低透明度）。

    glm-ocr 资产状态两种都可能出现（主环境 mlx_vlm 检测 + HF 缓存）——
    按钮呈 enabled（白字）或 disabled（墨色）都属设计内颜色。
    """
    page, _ = rendered
    btn = page.locator("header button:has-text('一键安装')").first
    color = btn.evaluate("el => getComputedStyle(el).color")
    assert color.startswith(
        ("rgba(0, 0, 0", "rgba(29, 29, 31", "rgb(255, 255, 255")
    ), f"应为设计内颜色（enabled 白 / disabled 墨色低透明）: {color}"


def test_readiness_popover_within_viewport(rendered):
    """就绪度 Popover 不超出视口右缘。"""
    page, _ = rendered
    page.locator("header .ant-badge").hover()
    page.wait_for_timeout(600)
    box = page.locator(".ant-popover:not(.ant-popover-hidden)").first.bounding_box()
    assert box, "popover 未出现"
    vw = page.evaluate("window.innerWidth")
    assert box["x"] + box["width"] <= vw + 1, (
        f"popover 右缘 {box['x'] + box['width']:.0f} 超出视口 {vw}"
    )


def test_python_deps_pagination(rendered):
    """Python 依赖分页：分页器存在 + 默认每页 5 行。"""
    page, _ = rendered
    deps = page.locator("#section-deps")
    assert deps.locator(".ant-pagination").count() == 1, "缺少分页器"
    rows = deps.locator(".ant-table-tbody tr.ant-table-row").count()
    assert rows == 5, f"默认每页应 5 行，实际 {rows}"


def test_python_deps_search_filters(rendered):
    """搜索框模糊过滤包名。"""
    page, _ = rendered
    deps = page.locator("#section-deps")
    search = deps.locator("input[placeholder*='搜索包名']")
    search.fill("sentence")
    page.wait_for_timeout(400)
    names = deps.locator(".ant-table-tbody tr.ant-table-row td:first-child").all_inner_texts()
    assert names == ["sentence-transformers"], f"搜索结果应为 1 行，实际 {names}"


def test_no_native_title_in_tables(rendered):
    """表格截断列不再用原生 title 属性（~1s 延迟源头，用户投诉点）。"""
    page, _ = rendered
    native = page.evaluate(
        "() => document.querySelectorAll('#section-deps .ant-table-tbody td [title]').length"
    )
    assert native == 0, f"存在 {native} 个原生 title 属性（应有即时 AntD tooltip）"


def test_config_grid_two_columns(rendered):
    """配置分区响应式网格：宽屏下表单项 x 坐标应有多个值（≥2 列）。"""
    page, _ = rendered
    xs = page.evaluate(
        """() => {
            const items = document.querySelectorAll('#section-config .ant-form-item');
            const xs = new Set();
            items.forEach(el => { const r = el.getBoundingClientRect(); if (r.width > 0) xs.add(Math.round(r.x)); });
            return [...xs];
        }"""
    )
    assert len(xs) >= 2, f"配置表单仍单列: x 坐标 {xs}"


def test_anchor_refresh_button(rendered):
    """锚点行刷新按钮：存在且点击触发全量重扫（/api/scan 重新请求）。"""
    page, _ = rendered
    # 硬件 Popover 未打开时（懒渲染），页面上的 reload 按钮即锚点行那个
    btn = page.locator("button:has(.anticon-reload)")
    assert btn.count() == 1, f"锚点行应有 1 个刷新按钮，实际 {btn.count()}"

    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url) if "/api/scan" in r.url else None)
    btn.first.click()
    page.wait_for_timeout(2500)
    assert len(requests) >= 1, "点击刷新后应重新请求 /api/scan"


def test_hardware_popover(rendered):
    """硬件 Popover：宽度紧凑（≤360px）+ 标题旁刷新按钮生效 + 无 0GHz 伪值。"""
    page, _ = rendered
    page.locator("header button:has-text('硬件')").click()
    page.wait_for_timeout(600)
    pop = page.locator(".ant-popover:not(.ant-popover-hidden)").first
    text = pop.inner_text()
    box = pop.bounding_box()
    assert box["width"] <= 360, f"硬件 Popover 应紧凑（≤360px），实际 {box['width']:.0f}px"
    assert "0GHz" not in text, "不应显示伪值 0GHz（Apple Silicon psutil 返回 4MHz）"
    assert "Apple" in text or "GPU" in text

    reqs: list[str] = []
    page.on("request", lambda r: reqs.append(r.url) if "/api/hardware" in r.url else None)
    pop.locator("button:has(.anticon-reload)").click()
    page.wait_for_timeout(1200)
    assert len(reqs) >= 1, "点击 Popover 内刷新按钮应重新请求 /api/hardware"


# ─── 迭代 7（2026-08-15 顶栏/锚点行现代化重构）────────────


def test_header_full_bleed_and_alignment(rendered):
    """顶栏通栏（body margin 已 reset）+ 品牌图标与文字块精确居中。"""
    page, _ = rendered
    info = page.evaluate(
        """() => {
            const header = document.querySelector('header');
            const hb = header.getBoundingClientRect();
            // 品牌圆角图标容器（34×34 圆角 9px 渐变块）
            const iconBox = [...header.querySelectorAll('div')].find(d => {
                const r = d.getBoundingClientRect();
                return Math.round(r.width) === 34 && Math.round(r.height) === 34;
            });
            const spans = [...header.querySelectorAll('span')];
            const title = spans.find(s => s.textContent === 'OpenSecurity');
            const sub = spans.find(s => s.textContent === '控制台');
            if (!iconBox || !title || !sub) return null;
            const ib = iconBox.getBoundingClientRect();
            const tb = title.getBoundingClientRect();
            const sb = sub.getBoundingClientRect();
            const textTop = Math.min(tb.y, sb.y);
            const textBot = Math.max(tb.y + tb.height, sb.y + sb.height);
            return {
                fullBleed: hb.x === 0 && Math.round(hb.width) === window.innerWidth,
                deltaCenter: Math.abs((ib.y + ib.height / 2) - (textTop + textBot) / 2),
            };
        }"""
    )
    assert info, "顶栏品牌元素未找到"
    assert info["fullBleed"], f"顶栏应通栏（x=0, w=innerWidth），实际偏移 {info.get('fullBleed')}"
    assert info["deltaCenter"] < 1.5, f"图标与文字块中心偏差 {info['deltaCenter']:.2f}px（应 <1.5）"


def test_modern_header_not_dark_default(rendered):
    """顶栏不再是 AntD 默认深蓝（#001529）——应为浅色毛玻璃。"""
    page, _ = rendered
    bg = page.locator("header").evaluate("el => getComputedStyle(el).backgroundColor")
    # rgba(255,255,255,0.78) 序列化后应为 rgba 白色系；#001529 = rgb(0,21,41)
    assert "(255, 255, 255" in bg, f"顶栏应为浅色毛玻璃，实际背景 {bg}"
    blur = page.locator("header").evaluate("el => getComputedStyle(el).backdropFilter")
    assert "blur" in (blur or ""), f"顶栏应有毛玻璃 backdropFilter，实际 {blur!r}"


# ─── 迭代 5（2026-08-15 布局细节）─────────────────────────


def test_model_disk_label(rendered):
    """模型卡磁盘占用文案：'磁盘 X.XXGB'（替代含混的'已缓存'）。"""
    page, _ = rendered
    text = page.locator("#section-models").inner_text()
    assert "磁盘 4.27GB" in text and "磁盘 2.14GB" in text, "应显示'磁盘 X.XXGB'"
    assert "已缓存" not in text, "'已缓存'文案应清除"


def test_tools_hint_truncated_with_tooltip(rendered):
    """外部工具安装提示超长截断 + 悬浮即时显示全文。"""
    page, _ = rendered
    page.locator("#section-tools .ant-collapse-item").filter(has_text="二进制逆向").first.click()
    page.wait_for_timeout(400)
    hint_cell = page.locator("#section-tools .ant-table-tbody tr:has-text('GoReSym') td").nth(4)
    truncated = hint_cell.evaluate(
        "el => { const t = el.querySelector('.ant-typography') || el; return t.scrollWidth > t.clientWidth + 1; }"
    )
    assert truncated, "GoReSym 安装提示应被截断（超长 URL）"
    hint_cell.hover()
    page.wait_for_timeout(150)
    tip = page.locator(".ant-tooltip:visible")
    assert tip.count() >= 1, "悬浮 150ms 内应显示完整提示"
    assert "mandiant" in tip.first.inner_text()


def test_config_deepseek_grouped_half_width(rendered):
    """DeepSeek 密钥与模型名：同一行（组内横排）+ 整组占 50% 宽。

    标记语义：密钥标'必要'（红）；模型名标'可选'且悬浮显示默认值
    （默认值来自后端 /api/config/meta 的 default_value，单一数据源）。
    """
    page, _ = rendered
    cfg = page.locator("#section-config")
    ds_item = cfg.locator(".ant-form-item").filter(has_text="DeepSeek")
    assert ds_item.count() >= 1, "应有 DeepSeek 配置组"
    label_text = ds_item.first.locator(".ant-form-item-label").inner_text()
    assert "必要" in label_text, "密钥应标'必要'"
    assert "可选" in label_text, "模型名应标'可选'"

    # 可选标记悬浮 → 显示默认值（后端收口数据）
    ds_item.first.locator(".ant-tag:has-text('可选')").hover()
    page.wait_for_timeout(400)
    tip = page.locator(".ant-tooltip:not(.ant-tooltip-hidden):has-text('此项可不配置')")
    assert tip.count() >= 1, "悬浮可选标记应显示说明"
    assert "deepseek-v4-flash" in tip.first.inner_text(), "说明应含默认值"

    container = cfg.locator(".ant-row").first.bounding_box()
    box = ds_item.first.bounding_box()
    assert box and container
    assert abs(box["width"] / container["width"] - 0.5) < 0.08, (
        f"组宽应约 50%，实际 {box['width'] / container['width'] * 100:.0f}%"
    )
    inputs = ds_item.first.locator("input")
    ys = [inputs.nth(i).bounding_box()["y"] for i in range(inputs.count())]
    assert len(ys) == 2 and max(ys) - min(ys) < 10, (
        f"密钥与模型名应同行横排，实际 y 坐标 {ys}"
    )


def test_docker_stop_confirm(rendered):
    """容器停止按钮：二次确认（防误点破坏图数据库）。"""
    page, _ = rendered
    stop_btn = page.locator("#section-docker button:has-text('停止')")
    if stop_btn.count() == 0:
        pytest.skip("当前无运行中容器")
    stop_btn.first.click()
    page.wait_for_timeout(500)
    confirm = page.locator(".ant-popover:not(.ant-popover-hidden):has-text('确定停止')")
    assert confirm.count() >= 1, "点击停止应弹出二次确认框"
    assert "确定停止" in confirm.first.inner_text()
    # 取消路径（AntD 中文按钮渲染为"取 消"带空格；关闭后节点保留 hidden class——
    # 断言"无可见确认框"而非"节点不存在"）
    confirm.first.locator("button").filter(has_text="取").first.click()
    page.wait_for_timeout(800)
    visible = page.locator(".ant-popover:not(.ant-popover-hidden):has-text('确定停止')")
    assert visible.count() == 0, "取消后确认框应关闭（不可见）"
