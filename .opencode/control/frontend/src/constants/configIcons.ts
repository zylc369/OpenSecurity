/**
 * 配置分类图标映射（code → antd 图标组件）。
 *
 * 纯视觉映射——分类的名称/顺序/描述均由服务端权威下发（ConfigMetaResponse
 * .categories），图标仅为侧栏/标题的视觉辅助，缺失时回退 AppstoreOutlined。
 */
import {
  AppstoreOutlined, CloudServerOutlined, CodeOutlined, DashboardOutlined,
  GlobalOutlined, RobotOutlined, SyncOutlined, ThunderboltOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";

export const CONFIG_CATEGORY_ICONS: Record<string, ComponentType> = {
  tools: ToolOutlined,
  models: RobotOutlined,
  proxy: GlobalOutlined,
  behavior: ThunderboltOutlined,
  developer: CodeOutlined,
  remote: CloudServerOutlined,
  remote_tuning: SyncOutlined,
  system: DashboardOutlined,
};

/** 分类图标（未知 code 回退 AppstoreOutlined——契约演进容错） */
export function categoryIcon(code: string): ComponentType {
  return CONFIG_CATEGORY_ICONS[code] ?? AppstoreOutlined;
}
