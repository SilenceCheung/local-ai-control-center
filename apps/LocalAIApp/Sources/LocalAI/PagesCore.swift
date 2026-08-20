import SwiftUI

struct OverviewPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                if let adv = store.runtime.advisory { AdvisoryBanner(advisory: adv) }
                if let mem = store.memoryAdvisory { AdvisoryBanner(advisory: mem) }
                runtimeCard
                dflashCard
                apiCard
                agentsCard
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
        .task { await store.loadOverviewExtras() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Overview").font(.largeTitle.weight(.semibold))
            Text("Apple Silicon local model runtime · speculative decoding · agent gateway")
                .foregroundStyle(.secondary)
        }
    }

    private var runtimeCard: some View {
        GroupBox("Runtime") {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    StatusDot(life: store.runtime.status, healthy: store.runtime.httpHealthy)
                    VStack(alignment: .leading) {
                        Text("Local AI Runtime  \(store.runtime.status.rawValue)")
                            .font(.headline)
                        Text(store.runtime.targetModel ?? "no target model")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                if store.running {
                    HStack {
                        StatCell(label: "Memory", value: Formatters.num(store.latestSample?.memUsedGb), unit: "GB")
                        StatCell(label: "Generation", value: Formatters.num(store.latestSample?.runtime?.decodeTokS), unit: "tok/s")
                        StatCell(label: "TTFT", value: Formatters.num(store.latestSample?.runtime?.ttftS, digits: 2), unit: "s")
                        StatCell(label: "Context",
                                 value: store.config.map { "\($0.runtime.maxContext / 1024)K" } ?? "—")
                    }
                }
            }
            .padding(8)
        }
    }

    private var dflashCard: some View {
        GroupBox("Speculative Decoding") {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    StatusDot(life: store.running && store.runtime.mode == .fast ? .running : .stopped)
                    Text("DFlash")
                        .font(.headline)
                    Text(store.runtime.mode == .fast ? (store.running ? "ON" : "enabled, stopped") : "OFF — Safe Mode")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                Text(store.runtime.draftModel ?? store.config?.runtime.draftModel ?? "no draft")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if store.running && store.runtime.mode == .fast {
                    HStack {
                        StatCell(label: "Acceptance", value: Formatters.pct(store.latestSample?.runtime?.acceptanceRate))
                        StatCell(label: "Prefill", value: Formatters.num(store.latestSample?.runtime?.prefillTokS, digits: 0), unit: "tok/s")
                        StatCell(label: "RSS", value: Formatters.num(store.latestSample?.runtime?.rssGb), unit: "GB")
                    }
                }
            }
            .padding(8)
        }
    }

    private var apiCard: some View {
        GroupBox("API Server") {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    StatusDot(life: store.runtime.httpHealthy ? .running : .stopped)
                    Text("OpenAI-compatible API")
                    Spacer()
                    Text(store.runtime.httpHealthy ? "Healthy" : "Unavailable")
                        .foregroundStyle(.secondary)
                }
                copyRow("Base URL", store.apiBaseURL)
                copyRow("Model", store.alias)
            }
            .padding(8)
        }
    }

    private var agentsCard: some View {
        GroupBox("Agents") {
            VStack(spacing: 0) {
                ForEach(store.agents.filter { $0.notSupportedNatively != true }) { agent in
                    KVRow(title: agent.name) {
                        Text(agent.status == "connected" ? "Connected" : agent.status == "seen_before" ? "Seen earlier" : "Unknown")
                            .foregroundStyle(agent.status == "connected" ? Palette.ok : .secondary)
                    }
                    if agent.id != store.agents.last(where: { $0.notSupportedNatively != true })?.id {
                        Divider()
                    }
                }
            }
            .padding(8)
        }
    }

    private func copyRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
            Text(value).font(.body.monospaced()).textSelection(.enabled).lineLimit(1)
            Spacer()
            Button("Copy") { store.copy(value) }
                .controlSize(.small)
        }
    }
}

struct ModelsPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Models").font(.largeTitle.weight(.semibold))
                Spacer()
                Button("Rescan") { store.scanModels() }
                    .disabled(store.isActing)
            }
            Text("Local inventory from LM Studio and Hugging Face caches — used in place, never moved.")
                .foregroundStyle(.secondary)
            Table(store.models) {
                TableColumn("Model") { m in
                    VStack(alignment: .leading) {
                        Text(m.displayName)
                        Text(m.id).font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                }
                TableColumn("Role") { m in
                    Text(m.role == "none" ? "—" : m.role.capitalized)
                }.width(70)
                TableColumn("Quant") { m in Text(m.quantization ?? "—") }.width(110)
                TableColumn("Size") { m in Text(Formatters.bytes(m.sizeBytes)) }.width(70)
                TableColumn("Compat") { m in Text(m.compatibility ?? "—") }.width(90)
                TableColumn("Actions") { m in
                    HStack {
                        if m.isDraftCandidate {
                            Button("Set Draft") { store.setRole(modelId: m.id, role: "draft") }
                                .disabled(m.role == "draft" || store.isActing)
                        } else if m.compatibility == "mlx" {
                            Button("Set Target") { store.setRole(modelId: m.id, role: "target") }
                                .disabled(m.role == "target" || store.isActing)
                        }
                        Button("Folder") { store.openModelFolder(m.id) }
                        Button("Copy ID") { store.copy(m.id) }
                    }
                    .controlSize(.small)
                }.width(240)
            }
        }
        .task { await store.loadModels() }
    }
}

struct RuntimePage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Runtime").font(.largeTitle.weight(.semibold))
                Text("Mode switches reload the model. Agents keep the same endpoint and alias.")
                    .foregroundStyle(.secondary)
                GroupBox("Mode") {
                    VStack(spacing: 0) {
                        KVRow(title: "Safe Mode", subtitle: "Target only · mlx-lm · maximum stability") {
                            Button("Use Safe") { store.setMode(.safe) }
                                .disabled(store.runtime.mode == .safe || store.isActing)
                        }
                        Divider()
                        KVRow(title: "Fast Mode", subtitle: "Target + DFlash draft · speculative decoding") {
                            Button("Use Fast") { store.setMode(.fast) }
                                .disabled(store.runtime.mode == .fast || store.isActing)
                        }
                    }
                    .padding(8)
                }
                GroupBox("Process") {
                    VStack(spacing: 0) {
                        KVRow(title: "Status") { Text(store.runtime.status.rawValue) }
                        Divider()
                        KVRow(title: "Engine") { Text(store.runtime.engine ?? "—") }
                        Divider()
                        KVRow(title: "PID") { Text(store.runtime.pid.map(String.init) ?? "—").font(.body.monospaced()) }
                        Divider()
                        KVRow(title: "Uptime") { Text(Formatters.uptime(store.runtime.uptimeS)) }
                        Divider()
                        KVRow(title: "HTTP health") { Text(store.runtime.httpHealthy ? "healthy" : "unreachable") }
                        Divider()
                        KVRow(title: "Fallbacks") { Text("\(store.runtime.fallbackCount ?? 0)") }
                    }
                    .padding(8)
                }
                GroupBox("Recent Events") {
                    Table(store.events) {
                        TableColumn("Time") { Text(Formatters.time($0.createdAt)) }.width(160)
                        TableColumn("Event") { Text($0.kind) }.width(90)
                        TableColumn("Detail") { Text($0.detail ?? "").font(.caption.monospaced()) }
                    }
                    .frame(minHeight: 220)
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
        .task { await store.loadEvents() }
    }
}
