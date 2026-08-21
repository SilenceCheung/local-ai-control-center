import SwiftUI

struct DFlashPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            Text(L10n.t("dflash.kicker")).foregroundStyle(.secondary)
            if let notice = store.statusNotice, notice.kind != "restart_required" {
                AdvisoryBanner(advisory: notice)
            }
            if let adv = store.dflash?.advisory { AdvisoryBanner(advisory: adv) }

            Section(L10n.t("dflash.recipe.section")) {
                Picker(L10n.t("dflash.recipe.picker"), selection: Binding(
                    get: { store.dflash?.recipeId ?? store.recipes?.active ?? "heretic" },
                    set: { store.activateRecipe($0) }
                )) {
                    Text(L10n.t("dflash.recipe.heretic")).tag("heretic")
                    Text(L10n.t("dflash.recipe.official")).tag("official_dflash2")
                }
                .pickerStyle(.segmented)
                .disabled(store.isActing)

                if let sync = store.dflash?.configuration {
                    HStack(spacing: Space.sm) {
                        configurationBadge(sync)
                        Spacer()
                        if sync.restartRequired {
                            Button(L10n.t("dflash.apply_restart")) {
                                store.restartRuntime()
                            }
                            .keyboardShortcut(.return, modifiers: [.command])
                            .disabled(store.isActing)
                        }
                    }
                    if sync.restartRequired {
                        Text(pendingSummary(sync.changes))
                            .font(TypeScale.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Section(L10n.t("dflash.running.section")) {
                if let running = store.dflash?.configuration?.running {
                    LabeledContent(L10n.t("dflash.running.mode")) {
                        Text(running.mode == .fast
                             ? L10n.t("dflash.running.fast")
                             : L10n.t("dflash.running.safe"))
                    }
                    LabeledContent(L10n.t("dflash.running.recipe")) {
                        Text(recipeName(running.recipeId))
                    }
                    LabeledContent(L10n.t("dflash.running.target")) {
                        Text(running.targetModel ?? L10n.t("emdash"))
                            .font(.body.monospaced())
                            .textSelection(.enabled)
                    }
                    LabeledContent(L10n.t("dflash.running.draft")) {
                        Text(running.draftModel ?? L10n.t("emdash"))
                            .font(.body.monospaced())
                            .textSelection(.enabled)
                    }
                    LabeledContent(L10n.t("dflash.running.quant")) {
                        Text(running.draftQuant ?? L10n.t("emdash"))
                            .font(.body.monospaced())
                    }
                    LabeledContent(L10n.t("dflash.running.block")) {
                        Text(blockDescription(running))
                    }
                    LabeledContent(L10n.t("dflash.running.cache")) {
                        Text(cacheDescription(running))
                    }
                } else {
                    Text(L10n.t("dflash.running.empty"))
                        .foregroundStyle(.secondary)
                }
                if let missing = store.dflash?.missing, !missing.isEmpty {
                    Text(L10n.t("dflash.missing") + " " + missing.map(\.id).joined(separator: " · "))
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.warn)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(L10n.t("dflash.missing.download")) {
                        store.openDiscover(prefill: missing[0].id)
                    }
                }
                if store.runtime.mode == .fast && store.running {
                    HStack {
                        StatCell(label: L10n.t("dflash.metric.acceptance"), value: Formatters.pct(store.latestSample?.runtime?.acceptanceRate))
                        StatCell(label: L10n.t("dflash.metric.generation"), value: Formatters.num(store.latestSample?.runtime?.decodeTokS), unit: L10n.t("popover.unit.toks"))
                        StatCell(label: L10n.t("dflash.metric.fallbacks"), value: "\(store.dflash?.fallbackCount ?? 0)")
                    }
                }
            }

            Section(store.dflash?.configuration?.restartRequired == true
                    ? L10n.t("dflash.config.next")
                    : L10n.t("dflash.config")) {
                Toggle(L10n.t("dflash.enabled"), isOn: Binding(
                    get: { store.dflash?.mode == .fast },
                    set: { store.updateDFlash(DFlashPatch(enabled: $0)) }
                ))
                .disabled(store.isActing)
                Picker(L10n.t("dflash.draft"), selection: Binding(
                    get: { store.dflash?.draftModel ?? "" },
                    set: { store.updateDFlash(DFlashPatch(draftModel: $0)) }
                )) {
                    ForEach(store.models.filter(\.isDraftCandidate)) { m in
                        Text(m.id).tag(m.id)
                    }
                }
                .disabled(store.isActing)
                Picker(L10n.t("dflash.quant"), selection: Binding(
                    get: { store.dflash?.config.draftQuant ?? "default" },
                    set: { store.updateDFlash(DFlashPatch(draftQuant: $0)) }
                )) {
                    Text(L10n.t("dflash.quant.default")).tag("default")
                    Text("w4:gs64").tag("w4:gs64")
                }
                .disabled(store.isActing)
                Text(L10n.t("dflash.quant.sub"))
                    .font(TypeScale.caption)
                    .foregroundStyle(.secondary)
                LabeledContent(L10n.t("dflash.block"), value: String(format: L10n.t("dflash.block.value"), store.dflash?.blockSizeTrained ?? 16))
                Text(L10n.t("dflash.block.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                Picker(L10n.t("dflash.verify"), selection: Binding(
                    get: { store.dflash?.config.verifyMode ?? "adaptive" },
                    set: { store.updateDFlash(DFlashPatch(verifyMode: $0)) }
                )) {
                    Text(L10n.t("dflash.verify.adaptive")).tag("adaptive")
                    Text(L10n.t("dflash.verify.dflash")).tag("dflash")
                    Text(L10n.t("dflash.verify.ddtree")).tag("ddtree")
                }
                .disabled(store.isActing)
                Text(L10n.t("dflash.verify.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                Picker(L10n.t("dflash.cap"), selection: Binding(
                    get: { store.dflash?.config.verifyLenCap ?? 0 },
                    set: { store.updateDFlash(DFlashPatch(verifyLenCap: $0)) }
                )) {
                    Text(L10n.t("dflash.cap.default")).tag(0)
                    Text("4").tag(4)
                    Text("8").tag(8)
                    Text("16").tag(16)
                }
                .disabled(store.isActing)
                Text(L10n.t("dflash.cap.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                if store.dflash?.recipeId == "official_dflash2" {
                    if store.dflash?.engine?.knobsLive?["runtime_block_size"] == true {
                        Picker(L10n.t("dflash.block.runtime"), selection: Binding(
                            get: { store.dflash?.config.runtimeBlockSize ?? 0 },
                            set: { store.updateDFlash(DFlashPatch(runtimeBlockSize: $0)) }
                        )) {
                            Text(L10n.t("dflash.cap.default")).tag(0)
                            Text("4").tag(4)
                            Text("5").tag(5)
                            Text("8").tag(8)
                        }
                        .disabled(store.isActing)
                    } else {
                        LabeledContent(L10n.t("dflash.block.runtime"), value: L10n.t("dflash.unsupported"))
                    }
                    Text(L10n.t("dflash.block.runtime.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                    if store.dflash?.engine?.knobsLive?["draft_bits"] == true {
                        Picker(L10n.t("dflash.bits"), selection: Binding(
                            get: { store.dflash?.config.draftBits ?? 0 },
                            set: { store.updateDFlash(DFlashPatch(draftBits: $0)) }
                        )) {
                            Text(L10n.t("dflash.cap.default")).tag(0)
                            Text("4").tag(4)
                        }
                        .disabled(store.isActing)
                    }
                    Picker(L10n.t("dflash.reasoning"), selection: Binding(
                        get: { store.dflash?.config.reasoning ?? "xhigh" },
                        set: { store.updateDFlash(DFlashPatch(reasoning: $0)) }
                    )) {
                        Text(L10n.t("dflash.reasoning.default")).tag("default")
                        Text("low").tag("low")
                        Text("medium").tag("medium")
                        Text("xhigh").tag("xhigh")
                    }
                    .disabled(store.isActing)
                    Text(L10n.t("dflash.reasoning.sub")).font(TypeScale.caption).foregroundStyle(.secondary)
                }
            }

            Section(L10n.t("dflash.recent")) {
                let recents = Array((store.dflash?.metrics.data?.recentRequests ?? []).suffix(8).reversed())
                if recents.isEmpty {
                    Text(L10n.t("dflash.empty.recent")).foregroundStyle(.secondary)
                } else {
                    VStack(alignment: .leading, spacing: Space.xs) {
                        HStack {
                            Text(L10n.t("dflash.col.tokens")).frame(width: 70, alignment: .trailing)
                            Text(L10n.t("dflash.col.toks")).frame(width: 70, alignment: .trailing)
                            Text(L10n.t("dflash.col.accept")).frame(width: 90, alignment: .trailing)
                            Text(L10n.t("dflash.col.cycle")).frame(width: 80, alignment: .trailing)
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
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel(recentRequestLabel(r))
                        }
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel(L10n.t("dflash.recent"))
                }
            }
        }
        .formStyle(.grouped)
        .task {
            await store.loadModels()
            await store.loadDFlash()
        }
    }

    @ViewBuilder
    private func configurationBadge(_ sync: RuntimeConfigurationStatus) -> some View {
        if sync.restartRequired {
            Label(L10n.t("dflash.sync.pending"), systemImage: "clock.arrow.circlepath")
                .font(TypeScale.caption.weight(.semibold))
                .foregroundStyle(Palette.warn)
        } else if sync.running == nil {
            Label(L10n.t("dflash.sync.next_start"), systemImage: "checkmark.circle")
                .font(TypeScale.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        } else {
            Label(L10n.t("dflash.sync.active"), systemImage: "checkmark.seal.fill")
                .font(TypeScale.caption.weight(.semibold))
                .foregroundStyle(Palette.ok)
        }
    }

    private func recipeName(_ id: String?) -> String {
        id == "official_dflash2" ? L10n.t("dflash.recipe.official") :
        id == "heretic" ? L10n.t("dflash.recipe.heretic") : L10n.t("dflash.recipe.unknown")
    }

    private func blockDescription(_ profile: EffectiveRuntimeProfile) -> String {
        if let size = profile.runtimeBlockSize {
            return String(format: L10n.t("dflash.running.block.override"), size)
        }
        return L10n.t("dflash.running.block.checkpoint")
    }

    private func cacheDescription(_ profile: EffectiveRuntimeProfile) -> String {
        guard profile.prefixCache == true else { return L10n.t("dflash.cache.off") }
        return profile.prefixCacheL2 == true ? L10n.t("dflash.cache.l1l2") : L10n.t("dflash.cache.l1")
    }

    private func pendingSummary(_ changes: [RuntimeConfigurationChange]) -> String {
        let labels = changes.prefix(5).map { changeLabel($0.field) }
        return String(format: L10n.t("dflash.sync.changes"), labels.joined(separator: "、"))
    }

    private func changeLabel(_ field: String) -> String {
        switch field {
        case "recipe_id": return L10n.t("dflash.running.recipe")
        case "target_model": return L10n.t("dflash.running.target")
        case "draft_model": return L10n.t("dflash.running.draft")
        case "draft_quant": return L10n.t("dflash.running.quant")
        case "verify_mode": return L10n.t("dflash.verify")
        case "mode": return L10n.t("runtime.mode")
        default: return field.replacingOccurrences(of: "_", with: " ")
        }
    }

    private func recentRequestLabel(_ request: DFlashState.RecentRequest) -> String {
        [
            "\(L10n.t("dflash.col.tokens")): \(request.generatedTokens ?? request.tokens ?? 0)",
            "\(L10n.t("dflash.col.toks")): \(Formatters.num(request.decodeTokS))",
            "\(L10n.t("dflash.col.accept")): \(Formatters.pct(request.acceptanceRate))",
            "\(L10n.t("dflash.col.cycle")): \(Formatters.num(request.tokensPerCycle))"
        ].joined(separator: ", ")
    }
}

struct APIPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            Text(L10n.t("api.kicker")).foregroundStyle(.secondary)
            Section(L10n.t("api.connection")) {
                CopyableRow(label: L10n.t("api.base"), value: store.apiBaseURL, copy: store.copy)
                CopyableRow(label: L10n.t("api.key"), value: store.apiKey, copy: store.copy)
                EditableAliasRow(label: L10n.t("api.model"))
            }
            Section(L10n.t("api.server")) {
                let s = store.gateway?.stats
                HStack {
                    StatCell(label: L10n.t("api.requests"), value: s?.requestsTotal.map(String.init) ?? L10n.t("emdash"))
                    StatCell(label: L10n.t("api.active"), value: s?.requestsActive.map(String.init) ?? L10n.t("emdash"))
                    StatCell(label: L10n.t("api.tokens"), value: s?.tokensGenerated.map { $0.formatted() } ?? L10n.t("emdash"))
                    StatCell(label: L10n.t("api.errors"), value: s?.errorsTotal.map(String.init) ?? L10n.t("emdash"))
                }
                Text(String(format: L10n.t("api.last"), Formatters.time(s?.lastRequestAt)))
                    .font(TypeScale.caption)
                    .foregroundStyle(.secondary)
                if let scheduler = s?.scheduler {
                    LabeledContent(L10n.t("api.queue")) {
                        Text("\(scheduler.waiting ?? 0) / \(scheduler.maxQueue ?? 0)")
                    }
                    LabeledContent(L10n.t("api.admission")) {
                        Text(String(
                            format: L10n.t("api.admission.value"),
                            scheduler.duplicatesTotal ?? 0,
                            scheduler.timeoutsTotal ?? 0,
                            scheduler.budgetLimitedTotal ?? 0
                        ))
                        .font(TypeScale.caption.monospacedDigit())
                    }
                }
            }
            if let requests = store.gateway?.stats?.inflightRequests, !requests.isEmpty {
                Section(L10n.t("api.inflight")) {
                    ForEach(requests) { request in
                        HStack(alignment: .center, spacing: Space.md) {
                            VStack(alignment: .leading, spacing: Space.xs) {
                                Text("\(request.agent ?? "unknown") · \(request.status ?? "queued")")
                                    .font(TypeScale.body.weight(.medium))
                                Text("\(request.profile ?? "production") · cache \(request.cacheStatus ?? "pending")")
                                    .font(TypeScale.caption)
                                    .foregroundStyle(.secondary)
                                Text(String(
                                    format: L10n.t("api.inflight.detail"),
                                    request.estimatedInputTokens ?? 0,
                                    request.toolCount ?? 0,
                                    request.effectiveMaxTokens ?? 0,
                                    (request.elapsedMs ?? 0) / 1000
                                ))
                                .font(TypeScale.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button(L10n.t("api.cancel"), role: .destructive) {
                                store.cancelGatewayRequest(request.requestId)
                            }
                            .disabled(store.isActing)
                        }
                    }
                }
            }
            Section(L10n.t("api.curl")) {
                CodeBlock(text: """
                curl \(store.apiBaseURL)/chat/completions \\
                  -H "Content-Type: application/json" \\
                  -d '{"model": "\(store.alias)", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100, "stream": true}'
                """)
            }
        }
        .formStyle(.grouped)
        .task { await store.loadOverviewExtras() }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in
            Task { await store.refreshGatewayStats() }
        }
    }
}

struct BenchmarkPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            Text(L10n.t("bench.kicker")).foregroundStyle(.secondary)
            HStack(spacing: Space.md) {
                Picker(L10n.t("bench.prompt"), selection: $store.benchPromptKey) {
                    ForEach(store.benchPrompts.keys.sorted(), id: \.self) { key in
                        if let p = store.benchPrompts[key] {
                            Text("\(p.label) · \(p.maxTokens) tok").tag(key)
                        }
                    }
                }
                .frame(maxWidth: 320)
                Button(L10n.t("bench.quick")) {
                    store.startBench("/api/benchmark/quick", promptKey: store.benchPromptKey)
                }
                .keyboardShortcut(.defaultAction)
                Menu(L10n.t("bench.more")) {
                    Button(L10n.t("bench.ab")) { store.startBench("/api/benchmark/ab", promptKey: store.benchPromptKey) }
                    Button(L10n.t("bench.autotune")) { store.startBench("/api/benchmark/autotune") }
                    Button(L10n.t("bench.tool")) { store.startBench("/api/benchmark/tool-calling") }
                }
            }
            .disabled(store.isActing || store.benchJob?.busy == true)

            if let job = store.benchJob?.job {
                VStack(alignment: .leading, spacing: Space.xs) {
                    HStack {
                        Text(L10n.t("bench.job")).font(TypeScale.section)
                        Text(job.kind)
                        Text(job.status).foregroundStyle(.secondary)
                        if store.benchJob?.busy == true { ProgressView().controlSize(.small) }
                    }
                    if let err = job.error {
                        ErrorBanner(title: err, detail: nil)
                    }
                    ForEach(job.steps ?? [], id: \.step) { step in
                        Text("• \(step.step)\(step.detail.map { " — \($0)" } ?? "")")
                            .font(TypeScale.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            if store.benchHistory.isEmpty {
                EmptyState(
                    title: L10n.t("bench.empty.title"),
                    bodyText: L10n.t("bench.empty.body")
                )
                Spacer()
            } else {
                Table(store.benchHistory) {
                    TableColumn(L10n.t("bench.col.time")) { Text(Formatters.time($0.createdAt)) }.width(150)
                    TableColumn(L10n.t("bench.col.kind")) { Text($0.kind) }.width(90)
                    TableColumn(L10n.t("bench.col.prompt")) { Text($0.label ?? $0.promptKey ?? L10n.t("emdash")) }
                    TableColumn(L10n.t("bench.col.toks")) { r in
                        let n = r.results["dflash"]?.object?["tok_s"]?.double ?? r.results["tok_s"]?.double
                        Text(Formatters.num(n))
                    }.width(70)
                    TableColumn(L10n.t("bench.col.speedup")) { r in
                        Text(r.results["speedup"]?.double.map { String(format: "%.2f×", $0) } ?? L10n.t("emdash"))
                    }.width(70)
                }
                .frame(minHeight: 0, maxHeight: .infinity)
            }
        }
        .padding(Space.lg)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task { await store.loadBenchmark() }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            if store.benchJob?.busy == true {
                Task { await store.pollBenchJob() }
            }
        }
    }
}
