import SwiftUI

enum ConsolePage: String, CaseIterable, Identifiable, Hashable {
    case overview, models, runtime, dflash, api, benchmark, agents, monitoring, logs
    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return L10n.t("nav.overview")
        case .models: return L10n.t("nav.models")
        case .runtime: return L10n.t("nav.runtime")
        case .dflash: return L10n.t("nav.dflash")
        case .api: return L10n.t("nav.api")
        case .benchmark: return L10n.t("nav.benchmark")
        case .agents: return L10n.t("nav.agents")
        case .monitoring: return L10n.t("nav.monitoring")
        case .logs: return L10n.t("nav.logs")
        }
    }

    var icon: String {
        switch self {
        case .overview: return "square.grid.2x2"
        case .models: return "shippingbox"
        case .runtime: return "cpu"
        case .dflash: return "bolt"
        case .api: return "network"
        case .benchmark: return "stopwatch"
        case .agents: return "link"
        case .monitoring: return "waveform.path.ecg"
        case .logs: return "doc.text"
        }
    }

    static let control: [ConsolePage] = [.overview, .runtime, .models]
    static let decode: [ConsolePage] = [.dflash]
    static let integrate: [ConsolePage] = [.api, .agents]
    static let observe: [ConsolePage] = [.monitoring, .logs, .benchmark]
}

struct ConsoleView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        NavigationStack {
            HStack(spacing: 0) {
                if !store.sidebarHidden {
                    consoleSidebar
                        .frame(width: 200)
                    Divider()
                }
                consoleDetail
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .navigationTitle(store.consolePage.title)
            .toolbar {
                ToolbarItemGroup(placement: .automatic) {
                    if store.consolePage == .models, store.modelsPane == "installed" {
                        TextField(L10n.t("models.search"), text: $store.modelFilter)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 180)
                            .accessibilityLabel(L10n.t("models.search"))
                        Button {
                            store.scanModels()
                        } label: {
                            Label(L10n.t("models.rescan"), systemImage: "arrow.clockwise")
                        }
                        .disabled(store.isActing)
                        .keyboardShortcut("r", modifiers: [.command])
                        .help(L10n.t("models.rescan"))
                    }
                    if store.consolePage == .models, store.modelsPane == "discover" {
                        TextField(L10n.t("models.hub.search"), text: $store.hubQuery)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 200)
                            .accessibilityLabel(L10n.t("models.hub.search"))
                            .onChange(of: store.hubQuery) { _, _ in store.scheduleHubSearch() }
                            .onSubmit { Task { await store.searchHub() } }
                        Picker(L10n.t("models.hub.sort"), selection: $store.hubSort) {
                            Text(L10n.t("models.hub.sort.downloads")).tag("downloads")
                            Text(L10n.t("models.hub.sort.updated")).tag("updated")
                            Text(L10n.t("models.hub.sort.relevance")).tag("relevance")
                        }
                        .labelsHidden()
                        .frame(width: 120)
                        .accessibilityLabel(L10n.t("models.hub.sort"))
                        .onChange(of: store.hubSort) { _, _ in
                            Task { await store.searchHub() }
                        }
                        .help(L10n.t("models.hub.sort"))
                    }
                    if store.consolePage == .logs {
                        TextField(L10n.t("logs.search"), text: $store.logQuery)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 180)
                            .accessibilityLabel(L10n.t("logs.search"))
                    }
                }
                ToolbarItemGroup(placement: .primaryAction) {
                    if store.running {
                        Button(action: store.stopRuntime) {
                            Label(L10n.t("menu.stop"), systemImage: "stop.fill")
                        }
                        .disabled(store.isActing)
                        .help(L10n.t("menu.stop"))
                        .accessibilityHint(L10n.t("menu.stop.hint"))
                        Button(action: store.restartRuntime) {
                            Label(L10n.t("menu.restart"), systemImage: "arrow.triangle.2.circlepath")
                        }
                        .disabled(store.isActing)
                        .help(L10n.t("menu.restart"))
                        .accessibilityHint(L10n.t("menu.restart.hint"))
                    } else {
                        Button(action: store.startRuntime) {
                            Label(L10n.t("menu.start"), systemImage: "play.fill")
                        }
                        .disabled(store.isActing || !store.backendReachable)
                        .keyboardShortcut(.defaultAction)
                        .help(L10n.t("menu.start"))
                        .accessibilityHint(L10n.t("menu.start.hint"))
                    }
                }
            }
        }
        .frame(minWidth: 0, maxWidth: .infinity, minHeight: 0, maxHeight: .infinity)
        .onAppear {
            store.consoleVisible = true
            Task { await store.tick(); await store.loadOverviewExtras() }
        }
        .onDisappear { store.consoleVisible = false }
        .alert(
            L10n.t("models.dl.delete.title"),
            isPresented: Binding(
                get: { store.pendingModelDeletion != nil },
                set: { if !$0 { store.pendingModelDeletion = nil } }
            )
        ) {
            Button(L10n.t("models.dl.delete"), role: .destructive) {
                store.deletePendingModel()
            }
            Button(L10n.t("common.cancel"), role: .cancel) {
                store.pendingModelDeletion = nil
            }
        } message: {
            Text(String(
                format: L10n.t("models.dl.delete.body"),
                store.pendingModelDeletion ?? ""
            ))
        }
    }

    private var consoleSidebar: some View {
        List(selection: $store.consolePage) {
            Section(L10n.t("nav.control")) {
                ForEach(ConsolePage.control) { item in
                    Label(item.title, systemImage: item.icon).tag(item)
                }
            }
            Section(L10n.t("nav.decode")) {
                ForEach(ConsolePage.decode) { item in
                    Label(item.title, systemImage: item.icon).tag(item)
                }
            }
            Section(L10n.t("nav.integrate")) {
                ForEach(ConsolePage.integrate) { item in
                    Label(item.title, systemImage: item.icon).tag(item)
                }
            }
            Section(L10n.t("nav.observe")) {
                ForEach(ConsolePage.observe) { item in
                    Label(item.title, systemImage: item.icon).tag(item)
                }
            }
        }
        .accessibilityLabel(L10n.t("a11y.sidebar"))
        .listStyle(.sidebar)
    }

    @ViewBuilder
    private var consoleDetail: some View {
        if !store.backendReachable {
            EmptyState(
                title: L10n.t("first_run.console.title"),
                bodyText: L10n.t("first_run.console.body"),
                actionTitle: L10n.t("empty.control.action"),
                action: { store.startControlPlane() }
            )
            .padding(Space.xl)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } else {
            switch store.consolePage {
            case .overview: OverviewPage()
            case .models: ModelsPage()
            case .runtime: RuntimePage()
            case .dflash: DFlashPage()
            case .api: APIPage()
            case .benchmark: BenchmarkPage()
            case .agents: AgentsPage()
            case .monitoring: MonitoringPage()
            case .logs: LogsPage()
            }
        }
    }
}
