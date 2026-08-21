import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { usePoll } from "./hooks/usePoll";
import { api, type RuntimeStatus } from "./api/client";
import { StatusDot } from "./components/ui";
import { LanguageSelect, useI18n } from "./i18n";
import Overview from "./pages/Overview";
import Models from "./pages/Models";
import Runtime from "./pages/Runtime";
import DFlash from "./pages/DFlash";
import ApiPage from "./pages/ApiPage";
import Benchmark from "./pages/Benchmark";
import Agents from "./pages/Agents";
import Monitoring from "./pages/Monitoring";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";

export default function App() {
  const { t } = useI18n();
  const loc = useLocation();
  const { data: rt } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 6000);
  const dotKind =
    rt?.status === "running" ? "ok"
    : rt?.status === "starting" || rt?.status === "stopping" ? "warn"
    : rt?.status === "error" ? "err" : "idle";

  const nav = [
    { to: "/", key: "nav.overview" as const },
    { to: "/models", key: "nav.models" as const },
    { to: "/runtime", key: "nav.runtime" as const },
    { to: "/dflash", key: "nav.dflash" as const },
    { to: "/api", key: "nav.api" as const },
    { to: "/benchmark", key: "nav.benchmark" as const },
    { to: "/agents", key: "nav.agents" as const },
    { to: "/monitoring", key: "nav.monitoring" as const },
    { to: "/logs", key: "nav.logs" as const },
    { to: "/settings", key: "nav.settings" as const },
  ];

  return (
    <div className="shell">
      <nav className="sidebar" aria-label={t("nav.aria")}>
        <div className="sidebar-brand">
          <StatusDot kind={dotKind} pulse={rt?.status === "starting"} />
          {t("app.name")}
        </div>
        {nav.map((n) => (
          <NavLink
            key={n.to} to={n.to} end={n.to === "/"}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            {t(n.key)}
          </NavLink>
        ))}
        <div className="sidebar-foot">
          <LanguageSelect />
        </div>
      </nav>
      <main className="main">
        <div className={`page${loc.pathname === "/models" ? " wide" : ""}`}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/models" element={<Models />} />
            <Route path="/runtime" element={<Runtime />} />
            <Route path="/dflash" element={<DFlash />} />
            <Route path="/api" element={<ApiPage />} />
            <Route path="/benchmark" element={<Benchmark />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/monitoring" element={<Monitoring />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
