import SwiftUI

struct DFlashPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("DFlash").font(.largeTitle.weight(.semibold))
                Text("Block-diffusion speculative decoding. Draft block size is fixed at training time.")
                    .foregroundStyle(.secondary)
                if let adv = store.dflash?.advisory { AdvisoryBanner(advisory: adv) }

                GroupBox("Status") {
                    VStack(alignment: .leading, spacing: 12) {
                        KVRow(title: "DFlash") {
                            Toggle("Enabled", isOn: Binding(
                                get: { store.runtime.mode == .fast },
                                set: { store.updateDFlash(DFlashPatch(enabled: $0)) }
                            ))
                            .toggleStyle(.switch)
                            .labelsHidden()
                            .disabled(store.isActing)
                            .accessibilityLabel("DFlash enabled")
                        }
                        if store.runtime.mode == .fast && store.running {
                            HStack {
                                StatCell(label: "Acceptance", value: Formatters.pct(store.latestSample?.runtime?.acceptanceRate))
                                StatCell(label: "Generation", value: Formatters.num(store.latestSample?.runtime?.decodeTokS), unit: "tok/s")
                                StatCell(label: "Fallbacks", value: "\(store.dflash?.fallbackCount ?? 0)")
                            }
                        }
                    }
                    .padding(8)
                }

                GroupBox("Configuration") {
                    VStack(spacing: 0) {
                        KVRow(title: "Draft model") {
                            Picker("Draft", selection: Binding(
                                get: { store.dflash?.draftModel ?? "" },
                                set: { store.updateDFlash(DFlashPatch(draftModel: $0)) }
                            )) {
                                ForEach(store.models.filter(\.isDraftCandidate)) { m in
                                    Text(m.id).tag(m.id)
                                }
                            }
                            .labelsHidden()
                            .frame(maxWidth: 360)
                            .disabled(store.isActing)
                        }
                        Divider()
                        KVRow(title: "Draft block size", subtitle: "Fixed by this checkpoint — not a runtime knob") {
                            Text("\(store.dflash?.blockSizeTrained ?? 16) tokens")
                                .font(.body.monospaced())
                        }
                        Divider()
                        KVRow(title: "Verify mode", subtitle: "adaptive shortens low-acceptance blocks") {
                            Picker("Verify", selection: Binding(
                                get: { store.dflash?.config.verifyMode ?? "adaptive" },
                                set: { store.updateDFlash(DFlashPatch(verifyMode: $0)) }
                            )) {
                                Text("adaptive (recommended)").tag("adaptive")
                                Text("dflash (fixed block)").tag("dflash")
                                Text("ddtree (experimental)").tag("ddtree")
                            }
                            .labelsHidden()
                            .disabled(store.isActing)
                        }
                        Divider()
                        KVRow(title: "Verify length cap", subtitle: "0 = engine default") {
                            Picker("Cap", selection: Binding(
                                get: { store.dflash?.config.verifyLenCap ?? 0 },
                                set: { store.updateDFlash(DFlashPatch(verifyLenCap: $0)) }
                            )) {
                                Text("default").tag(0)
                                Text("4").tag(4)
                                Text("8").tag(8)
                                Text("16").tag(16)
                            }
                            .labelsHidden()
                            .disabled(store.isActing)
                        }
                    }
                    .padding(8)
                }

                GroupBox("Recent Requests") {
                    let recents = Array((store.dflash?.metrics.data?.recentRequests ?? []).suffix(8).reversed())
                    if recents.isEmpty {
                        Text("No requests recorded yet in this runtime session.")
                            .foregroundStyle(.secondary)
                            .padding(8)
                    } else {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text("Tokens").frame(width: 70, alignment: .trailing)
                                Text("tok/s").frame(width: 70, alignment: .trailing)
                                Text("Acceptance").frame(width: 90, alignment: .trailing)
                                Text("Tok/cycle").frame(width: 80, alignment: .trailing)
                            }
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.tertiary)
                            ForEach(Array(recents.enumerated()), id: \.offset) { _, r in
                                HStack {
                                    Text("\(r.generatedTokens ?? r.tokens ?? 0)").frame(width: 70, alignment: .trailing)
                                    Text(Formatters.num(r.decodeTokS)).frame(width: 70, alignment: .trailing)
                                    Text(Formatters.pct(r.acceptanceRate)).frame(width: 90, alignment: .trailing)
                                    Text(Formatters.num(r.tokensPerCycle)).frame(width: 80, alignment: .trailing)
                                }
                                .font(.body.monospacedDigit())
                            }
                        }
                        .padding(8)
                    }
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
        .task {
            await store.loadModels()
            await store.loadDFlash()
        }
    }
}

struct APIPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("API").font(.largeTitle.weight(.semibold))
                Text("Stable across runtime restarts and mode switches.")
                    .foregroundStyle(.secondary)
                GroupBox("Connection") {
                    VStack(alignment: .leading, spacing: 8) {
                        row("Base URL", store.apiBaseURL)
                        row("API Key", store.apiKey)
                        row("Model", store.alias)
                    }
                    .padding(8)
                }
                GroupBox("Server Status") {
                    let s = store.gateway?.stats
                    HStack {
                        StatCell(label: "Requests", value: s?.requestsTotal.map(String.init) ?? "—")
                        StatCell(label: "Active", value: s?.requestsActive.map(String.init) ?? "—")
                        StatCell(label: "Tokens", value: s?.tokensGenerated.map { $0.formatted() } ?? "—")
                        StatCell(label: "Errors", value: s?.errorsTotal.map(String.init) ?? "—")
                    }
                    .padding(8)
                    Text("Last request: \(Formatters.time(s?.lastRequestAt))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 8)
                }
                GroupBox("Quick Test") {
                    Text("""
                    curl \(store.apiBaseURL)/chat/completions \\
                      -H "Content-Type: application/json" \\
                      -d '{"model": "\(store.alias)", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100, "stream": true}'
                    """)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(8)
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
        }
        .task { await store.loadOverviewExtras() }
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).foregroundStyle(.secondary).frame(width: 80, alignment: .leading)
            Text(v).font(.body.monospaced()).textSelection(.enabled)
            Spacer()
            Button("Copy") { store.copy(v) }.controlSize(.small)
        }
    }
}

struct BenchmarkPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Benchmark").font(.largeTitle.weight(.semibold))
            Text("Measured live against the real runtime — temperature 0, fixed prompts.")
                .foregroundStyle(.secondary)
            GroupBox("Run") {
                VStack(alignment: .leading, spacing: 10) {
                    Picker("Prompt", selection: $store.benchPromptKey) {
                        ForEach(store.benchPrompts.keys.sorted(), id: \.self) { key in
                            if let p = store.benchPrompts[key] {
                                Text("\(p.label) · \(p.maxTokens) tok").tag(key)
                            }
                        }
                    }
                    .frame(maxWidth: 320)
                    HStack {
                        Button("Quick Benchmark") { store.startBench("/api/benchmark/quick", promptKey: store.benchPromptKey) }
                        Button("DFlash A/B") { store.startBench("/api/benchmark/ab", promptKey: store.benchPromptKey) }
                        Button("Auto Tune") { store.startBench("/api/benchmark/autotune") }
                        Button("Tool Calling") { store.startBench("/api/benchmark/tool-calling") }
                    }
                    .disabled(store.isActing || store.benchJob?.busy == true)
                    .controlSize(.regular)
                }
                .padding(8)
            }
            if let job = store.benchJob?.job {
                GroupBox("Current Job") {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(job.kind).font(.headline)
                            Text(job.status).foregroundStyle(.secondary)
                            if store.benchJob?.busy == true { ProgressView().controlSize(.small) }
                        }
                        if let err = job.error { Text(err).foregroundStyle(Palette.err) }
                        ForEach(job.steps ?? [], id: \.step) { step in
                            Text("• \(step.step)\(step.detail.map { " — \($0)" } ?? "")")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(8)
                }
            }
            GroupBox("History") {
                Table(store.benchHistory) {
                    TableColumn("Time") { Text(Formatters.time($0.createdAt)) }.width(150)
                    TableColumn("Kind") { Text($0.kind) }.width(90)
                    TableColumn("Prompt") { Text($0.label ?? $0.promptKey ?? "—") }
                    TableColumn("tok/s") { r in
                        let n = r.results["dflash"]?.object?["tok_s"]?.double ?? r.results["tok_s"]?.double
                        Text(Formatters.num(n))
                    }.width(70)
                    TableColumn("Speedup") { r in
                        Text(r.results["speedup"]?.double.map { String(format: "%.2f×", $0) } ?? "—")
                    }.width(70)
                }
                .frame(minHeight: 240)
            }
        }
        .task { await store.loadBenchmark() }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            if store.benchJob?.busy == true {
                Task { await store.pollBenchJob() }
            }
        }
    }
}
