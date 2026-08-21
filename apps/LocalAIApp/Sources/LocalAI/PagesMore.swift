import Charts
import SwiftUI

struct AgentsPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            HStack {
                Text(L10n.t("agents.kicker"))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                Button(store.agentTesting ? L10n.t("agents.testing") : L10n.t("agents.test")) {
                    store.agentTesting = true
                    Task {
                        store.agentTest = await store.testAgents()
                        store.agentTesting = false
                        await store.loadOverviewExtras()
                    }
                }
                .disabled(store.agentTesting)
            }

            if let test = store.agentTest {
                Section(L10n.t("agents.test_box")) {
                    if test.ok {
                        Text(String(format: L10n.t("agents.test_ok"), Formatters.num(test.elapsedS, digits: 2)))
                            .foregroundStyle(Palette.ok)
                        if let reply = test.reply {
                            Text(reply).font(TypeScale.caption.monospaced())
                        }
                    } else {
                        ErrorBanner(title: L10n.t("agents.test_fail"), detail: test.error)
                    }
                }
            }

            if store.agents.isEmpty {
                EmptyState(
                    title: L10n.t("agents.empty.title"),
                    bodyText: L10n.t("agents.empty.body")
                )
            } else {
                ForEach(store.agents) { agent in
                    Section(agent.name) {
                        Text(statusLabel(agent))
                            .foregroundStyle(agent.status == "connected" ? Palette.ok : .secondary)
                        Text(agent.instructions)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        if agent.notSupportedNatively != true {
                            CopyableRow(label: L10n.t("api.base"), value: agent.config.baseUrl, copy: store.copy)
                            CopyableRow(label: L10n.t("api.key"), value: agent.config.apiKey, copy: store.copy)
                            CopyableRow(label: L10n.t("api.model"), value: agent.config.model, copy: store.copy)
                        }
                        if let snippet = agent.configSnippet {
                            LabeledContent(L10n.t("agents.snippet")) {
                                Button(L10n.t("common.copy")) { store.copy(snippet) }
                                    .controlSize(.small)
                            }
                            CodeBlock(text: snippet)
                                .contextMenu {
                                    Button(L10n.t("common.copy")) { store.copy(snippet) }
                                }
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .task { await store.loadOverviewExtras() }
    }

    private func statusLabel(_ a: AgentInfo) -> String {
        if a.notSupportedNatively == true { return L10n.t("agents.needs_gateway") }
        switch a.status {
        case "connected": return L10n.t("agent.connected")
        case "seen_before": return L10n.t("agent.seen")
        default: return L10n.t("agent.unknown")
        }
    }
}

struct MonitoringPage: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Form {
            Text(L10n.t("monitor.kicker")).foregroundStyle(.secondary)
            if let adv = store.memoryAdvisory { AdvisoryBanner(advisory: adv) }

            Section(L10n.t("monitor.system")) {
                metric(L10n.t("monitor.mem"), "\(Formatters.num(store.latestSample?.memUsedGb)) GB", series: store.samples.map(\.memUsedGb))
                metric(L10n.t("monitor.pressure"), Formatters.pressure(store.latestSample?.pressureLevel), series: store.samples.map { $0.pressureLevel.map(Double.init) })
                metric(L10n.t("monitor.swap"), "\(Formatters.num(store.latestSample?.swapUsedGb)) GB", series: store.samples.map(\.swapUsedGb))
                metric(L10n.t("monitor.cpu"), "\(Formatters.num(store.latestSample?.cpuPct, digits: 0))%", series: store.samples.map(\.cpuPct))
            }

            Section(L10n.t("monitor.inference")) {
                if store.latestSample?.runtime != nil {
                    metric(L10n.t("monitor.generation"), "\(Formatters.num(store.latestSample?.runtime?.decodeTokS)) tok/s", series: store.samples.map { $0.runtime?.decodeTokS })
                    metric(L10n.t("monitor.prompt"), "\(Formatters.num(store.latestSample?.runtime?.prefillTokS, digits: 0)) tok/s", series: store.samples.map { $0.runtime?.prefillTokS })
                    metric(L10n.t("monitor.ttft"), "\(Formatters.num(store.latestSample?.runtime?.ttftS, digits: 2)) s", series: store.samples.map { $0.runtime?.ttftS })
                    metric(L10n.t("monitor.acceptance"), Formatters.pct(store.latestSample?.runtime?.acceptanceRate), series: store.samples.map { $0.runtime?.acceptanceRate })
                } else {
                    Text(L10n.t("monitor.safe_note")).foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
    }

    private func metric(_ title: String, _ value: String, series: [Double?]) -> some View {
        HStack {
            Text(title)
            Spacer()
            if !reduceMotion {
                sparkline(series)
                    .frame(width: 120, height: 28)
                    .accessibilityHidden(true)
            }
            Text(value)
                .font(.body.monospacedDigit().weight(.medium))
                .frame(minWidth: 90, alignment: .trailing)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(title)
        .accessibilityValue(value + sparkSummary(series))
    }

    private func sparkSummary(_ series: [Double?]) -> String {
        let pts = series.compactMap { $0 }
        guard let first = pts.first, let last = pts.last, pts.count > 1 else { return "" }
        return ", \(L10n.t("monitor.spark")) \(Formatters.num(first)) → \(Formatters.num(last))"
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
        VStack(alignment: .leading, spacing: Space.md) {
            HStack(spacing: Space.md) {
                Picker("", selection: $store.logCategory) {
                    Text(L10n.t("logs.cat.runtime")).tag("runtime")
                    Text(L10n.t("logs.cat.api")).tag("api")
                    Text(L10n.t("logs.cat.backend")).tag("backend")
                    Text(L10n.t("logs.cat.benchmark")).tag("benchmark")
                }
                .labelsHidden()
                .frame(width: 140)
                .accessibilityLabel(L10n.t("logs.category"))
                Toggle(L10n.t("logs.errors"), isOn: $store.logErrorsOnly)
                Toggle(L10n.t("logs.important"), isOn: $store.logImportantOnly)
                Button(L10n.t("logs.copy")) {
                    store.copy((store.logs?.lines ?? []).joined(separator: "\n"))
                }
            }
            let lines = store.logs?.lines ?? []
            if lines.isEmpty {
                EmptyState(
                    title: L10n.t("logs.empty.title"),
                    bodyText: L10n.t("logs.empty.body")
                )
                Spacer()
            } else {
                List(Array(lines.enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(TypeScale.log)
                        .foregroundStyle(color(line))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(spokenLine(line))
                        .contextMenu {
                            Button(L10n.t("common.copy")) { store.copy(line) }
                        }
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(
                            top: 1,
                            leading: Space.sm,
                            bottom: 1,
                            trailing: Space.sm
                        ))
                    }
                .listStyle(.plain)
                .accessibilityLabel(L10n.t("nav.logs"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(CodeBackdrop())
            }
            if let path = store.logs?.path {
                Text(String(format: L10n.t("logs.meta"), path, store.logs?.totalLines ?? 0))
                    .font(TypeScale.caption.monospaced())
                    .foregroundStyle(.tertiary)
                    .lineLimit(2)
            }
        }
            .padding(Space.lg)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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

    private func spokenLine(_ line: String) -> String {
        if isError(line) { return "\(L10n.t("logs.a11y.error")). \(line)" }
        if isWarn(line) { return "\(L10n.t("logs.a11y.warn")). \(line)" }
        return line
    }

    private func isError(_ line: String) -> Bool {
        line.range(of: "error|critical|traceback|exception|failed|crash", options: [.regularExpression, .caseInsensitive]) != nil
    }

    private func isWarn(_ line: String) -> Bool {
        line.range(of: "warn", options: .caseInsensitive) != nil
    }

    private func color(_ line: String) -> Color {
        if isError(line) { return Palette.err }
        if isWarn(line) { return Palette.warn }
        return .primary
    }
}

struct SettingsRoot: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        TabView(selection: $store.settingsTab) {
            SettingsGeneral()
                .tabItem { Label(L10n.t("settings.general"), systemImage: "gearshape") }
                .tag("general")
            SettingsRuntimePane()
                .tabItem { Label(L10n.t("settings.runtime"), systemImage: "cpu") }
                .tag("runtime")
            SettingsServices()
                .tabItem { Label(L10n.t("settings.services"), systemImage: "bolt.horizontal") }
                .tag("services")
            SettingsAdvanced()
                .tabItem { Label(L10n.t("settings.advanced"), systemImage: "slider.horizontal.3") }
                .tag("advanced")
        }
        .frame(minWidth: 520, minHeight: 380)
        .task {
            await store.refreshConfig()
            await store.loadServices()
            await store.loadDFlash()
            store.launchAtLoginPref = LoginItem.isEnabled
        }
    }
}

struct SettingsGeneral: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollViewReader { proxy in
            Form {
            EditableAliasRow(label: L10n.t("settings.alias"))
                .id("settings.general.top")
            Text(L10n.t("settings.alias.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
            Toggle(L10n.t("settings.login"), isOn: $store.launchAtLoginPref)
                .onChange(of: store.launchAtLoginPref) { _, on in
                    LoginItem.setEnabled(on)
                }
            Text(L10n.t("settings.login.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
            Toggle(L10n.t("settings.keep_on_quit"), isOn: Binding(
                get: { store.keepServicesOnQuit },
                set: { store.setKeepServicesOnQuit($0) }
            ))
            Text(L10n.t("settings.keep_on_quit.sub"))
                .font(TypeScale.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Picker(L10n.t("settings.language"), selection: Binding(
                get: { store.appLanguage },
                set: { store.setLanguage($0) }
            )) {
                Text(L10n.t("settings.lang.system")).tag("system")
                Text(L10n.t("settings.lang.en")).tag("en")
                Text(L10n.t("settings.lang.zh")).tag("zh-Hans")
            }
            Text(L10n.t("settings.language.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
            LabeledContent(L10n.t("settings.project")) {
                HStack {
                    Text(ProjectRoot.resolve().path)
                        .font(TypeScale.caption.monospaced())
                        .lineLimit(2)
                        .truncationMode(.middle)
                    Button(L10n.t("settings.locate")) { store.locateProject() }
                }
            }
            if let err = store.locateError {
                Text(err).foregroundStyle(Palette.err).font(TypeScale.caption)
            }
            LabeledContent(L10n.t("models.library")) {
                VStack(alignment: .trailing, spacing: Space.xs) {
                    Text(store.modelLibrary?.library ?? store.config?.modelDirs?.first ?? L10n.t("emdash"))
                        .font(TypeScale.caption.monospaced())
                        .textSelection(.enabled)
                        .lineLimit(2)
                        .truncationMode(.middle)
                    HStack(spacing: Space.sm) {
                        Button(L10n.t("models.library.change")) { store.chooseLibraryFolder() }
                            .disabled(store.isActing)
                        Button(L10n.t("menu.reveal_library")) { store.revealLibrary() }
                    }
                    .controlSize(.small)
                }
            }
            Text(L10n.t("models.library.hint"))
                .font(TypeScale.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }
            .formStyle(.grouped)
            .padding(Space.md)
            .modifier(LibraryDropCatcher())
            .task { await store.loadLibrary() }
            .onAppear {
                DispatchQueue.main.async {
                    proxy.scrollTo("settings.general.top", anchor: .top)
                }
            }
        }
    }
}

struct SettingsRuntimePane: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            if let cfg = store.config {
                Picker(L10n.t("settings.context"), selection: Binding(
                    get: { cfg.runtime.maxContext },
                    set: { store.patchSettings(SettingsPatch(runtime: .init(maxContext: $0))) }
                )) {
                    ForEach([16384, 32768, 65536, 131072, 262144], id: \.self) { v in
                        Text("\(v / 1024)K").tag(v)
                    }
                }
                Picker(L10n.t("settings.tokens"), selection: Binding(
                    get: { cfg.runtime.defaultMaxTokens },
                    set: { store.patchSettings(SettingsPatch(runtime: .init(defaultMaxTokens: $0))) }
                )) {
                    ForEach([1024, 2048, 4096, 8192, 16384], id: \.self) { v in
                        Text("\(v)").tag(v)
                    }
                }
                Toggle(L10n.t("settings.thinking"), isOn: Binding(
                    get: { cfg.runtime.enableThinking ?? true },
                    set: { store.patchSettings(SettingsPatch(runtime: .init(enableThinking: $0))) }
                ))
                Text(L10n.t("settings.thinking.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                Toggle(L10n.t("settings.autoload"), isOn: Binding(
                    get: { cfg.runtime.autoLoad },
                    set: { store.patchSettings(SettingsPatch(runtime: .init(autoLoad: $0))) }
                ))
                Text(L10n.t("settings.autoload.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                Picker(L10n.t("settings.recipe"), selection: Binding(
                    get: { store.recipes?.active ?? store.config?.recipes?.active ?? "heretic" },
                    set: { store.activateRecipe($0) }
                )) {
                    Text(L10n.t("settings.recipe.heretic")).tag("heretic")
                    Text(L10n.t("settings.recipe.official")).tag("official_dflash2")
                }
                .disabled(store.isActing)
                Text((store.recipes?.active ?? "heretic") == "official_dflash2"
                     ? L10n.t("settings.recipe.official.sub")
                     : L10n.t("settings.recipe.heretic.sub"))
                    .font(TypeScale.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let missing = store.recipes?.missing, !missing.isEmpty {
                    Text(L10n.t("dflash.missing") + " " + missing.map(\.id).joined(separator: " · "))
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.warn)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(L10n.t("dflash.missing.download")) {
                        store.openDiscover(prefill: missing[0].id)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .padding(Space.md)
    }
}

struct SettingsServices: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            Text(L10n.t("settings.services.kicker"))
                .font(TypeScale.caption)
                .foregroundStyle(.secondary)
            serviceRow("backend", title: L10n.t("settings.svc.backend"))
            serviceRow("gateway", title: L10n.t("settings.svc.gateway"))
        }
        .formStyle(.grouped)
        .padding(Space.md)
    }

    private func serviceRow(_ name: String, title: String) -> some View {
        let s = store.services[name]
        return LabeledContent(title) {
            HStack {
                if s?.loaded == true {
                    Text(L10n.t("common.running")).foregroundStyle(Palette.ok)
                } else if s?.installed == true {
                    Text(L10n.t("common.installed")).foregroundStyle(Palette.warn)
                } else {
                    Text(L10n.t("common.not_installed")).foregroundStyle(.secondary)
                }
                if s?.installed == true {
                    Button(L10n.t("common.remove")) { store.uninstallService(name) }
                } else {
                    Button(L10n.t("common.install")) { store.installService(name) }
                }
            }
            .controlSize(.small)
            .disabled(store.isActing)
        }
    }
}

struct SettingsAdvanced: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            if let cfg = store.config {
                LabeledContent(L10n.t("settings.api_port")) {
                    Text("\(cfg.api.port)").font(TypeScale.mono)
                }
                LabeledContent(L10n.t("settings.dash_port")) {
                    Text("\(cfg.dashboard.port)").font(TypeScale.mono)
                }
                LabeledContent(L10n.t("settings.bind"), value: "127.0.0.1")
                Text(L10n.t("settings.bind.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                Picker(L10n.t("settings.log_level"), selection: Binding(
                    get: { cfg.logging.level },
                    set: { store.patchSettings(SettingsPatch(logging: .init(level: $0))) }
                )) {
                    ForEach(["DEBUG", "INFO", "WARNING", "ERROR"], id: \.self) { Text($0).tag($0) }
                }
                Picker(L10n.t("settings.swap"), selection: Binding(
                    get: { cfg.memory.swapWarnGb },
                    set: { store.patchSettings(SettingsPatch(memory: .init(swapWarnGb: $0))) }
                )) {
                    ForEach([2.0, 4.0, 8.0, 16.0], id: \.self) { Text("\(Int($0)) GB").tag($0) }
                }
            }
        }
        .formStyle(.grouped)
        .padding(Space.md)
    }
}
