import Charts
import SwiftUI

struct AgentsPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("Agents").font(.largeTitle.weight(.semibold))
                    Spacer()
                    Button(store.agentTesting ? "Testing…" : "Test Connection") {
                        store.agentTesting = true
                        Task {
                            store.agentTest = await store.testAgents()
                            store.agentTesting = false
                            await store.loadOverviewExtras()
                        }
                    }
                    .disabled(store.agentTesting)
                }
                Text("One alias, one endpoint. Status is honest: Connected means this client sent traffic in the last 30 minutes.")
                    .foregroundStyle(.secondary)

                if let test = store.agentTest {
                    GroupBox("Connection Test") {
                        if test.ok {
                            Text("models OK · chat OK · \(Formatters.num(test.elapsedS, digits: 2))s")
                                .foregroundStyle(Palette.ok)
                            if let reply = test.reply {
                                Text("reply: \(reply)").font(.caption.monospaced())
                            }
                        } else {
                            ErrorBanner(title: "Connection test failed", detail: test.error)
                        }
                    }
                }

                ForEach(store.agents) { agent in
                    GroupBox(agent.name) {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text(statusLabel(agent)).foregroundStyle(agent.status == "connected" ? Palette.ok : .secondary)
                                Text(agent.protocolName?.uppercased() ?? "")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                            }
                            Text(agent.instructions)
                                .font(.callout)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            if agent.notSupportedNatively != true {
                                row("Base URL", agent.config.baseUrl)
                                row("API Key", agent.config.apiKey)
                                row("Model", agent.config.model)
                            }
                            if let snippet = agent.configSnippet {
                                HStack {
                                    Text("Config snippet").font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                    Button("Copy") { store.copy(snippet) }.controlSize(.small)
                                }
                                Text(snippet)
                                    .font(.system(.caption, design: .monospaced))
                                    .textSelection(.enabled)
                                    .padding(8)
                                    .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.04)))
                            }
                        }
                        .padding(8)
                    }
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
        .task { await store.loadOverviewExtras() }
    }

    private func statusLabel(_ a: AgentInfo) -> String {
        if a.notSupportedNatively == true { return "Needs Anthropic gateway" }
        switch a.status {
        case "connected": return "Connected"
        case "seen_before": return "Seen earlier"
        default: return "Unknown"
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).foregroundStyle(.secondary).frame(width: 80, alignment: .leading)
            Text(v).font(.body.monospaced()).lineLimit(1)
            Spacer()
            Button("Copy") { store.copy(v) }.controlSize(.small)
        }
    }
}

struct MonitoringPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Monitoring").font(.largeTitle.weight(.semibold))
                Text("Live samples from the control plane. GPU utilization is not exposed by macOS without elevated privileges — not shown rather than faked.")
                    .foregroundStyle(.secondary)
                if let adv = store.memoryAdvisory { AdvisoryBanner(advisory: adv) }

                GroupBox("System") {
                    VStack(spacing: 12) {
                        metric("Unified Memory",
                               "\(Formatters.num(store.latestSample?.memUsedGb)) GB",
                               series: store.samples.map(\.memUsedGb))
                        metric("Memory Pressure",
                               Formatters.pressure(store.latestSample?.pressureLevel),
                               series: store.samples.map { $0.pressureLevel.map(Double.init) })
                        metric("Swap",
                               "\(Formatters.num(store.latestSample?.swapUsedGb)) GB",
                               series: store.samples.map(\.swapUsedGb))
                        metric("CPU",
                               "\(Formatters.num(store.latestSample?.cpuPct, digits: 0))%",
                               series: store.samples.map(\.cpuPct))
                    }
                    .padding(8)
                }

                GroupBox("Inference") {
                    if store.latestSample?.runtime != nil {
                        VStack(spacing: 12) {
                            metric("Generation", "\(Formatters.num(store.latestSample?.runtime?.decodeTokS)) tok/s",
                                   series: store.samples.map { $0.runtime?.decodeTokS })
                            metric("Prompt", "\(Formatters.num(store.latestSample?.runtime?.prefillTokS, digits: 0)) tok/s",
                                   series: store.samples.map { $0.runtime?.prefillTokS })
                            metric("TTFT", "\(Formatters.num(store.latestSample?.runtime?.ttftS, digits: 2)) s",
                                   series: store.samples.map { $0.runtime?.ttftS })
                            metric("Acceptance", Formatters.pct(store.latestSample?.runtime?.acceptanceRate),
                                   series: store.samples.map { $0.runtime?.acceptanceRate })
                        }
                        .padding(8)
                    } else {
                        Text("Runtime metrics appear in Fast Mode (dflash-mlx /metrics). Safe Mode does not publish them.")
                            .foregroundStyle(.secondary)
                            .padding(8)
                    }
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
    }

    private func metric(_ title: String, _ value: String, series: [Double?]) -> some View {
        HStack {
            Text(title)
            Spacer()
            sparkline(series)
                .frame(width: 120, height: 28)
            Text(value)
                .font(.body.monospacedDigit().weight(.medium))
                .frame(minWidth: 90, alignment: .trailing)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title), \(value)")
    }

    private func sparkline(_ series: [Double?]) -> some View {
        let pts = series.enumerated().compactMap { i, v -> (Int, Double)? in
            guard let v else { return nil }
            return (i, v)
        }
        return Chart(pts, id: \.0) { item in
            LineMark(x: .value("t", item.0), y: .value("v", item.1))
                .foregroundStyle(Color.secondary)
                .interpolationMethod(.catmullRom)
        }
        .chartXAxis(.hidden)
        .chartYAxis(.hidden)
        .chartLegend(.hidden)
    }
}

struct LogsPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Logs").font(.largeTitle.weight(.semibold))
            HStack {
                Picker("Category", selection: $store.logCategory) {
                    Text("Runtime").tag("runtime")
                    Text("API").tag("api")
                    Text("Backend").tag("backend")
                    Text("Benchmark").tag("benchmark")
                }
                .frame(width: 160)
                TextField("Search", text: $store.logQuery)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 220)
                Toggle("Errors only", isOn: $store.logErrorsOnly)
                Toggle("Important only", isOn: $store.logImportantOnly)
                Button("Copy") {
                    store.copy((store.logs?.lines ?? []).joined(separator: "\n"))
                }
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(Array((store.logs?.lines ?? []).enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(color(line))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(8)
            }
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
            if let path = store.logs?.path {
                Text("\(path) · \(store.logs?.totalLines ?? 0) lines")
                    .font(.caption.monospaced())
                    .foregroundStyle(.tertiary)
            }
        }
        .task { await reload() }
        .onChange(of: store.logCategory) { _, _ in Task { await reload() } }
        .onChange(of: store.logQuery) { _, _ in Task { await reload() } }
        .onChange(of: store.logErrorsOnly) { _, _ in Task { await reload() } }
        .onChange(of: store.logImportantOnly) { _, _ in Task { await reload() } }
        .onReceive(Timer.publish(every: 4, on: .main, in: .common).autoconnect()) { _ in
            Task { await reload() }
        }
    }

    private func reload() async {
        await store.loadLogs(category: store.logCategory, query: store.logQuery, errorsOnly: store.logErrorsOnly, importantOnly: store.logImportantOnly)
    }

    private func color(_ line: String) -> Color {
        if line.range(of: "error|critical|traceback|exception|failed|crash", options: [.regularExpression, .caseInsensitive]) != nil {
            return Palette.err
        }
        if line.range(of: "warn", options: .caseInsensitive) != nil {
            return Palette.warn
        }
        return .primary
    }
}

struct SettingsPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Settings").font(.largeTitle.weight(.semibold))
                Text("Single source of truth: config/config.yaml. This app does not keep a second copy.")
                    .foregroundStyle(.secondary)

                GroupBox("General") {
                    VStack(spacing: 0) {
                        KVRow(title: "Model alias", subtitle: "What agents see as the model name") {
                            Text(store.alias).font(.body.monospaced())
                        }
                        Divider()
                        KVRow(title: "Launch Local AI at login", subtitle: "Menu bar app only — the 27B model still waits for Start") {
                            Toggle("Launch at login", isOn: $store.launchAtLoginPref)
                                .labelsHidden()
                                .onChange(of: store.launchAtLoginPref) { _, on in
                                    LoginItem.setEnabled(on)
                                }
                        }
                    }
                    .padding(8)
                }

                if let cfg = store.config {
                    GroupBox("Runtime") {
                        VStack(spacing: 0) {
                            KVRow(title: "Max context") {
                                Picker("Context", selection: Binding(
                                    get: { cfg.runtime.maxContext },
                                    set: { store.patchSettings(SettingsPatch(runtime: .init(maxContext: $0))) }
                                )) {
                                    ForEach([16384, 32768, 65536, 131072, 262144], id: \.self) { v in
                                        Text("\(v / 1024)K").tag(v)
                                    }
                                }
                                .labelsHidden()
                            }
                            Divider()
                            KVRow(title: "Default max tokens") {
                                Picker("Tokens", selection: Binding(
                                    get: { cfg.runtime.defaultMaxTokens },
                                    set: { store.patchSettings(SettingsPatch(runtime: .init(defaultMaxTokens: $0))) }
                                )) {
                                    ForEach([1024, 2048, 4096, 8192, 16384], id: \.self) { v in
                                        Text("\(v)").tag(v)
                                    }
                                }
                                .labelsHidden()
                            }
                            Divider()
                            KVRow(title: "Thinking mode", subtitle: "Qwen3.8 reasoning traces") {
                                Toggle("Thinking", isOn: Binding(
                                    get: { cfg.runtime.enableThinking ?? true },
                                    set: { store.patchSettings(SettingsPatch(runtime: .init(enableThinking: $0))) }
                                ))
                                .labelsHidden()
                            }
                            Divider()
                            KVRow(title: "Auto-load model on login", subtitle: "Off by default — pins ~29 GB") {
                                Toggle("Auto-load", isOn: Binding(
                                    get: { cfg.runtime.autoLoad },
                                    set: { store.patchSettings(SettingsPatch(runtime: .init(autoLoad: $0))) }
                                ))
                                .labelsHidden()
                            }
                        }
                        .padding(8)
                    }
                }

                GroupBox("Control plane services") {
                    VStack(spacing: 0) {
                        serviceRow("backend")
                        Divider()
                        serviceRow("gateway")
                    }
                    .padding(8)
                    Text("These keep the dashboard and API gateway alive after login. The model loads only when you press Start.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 8)
                }

                GroupBox("Advanced") {
                    VStack(spacing: 0) {
                        KVRow(title: "Show advanced options") {
                            Button(store.settingsAdvanced ? "Hide" : "Show") { store.settingsAdvanced.toggle() }
                        }
                        if store.settingsAdvanced, let cfg = store.config {
                            Divider()
                            KVRow(title: "API port") { Text("\(cfg.api.port)").font(.body.monospaced()) }
                            Divider()
                            KVRow(title: "Dashboard port") { Text("\(cfg.dashboard.port)").font(.body.monospaced()) }
                            Divider()
                            KVRow(title: "Bind address", subtitle: "LAN exposure is not offered in this version") {
                                Text("127.0.0.1").font(.body.monospaced())
                            }
                            Divider()
                            KVRow(title: "Log level") {
                                Picker("Level", selection: Binding(
                                    get: { cfg.logging.level },
                                    set: { store.patchSettings(SettingsPatch(logging: .init(level: $0))) }
                                )) {
                                    ForEach(["DEBUG", "INFO", "WARNING", "ERROR"], id: \.self) { Text($0).tag($0) }
                                }
                                .labelsHidden()
                            }
                            Divider()
                            KVRow(title: "Swap warning") {
                                Picker("Swap", selection: Binding(
                                    get: { cfg.memory.swapWarnGb },
                                    set: { store.patchSettings(SettingsPatch(memory: .init(swapWarnGb: $0))) }
                                )) {
                                    ForEach([2.0, 4.0, 8.0, 16.0], id: \.self) { Text("\(Int($0)) GB").tag($0) }
                                }
                                .labelsHidden()
                            }
                        }
                    }
                    .padding(8)
                }

                GroupBox("About") {
                    VStack(spacing: 0) {
                        KVRow(title: "Local AI") { Text("v0.2.0") }
                        Divider()
                        KVRow(title: "Project") { Text(ProjectRoot.resolve().path).font(.caption.monospaced()) }
                    }
                    .padding(8)
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
        .task {
            await store.refreshConfig()
            await store.loadServices()
            store.launchAtLoginPref = LoginItem.isEnabled
        }
    }

    private func serviceRow(_ name: String) -> some View {
        let s = store.services[name]
        return KVRow(title: "launchd · \(name)", subtitle: s?.label) {
            HStack {
                if s?.loaded == true {
                    Text("running").foregroundStyle(Palette.ok)
                } else if s?.installed == true {
                    Text("installed").foregroundStyle(Palette.warn)
                } else {
                    Text("not installed").foregroundStyle(.secondary)
                }
                if s?.installed == true {
                    Button("Remove") { store.uninstallService(name) }
                } else {
                    Button("Install") { store.installService(name) }
                }
            }
            .controlSize(.small)
            .disabled(store.isActing)
        }
    }
}
