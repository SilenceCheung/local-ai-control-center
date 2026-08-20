import SwiftUI

enum ConsolePage: String, CaseIterable, Identifiable, Hashable {
    case overview, models, runtime, dflash, api, benchmark, agents, monitoring, logs, settings
    var id: String { rawValue }
    var title: String {
        switch self {
        case .overview: return "Overview"
        case .models: return "Models"
        case .runtime: return "Runtime"
        case .dflash: return "DFlash"
        case .api: return "API"
        case .benchmark: return "Benchmark"
        case .agents: return "Agents"
        case .monitoring: return "Monitoring"
        case .logs: return "Logs"
        case .settings: return "Settings"
        }
    }
}

struct ConsoleView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        NavigationSplitView {
            List(ConsolePage.allCases, id: \.self, selection: $store.consolePage) { item in
                Label(item.title, systemImage: icon(item))
                    .tag(item)
            }
            .navigationSplitViewColumnWidth(min: 160, ideal: 180, max: 220)
            .listStyle(.sidebar)
        } detail: {
            Group {
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
                case .settings: SettingsPage()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(24)
        }
        .navigationTitle(store.consolePage.title)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if store.running {
                    Button("Restart", action: store.restartRuntime)
                        .disabled(store.isActing)
                    Button("Stop", role: .destructive, action: store.stopRuntime)
                        .disabled(store.isActing)
                } else {
                    Button("Start", action: store.startRuntime)
                        .disabled(store.isActing || !store.backendReachable)
                }
            }
        }
        .onAppear {
            store.consoleVisible = true
            Task { await store.tick(); await store.loadOverviewExtras() }
        }
        .onDisappear { store.consoleVisible = false }
    }

    private func icon(_ page: ConsolePage) -> String {
        switch page {
        case .overview: return "square.grid.2x2"
        case .models: return "shippingbox"
        case .runtime: return "cpu"
        case .dflash: return "bolt.fill"
        case .api: return "network"
        case .benchmark: return "stopwatch"
        case .agents: return "link"
        case .monitoring: return "waveform.path.ecg"
        case .logs: return "doc.text"
        case .settings: return "gear"
        }
    }
}
