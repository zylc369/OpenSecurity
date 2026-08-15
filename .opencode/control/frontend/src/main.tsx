import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./global.css";

/**
 * 主题：现代浅色（Apple 风格取向）
 *  • 中性色基底（#fafafa 页面底 / 纯白表面），不依赖重背景
 *  • 圆角统一 8px（卡片）/ 6px（控件），柔和但有秩序
 *  • 品牌蓝降饱和（#0A6CFF 偏 iOS 蓝），不再是 AntD 默认蓝
 *  • 字体栈优先 SF Pro（Mac 原生），与系统观感一致
 */
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          borderRadius: 6,
          colorPrimary: "#0A6CFF",
          colorBgLayout: "#f5f5f7",          // 苹果系页面灰底
          colorTextBase: "#1d1d1f",
          colorBorderSecondary: "rgba(0,0,0,0.08)",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        },
        components: {
          Card: {
            bodyPadding: 16,
            paddingLG: 20,
            colorBorderSecondary: "rgba(0,0,0,0.06)",
            boxShadowTertiary: "0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(0,0,0,0.04)",
          },
          Layout: { headerHeight: 56, headerBg: "transparent", headerPadding: "0 20px" },
          Table: { headerBg: "rgba(0,0,0,0.02)", cellPaddingBlockSM: 7 },
          Button: { fontWeight: 500 },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
