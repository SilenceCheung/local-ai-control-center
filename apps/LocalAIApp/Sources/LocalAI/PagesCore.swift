import SwiftUI

struct OverviewPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            Text(L10n.t("overview.kicker")).foregroundStyle(.secondary)
            if let notice = store.statusNotice { AdvisoryBanner(advisory: notice) }
            if let adv = store.runtime.advisory { AdvisoryBanner(advisory: adv) }
            if let mem = store.memoryAdvisory { AdvisoryBanner(advisory: mem) }

            Section(L10n.t("overview.runtime")) {
                StatusLine(life: store.runtime.status, healthy: store.runtime.httpHealthy)
                LabeledContent(L10n.t("overview.model")) {
                    Text(store.runtime.targetModel ?? L10n.t("overview.no_target"))
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                if store.running {
                    HStack {
                        StatCell(label: L10n.t("overview.metric.memory"), value: Formatters.num(store.latestSample?.memUsedGb), unit: L10n.t("popover.unit.gb"))
                        StatCell(label: L10n.t("overview.metric.generation"), value: Formatters.num(store.latestSample?.runtime?.decodeTokS), unit: L10n.t("popover.unit.toks"))
                        StatCell(label: L10n.t("overview.metric.ttft"), value: Formatters.num(store.latestSample?.runtime?.ttftS, digits: 2), unit: "s")
                        StatCell(label: L10n.t("overview.metric.context"),
                                 value: store.config.map { "\($0.runtime.maxContext / 1024)K" } ?? L10n.t("emdash"))
                    }
                }
            }

            Section(L10n.t("overview.dflash")) {
                StatusLine(
                    life: store.running && store.runtime.mode == .fast ? .running : .stopped,
                    extra: dflashCaption
                )
                Text(store.runtime.draftModel ?? store.config?.runtime.draftModel ?? L10n.t("overview.no_draft"))
                    .font(TypeScale.caption)
                    .foregroundStyle(.secondary)
                if store.running && store.runtime.mode == .fast {
                    HStack {
                        StatCell(label: L10n.t("overview.metric.acceptance"), value: Formatters.pct(store.latestSample?.runtime?.acceptanceRate))
                        StatCell(label: L10n.t("overview.metric.prefill"), value: Formatters.num(store.latestSample?.runtime?.prefillTokS, digits: 0), unit: L10n.t("popover.unit.toks"))
                        StatCell(label: L10n.t("overview.metric.rss"), value: Formatters.num(store.latestSample?.runtime?.rssGb), unit: L10n.t("popover.unit.gb"))
                    }
                }
            }

            Section(L10n.t("overview.api")) {
                StatusLine(life: store.runtime.httpHealthy ? .running : .stopped)
                CopyableRow(label: L10n.t("overview.base_url"), value: store.apiBaseURL, copy: store.copy)
                EditableAliasRow(label: L10n.t("overview.model"))
            }

            Section(L10n.t("overview.agents")) {
                let visible = store.agents.filter { $0.notSupportedNatively != true }
                if visible.isEmpty {
                    Text(L10n.t("agents.empty.body")).foregroundStyle(.secondary)
                } else {
                    ForEach(visible) { agent in
                        LabeledContent(agent.name) {
                            Text(agentStatus(agent))
                                .foregroundStyle(agent.status == "connected" ? Palette.ok : .secondary)
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(maxWidth: 900)
        .frame(maxWidth: .infinity)
        .task { await store.loadOverviewExtras() }
    }

    private var dflashCaption: String {
        if store.runtime.mode == .fast {
            return store.running ? L10n.t("overview.dflash.on") : L10n.t("overview.dflash.enabled_stopped")
        }
        return L10n.t("overview.dflash.off")
    }

    private func agentStatus(_ a: AgentInfo) -> String {
        switch a.status {
        case "connected": return L10n.t("agent.connected")
        case "seen_before": return L10n.t("agent.seen")
        default: return L10n.t("agent.unknown")
        }
    }
}

struct ModelsPage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            HStack(spacing: Space.md) {
                Picker("", selection: $store.modelsPane) {
                    Text(L10n.t("models.tab.installed")).tag("installed")
                    Text(L10n.t("models.tab.discover")).tag("discover")
                    Text(downloadsTabLabel).tag("downloads")
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 420)
                Spacer()
                Text(store.modelLibrary?.library ?? L10n.t("emdash"))
                    .font(TypeScale.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Button(L10n.t("models.library.change")) { store.chooseLibraryFolder() }
                    .disabled(store.isActing)
            }
            if store.modelsPane != "downloads", store.pullJob?.busy == true, let job = store.pullJob?.job {
                HStack {
                    ProgressView().controlSize(.small)
                    Text(job.current == "resume"
                         ? "\(L10n.t("models.hub.resuming")) \(job.repoId ?? "")"
                         : "\(L10n.t("models.hub.pulling")) \(job.repoId ?? "")")
                        .font(TypeScale.caption)
                    Spacer()
                    Button(L10n.t("models.dl.pause")) { store.pausePull(repoId: job.repoId) }
                    Button(L10n.t("models.tab.downloads")) { store.modelsPane = "downloads" }
                }
            }
            if store.modelsPane == "discover" {
                DiscoverPane()
            } else if store.modelsPane == "downloads" {
                DownloadsPane()
            } else {
                InstalledModelsPane()
            }
        }
        .padding(Space.lg)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .modifier(LibraryDropCatcher())
        .task {
            await store.loadModels()
            if store.modelsPane == "discover" {
                await store.searchHub()
            }
        }
        .onChange(of: store.modelsPane) { _, pane in
            if pane == "discover" { store.scheduleHubSearch() }
            if pane == "downloads" { Task { await store.pollPullJob() } }
        }
    }

    private var downloadsTabLabel: String {
        let n = store.downloadBadgeCount
        if n == 0 { return L10n.t("models.tab.downloads") }
        return "\(L10n.t("models.tab.downloads")) (\(n))"
    }
}

private struct DownloadsPane: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            Text(L10n.t("models.dl.kicker"))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if store.downloadItems.isEmpty {
                EmptyState(
                    title: L10n.t("models.dl.empty.title"),
                    bodyText: L10n.t("models.dl.empty.body"),
                    actionTitle: L10n.t("models.tab.discover"),
                    action: { store.modelsPane = "discover" }
                )
                Spacer()
            } else {
                List(store.downloadItems) { item in
                    DownloadRow(item: item)
                }
                .listStyle(.inset)
            }
        }
    }
}

private struct DownloadRow: View {
    @EnvironmentObject var store: AppStore
    var item: DownloadItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(item.repoId).font(TypeScale.mono)
                Spacer()
                Text(statusLabel).font(TypeScale.caption).foregroundStyle(statusColor)
            }
            if let err = item.error, item.status == "error" {
                Text(err).font(TypeScale.caption).foregroundStyle(Palette.err)
            }
            if let total = item.bytesTotal, total > 0 {
                ProgressView(value: min(1, Double(item.bytesDone ?? 0) / Double(total)))
                Text("\(Formatters.bytes(item.bytesDone)) / \(Formatters.bytes(total))")
                    .font(TypeScale.caption)
                    .foregroundStyle(.secondary)
            } else if let detail = item.detail, !detail.isEmpty {
                Text(detail).font(TypeScale.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: Space.sm) {
                if item.status == "running" || item.status == "pausing" {
                    Button(L10n.t("models.dl.pause")) { store.pausePull(repoId: item.repoId) }
                }
                if (item.status == "paused" || item.status == "queued" || item.status == "error")
                    && item.hasCompleteModel != true {
                    Button(L10n.t("models.hub.resume")) { store.resumePull(repoId: item.repoId) }
                        .disabled(store.isActing)
                }
                if item.status != "running" && item.status != "pausing" {
                    Button(L10n.t("models.dl.dismiss")) { store.dismissDownload(repoId: item.repoId) }
                }
                if item.status == "done" && item.completionSource == "disk" {
                    Button(L10n.t("models.dl.view_installed")) {
                        store.modelsPane = "installed"
                        Task { await store.loadModels() }
                    }
                }
                if item.hasPartialFiles == true && item.hasCompleteModel != true {
                    Button(L10n.t("models.dl.clear_partials"), role: .destructive) {
                        store.clearDownloadPartials(repoId: item.repoId)
                    }
                    .help(L10n.t("models.dl.clear_partials.help"))
                }
            }
            .controlSize(.small)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(item.repoId), \(statusLabel)")
    }

    private var statusLabel: String {
        switch item.status {
        case "running", "pausing": return L10n.t("models.dl.status.running")
        case "queued": return L10n.t("models.dl.status.queued")
        case "paused": return L10n.t("models.dl.status.paused")
        case "error": return L10n.t("models.dl.status.error")
        case "done":
            return item.completionSource == "disk"
                ? L10n.t("models.dl.status.installed_external")
                : L10n.t("models.dl.status.done")
        default: return item.status ?? L10n.t("emdash")
        }
    }

    private var statusColor: Color {
        switch item.status {
        case "running", "pausing": return Palette.ok
        case "queued": return .secondary
        case "paused": return Palette.warn
        case "error": return Palette.err
        case "done": return Palette.ok
        default: return .secondary
        }
    }
}

private struct InstalledModelsPane: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            Text(L10n.t("models.kicker"))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if store.filteredModels.isEmpty {
                EmptyState(
                    title: L10n.t("models.empty.title"),
                    bodyText: L10n.t("models.empty.body"),
                    actionTitle: L10n.t("models.empty.action"),
                    action: { store.scanModels() }
                )
                Spacer()
            } else {
                GeometryReader { geometry in
                    if geometry.size.width >= 760 {
                        HStack(alignment: .top, spacing: 0) {
                            modelsTable
                            Divider()
                            ModelInspectorPane()
                        }
                    } else {
                        VStack(spacing: 0) {
                            modelsTable
                            if store.selectedModel != nil {
                                Divider()
                                DisclosureGroup(
                                    L10n.t("models.inspector.title"),
                                    isExpanded: $store.narrowModelDetailsExpanded
                                ) {
                                    ModelInspectorPane(compact: true)
                                }
                                .padding(.horizontal, Space.md)
                                .padding(.vertical, Space.sm)
                            }
                        }
                    }
                }
            }
        }
    }

    private var modelsTable: some View {
        Table(store.filteredModels, selection: $store.selectedModelId, sortOrder: $store.modelSortOrder) {
            TableColumn(L10n.t("models.col.model"), value: \.displayName) { m in
                VStack(alignment: .leading) {
                    Text(m.displayName)
                    Text(m.id).font(TypeScale.caption.monospaced()).foregroundStyle(.secondary)
                }
                .contextMenu { modelMenu(m, store: store) }
                .accessibilityLabel("\(m.displayName), \(roleLabel(m.role))")
                .accessibilityAction(named: L10n.t("models.folder")) { store.openModelFolder(m.id) }
                .accessibilityAction(named: L10n.t("models.copy_id")) { store.copy(m.id) }
                .accessibilityAction(named: m.isDraftCandidate ? L10n.t("models.set_draft") : L10n.t("models.set_target")) {
                    store.selectedModelId = m.id
                    store.applyPrimaryRole()
                }
            }
            TableColumn(L10n.t("models.col.role"), value: \.role) { m in
                Text(roleLabel(m.role))
            }.width(80)
            TableColumn(L10n.t("models.col.quant"), value: \.quantValue) { m in
                Text(m.quantization ?? L10n.t("emdash"))
            }.width(110)
            TableColumn(L10n.t("models.col.size"), value: \.sizeValue) { m in
                Text(Formatters.bytes(m.sizeBytes))
            }.width(70)
            TableColumn(L10n.t("models.col.compat"), value: \.compatValue) { m in
                Text(m.compatibility ?? L10n.t("emdash"))
            }.width(90)
        }
        .frame(minWidth: 280, minHeight: 0, maxHeight: .infinity)
        .onKeyPress(.return) {
            store.applyPrimaryRole()
            return .handled
        }
    }
}

private struct ModelInspectorPane: View {
    @EnvironmentObject var store: AppStore
    var compact = false

    var body: some View {
        Group {
            if let m = store.selectedModel {
                ScrollView {
                    VStack(alignment: .leading, spacing: Space.md) {
                        Text(m.displayName).font(TypeScale.section)
                        Text(m.id)
                            .font(TypeScale.caption.monospaced())
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                        LabeledContent(L10n.t("models.col.role"), value: roleLabel(m.role))
                        LabeledContent(L10n.t("models.col.quant"), value: m.quantization ?? L10n.t("emdash"))
                        LabeledContent(L10n.t("models.col.size"), value: Formatters.bytes(m.sizeBytes))
                        LabeledContent(L10n.t("models.col.compat"), value: m.compatibility ?? L10n.t("emdash"))
                        if m.status == "downloading" {
                            Button(L10n.t("models.hub.resume")) { store.resumePull(repoId: m.id) }
                                .disabled(store.isActing)
                            Button(L10n.t("models.dl.pause")) { store.pausePull(repoId: m.id) }
                                .disabled(store.pullJob?.activeId != m.id)
                        }
                        if let path = m.localPath, !path.isEmpty {
                            LabeledContent(L10n.t("models.inspector.path")) {
                                Text(path)
                                    .font(TypeScale.caption.monospaced())
                                    .textSelection(.enabled)
                                    .lineLimit(3)
                                    .truncationMode(.middle)
                            }
                        }
                        VStack(alignment: .leading, spacing: Space.sm) {
                            modelMenu(m, store: store)
                        }
                        .controlSize(.regular)
                        Text(L10n.t("models.inspector.return"))
                            .font(TypeScale.caption)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(Space.md)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Text(L10n.t("models.inspector.empty"))
                    .foregroundStyle(.secondary)
                    .padding(Space.md)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
        .frame(
            minWidth: compact ? 0 : 220,
            idealWidth: compact ? nil : 260,
            maxWidth: compact ? .infinity : 340,
            maxHeight: compact ? 240 : .infinity
        )
        .accessibilityElement(children: .contain)
        .accessibilityLabel(L10n.t("models.inspector.title"))
    }
}

private func roleLabel(_ role: String) -> String {
    switch role {
    case "target": return L10n.t("role.target")
    case "draft": return L10n.t("role.draft")
    default: return L10n.t("role.none")
    }
}

@ViewBuilder
private func modelMenu(_ m: ModelInfo, store: AppStore) -> some View {
    if m.isDraftCandidate {
        Button(L10n.t("models.set_draft")) { store.setRole(modelId: m.id, role: "draft") }
            .disabled(m.role == "draft" || store.isActing)
    } else if m.compatibility == "mlx" {
        Button(L10n.t("models.set_target")) { store.setRole(modelId: m.id, role: "target") }
            .disabled(m.role == "target" || store.isActing)
    }
    Button(L10n.t("models.folder")) { store.openModelFolder(m.id) }
    Button(L10n.t("models.copy_id")) { store.copy(m.id) }
    Button(L10n.t("models.dl.delete"), role: .destructive) { store.confirmDeleteInstalledModel(m.id) }
        .disabled(store.isActing)
}

private struct DiscoverPane: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: Space.sm) {
                if store.hubSearching {
                    ProgressView().controlSize(.small)
                } else if store.hubHits.isEmpty {
                    Text(store.hubQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                         ? L10n.t("models.hub.empty")
                         : L10n.t("models.hub.none"))
                        .foregroundStyle(.secondary)
                        .font(TypeScale.caption)
                } else if store.hubQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Text(L10n.t("models.hub.recommended"))
                        .foregroundStyle(.secondary)
                        .font(TypeScale.caption)
                }
                List(store.hubHits, selection: $store.hubSelectedId) { hit in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(hit.id).font(TypeScale.body)
                        HStack(spacing: 6) {
                            if hit.local == true && hit.partial != true { Text(L10n.t("models.hub.local")).foregroundStyle(Palette.ok) }
                            if hit.partial == true { Text(L10n.t("models.hub.resume")).foregroundStyle(Palette.warn) }
                            if hit.kind == "target" { Text(L10n.t("models.hub.kind.target")) }
                            if hit.kind == "draft" { Text(L10n.t("models.hub.kind.draft")) }
                            if hit.runnable != true { Text(L10n.t("models.hub.not_runnable")).foregroundStyle(Palette.warn) }
                        }
                        .font(TypeScale.caption)
                        .foregroundStyle(.secondary)
                    }
                    .tag(Optional(hit.id))
                }
                .onChange(of: store.hubSelectedId) { _, id in
                    if let id { Task { await store.loadHubCard(id) } }
                }
            }
            .frame(minWidth: 260, idealWidth: 320, maxWidth: 360)

            Divider()
            HubDetailPane()
                .frame(minWidth: 360, maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private struct HubDetailPane: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Group {
            if let card = store.hubCard {
                Form {
                    Section(card.id) {
                        if card.local == true && card.partial != true { Text(L10n.t("models.hub.local")).foregroundStyle(Palette.ok) }
                        if card.partial == true { Text(L10n.t("models.hub.resume")).foregroundStyle(Palette.warn) }
                        if card.kind == "target" { Text(L10n.t("models.hub.kind.target")) }
                        if card.kind == "draft" { Text(L10n.t("models.hub.kind.draft")) }
                        if card.runnable != true {
                            Text(L10n.t("models.hub.not_runnable")).foregroundStyle(Palette.warn)
                            if let reason = reasonText(card.reason) {
                                Text(reason).font(TypeScale.caption).foregroundStyle(.secondary)
                            }
                        } else if card.pipelineTag == "image-text-to-text" {
                            Text(L10n.t("models.hub.text_only"))
                                .font(TypeScale.caption)
                                .foregroundStyle(.secondary)
                        }
                        LabeledContent(L10n.t("models.hub.params"), value: card.paramSize ?? L10n.t("emdash"))
                        LabeledContent(L10n.t("models.hub.license"), value: card.license ?? L10n.t("emdash"))
                        LabeledContent(L10n.t("models.library")) {
                            Text("\(store.modelLibrary?.library ?? "")/\(card.id)")
                                .font(TypeScale.caption.monospaced())
                                .textSelection(.enabled)
                        }
                        HStack {
                            Button(card.partial == true ? L10n.t("models.hub.resume") : L10n.t("models.hub.pull")) {
                                store.pullHub(repoId: card.id)
                            }
                            .disabled((card.local == true && card.partial != true) || store.isActing)
                            if card.kind == "target" {
                                Button(L10n.t("models.set_target")) { store.pullHub(repoId: card.id, assignRole: "target") }
                                    .disabled(card.runnable != true || card.local == true || store.isActing)
                            }
                            if card.kind == "draft" {
                                Button(L10n.t("models.set_draft")) { store.pullHub(repoId: card.id, assignRole: "draft") }
                                    .disabled(card.runnable != true || card.local == true || store.isActing)
                            }
                            if let urlStr = card.url, let url = URL(string: urlStr) {
                                Link(L10n.t("models.hub.hf"), destination: url)
                            }
                        }
                    }
                    if let readme = card.readme, !readme.isEmpty {
                        Section(L10n.t("models.hub.readme")) {
                            Text(readme).font(TypeScale.caption).textSelection(.enabled)
                        }
                    }
                    if let files = card.files, !files.isEmpty {
                        Section(L10n.t("models.hub.files")) {
                            ForEach(files.prefix(24), id: \.name) { f in
                                LabeledContent(f.name, value: Formatters.bytes(f.sizeBytes))
                            }
                        }
                    }
                }
                .formStyle(.grouped)
            } else {
                Text(L10n.t("models.hub.pick"))
                    .foregroundStyle(.secondary)
                    .padding(Space.lg)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
    }

    private func reasonText(_ reason: String?) -> String? {
        switch reason {
        case "gguf": return L10n.t("models.hub.reason.gguf")
        case "vision": return L10n.t("models.hub.reason.vision")
        case "not_mlx": return L10n.t("models.hub.reason.not_mlx")
        default: return nil
        }
    }
}

struct RuntimePage: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        Form {
            Text(L10n.t("runtime.kicker")).foregroundStyle(.secondary)
            Section(L10n.t("runtime.mode")) {
                KVRow(title: L10n.t("runtime.safe.title"), subtitle: L10n.t("runtime.safe.sub")) {
                    Button(L10n.t("runtime.use_safe")) { store.setMode(.safe) }
                        .disabled(store.runtime.mode == .safe || store.isActing)
                }
                KVRow(title: L10n.t("runtime.fast.title"), subtitle: L10n.t("runtime.fast.sub")) {
                    Button(L10n.t("runtime.use_fast")) { store.setMode(.fast) }
                        .disabled(store.runtime.mode == .fast || store.isActing)
                }
            }
            Section(L10n.t("runtime.process")) {
                LabeledContent(L10n.t("runtime.status")) {
                    StatusLine(life: store.runtime.status, healthy: store.runtime.httpHealthy)
                }
                LabeledContent(L10n.t("runtime.engine")) { Text(store.runtime.engine ?? L10n.t("emdash")) }
                LabeledContent(L10n.t("runtime.pid")) {
                    Text(store.runtime.pid.map(String.init) ?? L10n.t("emdash")).font(TypeScale.mono)
                }
                LabeledContent(L10n.t("runtime.uptime")) { Text(Formatters.uptime(store.runtime.uptimeS)) }
                LabeledContent(L10n.t("runtime.http")) {
                    Text(store.runtime.httpHealthy ? L10n.t("runtime.http.healthy") : L10n.t("runtime.http.unreachable"))
                }
                LabeledContent(L10n.t("runtime.fallbacks")) { Text("\(store.runtime.fallbackCount ?? 0)") }
            }
            Section(L10n.t("runtime.events")) {
                if store.events.isEmpty {
                    Text(L10n.t("runtime.empty.events")).foregroundStyle(.secondary)
                } else {
                    Table(store.events) {
                        TableColumn(L10n.t("runtime.col.time")) { Text(Formatters.time($0.createdAt)) }.width(160)
                        TableColumn(L10n.t("runtime.col.event")) { Text($0.kind) }.width(90)
                        TableColumn(L10n.t("runtime.col.detail")) { Text($0.detail ?? "").font(TypeScale.caption.monospaced()) }
                    }
                    .frame(minHeight: 160, maxHeight: 240)
                }
            }
        }
        .formStyle(.grouped)
        .task { await store.loadEvents() }
    }
}
