import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import StatusPage from "./pages/StatusPage";
import DepsPage from "./pages/DepsPage";
import DockerPage from "./pages/DockerPage";
import ConfigPage from "./pages/ConfigPage";
import HardwarePage from "./pages/HardwarePage";
import "./styles.css";

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1>OpenSecurity 控制台</h1>
          <nav className="nav">
            <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              状态总览
            </NavLink>
            <NavLink to="/deps" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              依赖管理
            </NavLink>
            <NavLink to="/docker" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              Docker
            </NavLink>
            <NavLink to="/hardware" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              硬件
            </NavLink>
            <NavLink to="/config" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              配置
            </NavLink>
          </nav>
        </header>
        <main className="app-main">
          <Routes>
            <Route path="/" element={<StatusPage />} />
            <Route path="/deps" element={<DepsPage />} />
            <Route path="/docker" element={<DockerPage />} />
            <Route path="/hardware" element={<HardwarePage />} />
            <Route path="/config" element={<ConfigPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
