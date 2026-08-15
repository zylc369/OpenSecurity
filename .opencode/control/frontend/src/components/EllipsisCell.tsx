/**
 * 表格截断单元格（即时 Tooltip）。
 *
 * 背景：AntD Table 的 `ellipsis: true` 渲染原生 HTML title 属性，
 * 浏览器原生 tooltip 固有 ~1s 延迟——用户悬浮后要等才见全文（被投诉）。
 * 本组件用 Typography 内置 tooltip（AntD Tooltip，mouseEnterDelay=0）替代。
 */
import React from "react";
import { Typography } from "antd";

interface Props {
  text: string | null | undefined;
  /** 文字颜色语义（警示提示用 warning 色） */
  type?: "secondary" | "warning";
  /** 单行最大宽度（px）——超出截断。表格自动列宽不定，需调用方显式约束 */
  maxWidth?: number;
}

const EllipsisCell: React.FC<Props> = ({ text, type = "secondary", maxWidth }) => {
  const content = text ?? "—";
  return (
    <Typography.Text
      type={type}
      ellipsis={{ tooltip: { title: content, mouseEnterDelay: 0, mouseLeaveDelay: 0 } }}
      style={{ fontSize: 12, maxWidth: maxWidth ? `${maxWidth}px` : "100%", display: "inline-block", verticalAlign: "bottom" }}
    >
      {content}
    </Typography.Text>
  );
};

export default EllipsisCell;
