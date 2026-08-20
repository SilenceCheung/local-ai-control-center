import { NavLink, Route, Routes } from "react-router-dom";
import { usePoll } from "./hooks/usePoll";
import { api, type RuntimeStatus } from "./api/client";
import { StatusDot } from "./components/ui";
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

const NAV = [
  { to: "/", label: "Overview" },
  { to: "/models", label: "Models" },
  { to: "/runtime", label: "Runtime" },
  { to: "/dflash", label: "DFlash" },
  { to: "/api", label: "API" },
  { to: "/benchmark", label: "Benchmark" },
  { to: "/agents", label: "Agents" },
  { to: "/monitoring", label: "Monitoring" },
  { to: "/logs", label: "Logs" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const { data: rt } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 6000);
  const dotKind =
    rt?.status === "running" ? "ok"
    : rt?.status === "starting" || rt?.status === "stopping" ? "warn"
    : rt?.status === "error" ? "err" : "idle";

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main navigation">
        <div className="sidebar-brand">
          <StatusDot kind={dotKind} pulse={rt?.status === "starting"} />
          Local AI Control Center
        </div>
        {NAV.map((n) => (
          <NavLink
            key={n.to} to={n.to} end={n.to === "/"}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      <main className="main">
        <div className="page">
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
