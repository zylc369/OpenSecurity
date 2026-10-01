/**
 * 配置页（#/config）——服务端分类驱动的配置管理面。
 *
 * 布局（Apple 系统设置风; 样式见 global.css .config-*）:
 *   左: 分类导航（图标+desc; 点击平滑滚动到对应分类卡; 滚动联动高亮）
 *   右: 全部分类卡平铺（CSS 多列瀑布，一屏纵览全部配置; 窄屏自动单列）
 *      + 顶部 sticky 保存条（全局唯一保存入口，dirty 提示）
 * 页面组成零定制: 分类/顺序/描述全部来自 /api/config/meta（surfaces=["config"]），
 * 前端不硬编码任何配置项判断（图标映射除外——纯视觉）。
 */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Card, Space, Tag, Typography } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import { useAllConfig, useConfigMeta } from "../hooks";
import { groupByCategory, masonryDistribute, dirtyUpdates } from "../utils/configGrouping";
import { categoryIcon } from "../constants/configIcons";
import ConfigFieldRow from "../components/ConfigFieldRow";
import type { ConfigMap } from "../types";

const ConfigPage: React.FC = () => {
  const { message } = AntApp.useApp();
  const meta = useConfigMeta("config");
  const { data: configs, loading, save } = useAllConfig("config");
  const [values, setValues] = useState<ConfigMap>({});
  const [saving, setSaving] = useState(false);
  const [active, setActive] = useState("");
  // 程序化滚动（导航点击）期间抑制滚动联动，避免途经分类的高亮闪烁
  const jumping = useRef(false);
  // 平铺列数（1..3）: 按容器宽动态计算（440px 最小列宽）; 容器宽与列数无关，无回环
  const tilesRef = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(2);

  useEffect(() => {
    if (configs) setValues(configs);
  }, [configs]);

  const groups = useMemo(
    () => (meta.data ? groupByCategory(meta.data.entries, meta.data.categories) : []),
    [meta.data]);

  useLayoutEffect(() => {
    const el = tilesRef.current;
    if (!el) return;
    const update = () => {
      setCols(Math.max(1, Math.min(3, Math.floor((el.clientWidth + 14) / 454))));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [meta.data]);

  // 瀑布流分列: 最短列优先，各列收尾齐平（替代 CSS 多列的列优先堆叠）
  const columns = useMemo(
    () => (meta.data ? masonryDistribute(groups, meta.data.entries, cols) : []),
    [groups, meta.data, cols]);

  // 滚动联动：视口顶部之下最靠下的分类卡 = 当前分类（列平铺下并列卡取先者）
  useEffect(() => {
    const onScroll = () => {
      if (jumping.current) return;
      let cur = groups[0]?.code ?? "";
      let bestTop = -Infinity;
      for (const g of groups) {
        const el = document.getElementById(`cat-${g.code}`);
        if (!el) continue;
        const top = el.getBoundingClientRect().top;
        if (top <= 150 && top > bestTop) { bestTop = top; cur = g.code; }
      }
      setActive(cur);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [groups]);

  const jumpTo = (code: string) => {
    setActive(code);
    jumping.current = true;
    document.getElementById(`cat-${code}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => { jumping.current = false; }, 700);
  };

  // dirty 与提交口径一致（dirtyUpdates 的 trim 比较）——纯空格编辑不再出现
  // "按钮亮但提示没有修改"的不一致
  const dirty = useMemo(() => {
    if (!configs || !meta.data) return false;
    return (
      Object.keys(dirtyUpdates(values, configs, meta.data.entries)).length > 0
    );
  }, [values, configs, meta.data]);

  const requiredMissing = useMemo(() => {
    if (!meta.data) return [];
    return Object.entries(meta.data.entries)
      .filter(([k, m]) => m.required && !(values[k] ?? "").trim())
      .map(([, m]) => m.label);
  }, [meta.data, values]);

  const doSave = async () => {
    setSaving(true);
    try {
      const entries = meta.data?.entries ?? {};
      // 只提交变化键（值接口返回生效值——全量回传会把默认值冻结进 .ai_env，
      // 服务端后续调默认不再跟随）
      const updates = dirtyUpdates(values, configs ?? {}, entries);
      if (Object.keys(updates).length === 0) {
        message.info("没有修改需要保存");
        return;
      }
      await save(updates);
      message.success("配置已保存（已自动去除首尾空格）");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading || !meta.data) {
    return <Typography.Text type="secondary">加载中…</Typography.Text>;
  }
  if (groups.length === 0) {
    return <Typography.Text type="secondary">无配置项</Typography.Text>;
  }

  // 守卫后捕获（JSX 回调内属性窄化会丢失）
  const entries = meta.data.entries;

  return (
    <Space direction="vertical" size={14} style={{ width: "100%" }}>
      {requiredMissing.length > 0 && (
        <Alert
          type="warning" showIcon
          message={`必要配置缺失：${requiredMissing.join("、")}`}
        />
      )}
      <div className="config-layout">
        <nav className="config-cats" aria-label="配置分类">
          {groups.map((g) => {
            const GIcon = categoryIcon(g.code);
            return (
              <button
                key={g.code}
                type="button"
                className={`config-cat${g.code === active ? " on" : ""}`}
                onClick={() => jumpTo(g.code)}
              >
                <GIcon />
                <span>{g.desc}</span>
              </button>
            );
          })}
        </nav>
        <div className="config-main">
          <div className="config-savebar">
            <Button
              type="primary" icon={<SaveOutlined />} loading={saving}
              disabled={!dirty}
              onClick={() => void doSave()}
            >
              保存{dirty ? "（有未保存修改）" : ""}
            </Button>
          </div>
          <div className="config-tiles" ref={tilesRef}>
            {columns.map((bucket, i) => (
              <div className="config-col" key={i}>
                {bucket.map((g) => {
                  const GIcon = categoryIcon(g.code);
                  return (
                    <Card
                      key={g.code}
                      id={`cat-${g.code}`}
                      size="small"
                      className="config-tile"
                      title={
                        <Space size={8}>
                          <GIcon />
                          <span>{g.desc}</span>
                          <Tag style={{ marginInlineEnd: 0 }}>{g.keys.length} 项</Tag>
                        </Space>
                      }
                    >
                      {g.keys.map((key) => (
                        <ConfigFieldRow
                          key={key}
                          meta={entries[key]}
                          value={values[key] ?? ""}
                          onChange={(v) => setValues((s) => ({ ...s, [key]: v }))}
                        />
                      ))}
                    </Card>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
    </Space>
  );
};

export default ConfigPage;
