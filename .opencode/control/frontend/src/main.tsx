import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm, // 亮色（管理台惯例，长时间看不累）
        token: { borderRadius: 6 },
        components: {
          Layout: { headerHeight: 52, headerBg: "#001529" }, // 深色顶栏突出品牌区
          Card: { bodyPadding: 16 },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
