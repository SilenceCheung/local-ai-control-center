import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

final class AppStore: ObservableObject {
    static let shared = AppStore()

    let client = APIClient()

    @Published var backendReachable = false
    @Published var runtime = RuntimeStatus.empty
    @Published var health: HealthResponse?
    @Published var config: AppConfig?
    @Published var latestSample: MetricSample?
    @Published var samples: [MetricSample] = []
    @Published var memoryAdvisory: Advisory?
    @Published var lastError: String?
    @Published var statusNotice: Advisory?
    @Published var busyAction: String?
    @Published var popoverVisible = false
    @Published var consoleVisible = false

    @Published var models: [ModelInfo] = []
    @Published var dflash: DFlashState?
    @Published var gateway: GatewayStatsEnvelope?
    @Published var agents: [AgentInfo] = []
    @Published var events: [EventRow] = []
    @Published var services: [String: ServiceStatus] = [:]
    @Published var benchJob: BenchJob?
    @Published var benchHistory: [BenchRun] = []
    @Published var benchPrompts: [String: BenchPrompt] = [:]
    @Published var consolePage: ConsolePage = .overview
    @Published var benchPromptKey = "coding_long"
    @Published var agentTest: ConnectionTest?
    @Published var agentTesting = false
    @Published var logCategory = "runtime"
    @Published var logQuery = ""
    @Published var logErrorsOnly = false
    @Published var logImportantOnly = true
    @Published var settingsAdvanced = false
    @Published var launchAtLoginPref = false
    @Published var logs: LogPayload?
    @Published var appLanguage: String = UserDefaults.standard.string(forKey: "appLanguage") ?? "system"
    @Published var sidebarHidden = false
    @Published var settingsTab = "general"
    @Published var modelFilter = ""
    @Published var locateError: String?
    @Published var showErrorDetail = false
    @Published var keepServicesOnQuit = ServiceSupervisor.keepServicesOnQuit
    @Published var recipes: RecipesStatus?
    @Published var modelsPane = "installed"
    @Published var hubQuery = ""
    @Published var hubSort = "downloads"
    @Published var hubHits: [HubHit] = []
    @Published var hubSearching = false
    @Published var hubSelectedId: String?
    @Published var hubCard: HubCard?
    @Published var pullJob: PullJobEnvelope?
    @Published var modelLibrary: ModelLibrary?
    @Published var selectedModelId: String?
    @Published var modelSortOrder: [KeyPathComparator<ModelInfo>] = [KeyPathComparator(\.displayName)]
    @Published var aliasDraft = ""
    @Published var aliasEditing = false
    @Published var libraryDropTargeted = false
    @Published var pendingModelDeletion: String?
    @Published var narrowModelDetailsExpanded = false

    var filteredModels: [ModelInfo] {
        let q = modelFilter.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let rows: [ModelInfo]
        if q.isEmpty {
            rows = models
        } else {
            rows = models.filter {
                $0.displayName.lowercased().contains(q) || $0.id.lowercased().contains(q)
            }
        }
        return rows.sorted(using: modelSortOrder)
    }

    var selectedModel: ModelInfo? {
        guard let id = selectedModelId else { return nil }
        return models.first { $0.id == id }
    }

    var swiftLocale: Locale { L10n.locale }

    private var pollTask: Task<Void, Never>?
    private var hubSearchTask: Task<Void, Never>?
    private var lastFallbackCount: Int = 0
    private var lastMemoryLevel: String?
    private var lastRuntimeStatus: RuntimeLife = .stopped

    var isActing: Bool { busyAction != nil }
    var running: Bool { runtime.status == .running }
    var starting: Bool { runtime.status == .starting || busyAction != nil }

    var dashboardURL: URL {
        let port = health?.ports.dashboard ?? 8787
        return URL(string: "http://127.0.0.1:\(port)")!
    }

    var apiBaseURL: String {
        if let cfg = config {
            return "http://\(cfg.api.host):\(cfg.api.port)/v1"
        }
        return "http://127.0.0.1:8080/v1"
    }

    var apiKey: String { config?.api.apiKey ?? "local" }
    var alias: String { config?.api.alias ?? "Qwen3.8-27B-Heretic-8bit" }
    var aliasAuto: Bool { config?.api.aliasAuto ?? true }
    var downloadItems: [DownloadItem] { pullJob?.items ?? [] }
    var downloadBadgeCount: Int {
        downloadItems.filter { item in
            ["running", "queued", "paused", "pausing", "error"].contains(item.status ?? "")
        }.count
    }

    func start() {
        pollTask?.cancel()
        pollTask = Task { @MainActor [weak self] in
            await self?.ensureControlPlane()
            while !Task.isCancelled {
                await self?.tick()
                let interval: UInt64 = (self?.popoverVisible == true || self?.consoleVisible == true) ? 3_000_000_000 : 5_000_000_000
                try? await Task.sleep(nanoseconds: interval)
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
    }

    @MainActor
    func tick() async {
        do {
            let h: HealthResponse = try await client.get("/api/health")
            let rt: RuntimeStatus = try await client.get("/api/runtime/status")
            let wasDown = !backendReachable
            backendReachable = true
            health = h
            runtime = rt
            if wasDown { lastError = nil }
            notifyTransitions(previous: lastRuntimeStatus, next: rt)
            lastRuntimeStatus = rt.status

            let n = (popoverVisible || consoleVisible) ? 90 : 2
            let snap: MonitorSnapshot = try await client.get("/api/monitor/snapshot?n=\(n)")
            latestSample = snap.samples.last
            memoryAdvisory = snap.memoryAdvisory
            if popoverVisible || consoleVisible {
                samples = snap.samples
            }
            if consolePage == .models || pullJob?.busy == true || !(pullJob?.items ?? []).isEmpty {
                await pollPullJob()
            }
            if let adv = snap.memoryAdvisory, adv.level != lastMemoryLevel {
                lastMemoryLevel = adv.level
                if adv.level == "critical" || adv.level == "warning" {
                    Notifier.post(id: "memory", title: adv.title, body: adv.detail)
                }
            } else if snap.memoryAdvisory == nil {
                lastMemoryLevel = nil
            }
        } catch {
            backendReachable = false
            if lastError == nil {
                lastError = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
    }

    private func notifyTransitions(previous: RuntimeLife, next: RuntimeStatus) {
        if let count = next.fallbackCount, count > lastFallbackCount {
            lastFallbackCount = count
            Notifier.post(
                id: "fallback-\(count)",
                title: L10n.t("notify.fallback.title"),
                body: next.advisory?.detail ?? L10n.t("notify.fallback.body")
            )
        } else if let count = next.fallbackCount {
            lastFallbackCount = count
        }
        if previous == .starting && next.status == .running {
            Notifier.post(id: "running", title: L10n.t("notify.ready.title"),
                          body: next.targetModel ?? alias)
        }
        if previous == .running && next.status == .error {
            Notifier.post(id: "error", title: L10n.t("notify.error.title"),
                          body: next.error ?? L10n.t("notify.error.body"))
        }
        if let adv = next.advisory, adv.kind == "low_acceptance" {
            Notifier.post(id: "acceptance", title: adv.title, body: adv.detail)
        }
    }

    func refreshConfig() async {
        do {
            config = try await client.get("/api/settings")
            adoptAliasDraftFromConfig()
            if let lang = config?.ui?.language, L10n.supported.contains(lang), lang != appLanguage {
                applyLanguagePreference(lang, persistRemote: false)
            }
        } catch { lastError = error.localizedDescription }
    }

    func loadOverviewExtras() async {
        async let c: AppConfig? = try? await client.get("/api/settings")
        async let a: [AgentInfo]? = try? await client.get("/api/agents")
        async let g: GatewayStatsEnvelope? = try? await client.get("/api/gateway/stats")
        config = await c
        adoptAliasDraftFromConfig()
        agents = await a ?? []
        gateway = await g
    }

    func cancelGatewayRequest(_ requestId: String) {
        perform("cancel-request") {
            struct OK: Decodable { var ok: Bool }
            let _: OK = try await self.client.post("/api/gateway/requests/\(requestId)/cancel")
            await self.loadOverviewExtras()
        }
    }

    func refreshGatewayStats() async {
        gateway = try? await client.get("/api/gateway/stats")
    }

    func loadModels() async {
        do { models = try await client.get("/api/models") }
        catch { lastError = error.localizedDescription }
        await loadLibrary()
    }

    func loadLibrary() async {
        modelLibrary = try? await client.get("/api/models/library")
    }

    func scheduleHubSearch() {
        hubSearchTask?.cancel()
        let delay: UInt64 = hubQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0 : 320_000_000
        hubSearchTask = Task { @MainActor in
            if delay > 0 { try? await Task.sleep(nanoseconds: delay) }
            guard !Task.isCancelled else { return }
            await searchHub()
        }
    }

    func searchHub() async {
        let q = hubQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        hubSearching = true
        defer { hubSearching = false }
        let encoded = q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q
        let path = "/api/models/search?q=\(encoded)&sort=\(hubSort)&format=mlx"
        do {
            let r: HubSearch = try await client.get(path)
            hubHits = r.results
        } catch {
            lastError = error.localizedDescription
            hubHits = []
        }
    }

    func selectHub(_ id: String) {
        hubSelectedId = id
        Task { await loadHubCard(id) }
    }

    func loadHubCard(_ id: String) async {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? id
        do { hubCard = try await client.get("/api/models/hub?id=\(encoded)") }
        catch { lastError = error.localizedDescription }
    }

    func pullHub(repoId: String, assignRole: String? = nil) {
        perform("pull") {
            let _: PullJobEnvelope = try await self.client.post(
                "/api/models/pull",
                body: PullBody(repoId: repoId, assignRole: assignRole)
            )
            await self.pollPullJob()
        }
    }

    func cancelPull() {
        pausePull(repoId: pullJob?.activeId ?? pullJob?.job?.repoId)
    }

    func pausePull(repoId: String?) {
        Task {
            struct OK: Decodable { var ok: Bool }
            _ = try? await client.post("/api/models/pull/pause", body: PullCtrlBody(repoId: repoId)) as OK
            await pollPullJob()
        }
    }

    func resumePull(repoId: String) {
        perform("pull") {
            struct OK: Decodable { var ok: Bool }
            _ = try await self.client.post("/api/models/pull/resume", body: PullCtrlBody(repoId: repoId)) as OK
            await self.pollPullJob()
        }
    }

    func dismissDownload(repoId: String) {
        Task {
            struct OK: Decodable { var ok: Bool }
            _ = try? await client.post("/api/models/pull/dismiss", body: PullCtrlBody(repoId: repoId)) as OK
            await pollPullJob()
        }
    }

    func clearDownloadPartials(repoId: String) {
        perform("delete") {
            struct OK: Decodable { var ok: Bool }
            let _: OK = try await self.client.post(
                "/api/models/pull/clear-partials",
                body: PullCtrlBody(repoId: repoId)
            )
            await self.pollPullJob()
            await self.loadModels()
        }
    }

    func confirmDeleteInstalledModel(_ repoId: String) {
        pendingModelDeletion = repoId
    }

    func deletePendingModel() {
        guard let repoId = pendingModelDeletion else { return }
        pendingModelDeletion = nil
        perform("delete") {
            struct R: Decodable { var ok: Bool }
            let _: R = try await self.client.post(
                "/api/models/delete",
                body: DeleteInstalledModelBody(modelId: repoId, confirmModelId: repoId)
            )
            await self.pollPullJob()
            await self.loadModels()
        }
    }

    func pollPullJob() async {
        let wasBusy = pullJob?.busy == true
        pullJob = try? await client.get("/api/models/pull")
        if wasBusy && pullJob?.busy == false {
            await loadModels()
        }
    }

    func chooseLibraryFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = L10n.t("models.library.prompt")
        panel.prompt = L10n.t("models.library.change")
        if let current = modelLibrary?.libraryResolved {
            panel.directoryURL = URL(fileURLWithPath: current)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        applyLibraryPath(url)
    }

    func applyLibraryPath(_ url: URL) {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue else { return }
        perform("library") {
            let _: LibraryResult = try await self.client.post(
                "/api/models/library",
                body: LibraryBody(path: url.path)
            )
            await self.loadLibrary()
            await self.loadModels()
            await self.refreshConfig()
        }
    }

    func acceptLibraryDrop(_ providers: [NSItemProvider]) -> Bool {
        let uti = UTType.fileURL.identifier
        guard let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(uti) }) else {
            return false
        }
        provider.loadItem(forTypeIdentifier: uti, options: nil) { item, _ in
            let url: URL? = {
                if let url = item as? URL { return url }
                if let data = item as? Data {
                    return URL(dataRepresentation: data, relativeTo: nil) ?? URL(string: String(data: data, encoding: .utf8) ?? "")
                }
                if let str = item as? String { return URL(string: str) ?? URL(fileURLWithPath: str) }
                return nil
            }()
            guard let url else { return }
            DispatchQueue.main.async { self.applyLibraryPath(url) }
        }
        return true
    }

    func revealLibrary() {
        let raw = modelLibrary?.libraryResolved ?? modelLibrary?.library
        guard let raw, !raw.isEmpty else { return }
        let path = (raw as NSString).expandingTildeInPath
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func openDiscover(prefill: String) {
        modelsPane = "discover"
        hubQuery = prefill
        consolePage = .models
        scheduleHubSearch()
        selectHub(prefill)
    }

    func loadDFlash() async {
        do { dflash = try await client.get("/api/dflash") }
        catch { lastError = error.localizedDescription }
        recipes = try? await client.get("/api/recipes")
    }

    func loadEvents() async {
        do { events = try await client.get("/api/events?limit=40") }
        catch { lastError = error.localizedDescription }
    }

    func loadServices() async {
        do { services = try await client.get("/api/service/status") }
        catch { lastError = error.localizedDescription }
    }

    func loadBenchmark() async {
        benchPrompts = (try? await client.get("/api/benchmark/prompts")) ?? [:]
        benchJob = try? await client.get("/api/benchmark/job")
        benchHistory = (try? await client.get("/api/benchmark/history?limit=30")) ?? []
    }

    func loadLogs(category: String, query: String, errorsOnly: Bool, importantOnly: Bool) async {
        var path = "/api/logs?category=\(category)&lines=400&errors_only=\(errorsOnly)&important_only=\(importantOnly)"
        if !query.isEmpty, let enc = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            path += "&query=\(enc)"
        }
        logs = try? await client.get(path)
    }

    // MARK: - Actions

    func perform(_ name: String, _ work: @escaping () async throws -> Void) {
        guard busyAction == nil else { return }
        busyAction = name
        lastError = nil
        Task { @MainActor in
            defer { busyAction = nil }
            do {
                try await work()
                await tick()
            } catch {
                lastError = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
    }

    func startRuntime() {
        Notifier.request()
        perform("start") {
            let _: RuntimeStatus = try await self.client.post("/api/runtime/start")
            self.statusNotice = nil
        }
    }

    func stopRuntime() {
        perform("stop") {
            let _: RuntimeStatus = try await self.client.post("/api/runtime/stop")
        }
    }

    func restartRuntime() {
        perform("restart") {
            let _: RuntimeStatus = try await self.client.post("/api/runtime/restart")
            self.statusNotice = nil
        }
    }

    func setMode(_ mode: RuntimeMode) {
        perform("mode") {
            let _: RuntimeStatus = try await self.client.post("/api/runtime/mode", body: ModeBody(mode: mode.rawValue))
            await self.refreshConfig()
        }
    }

    func startControlPlane() {
        Notifier.request()
        perform("control") {
            _ = ServiceSupervisor.startControlPlane()
            for _ in 0..<20 {
                try? await Task.sleep(nanoseconds: 500_000_000)
                if await self.client.reachable() { break }
            }
            await self.tick()
            await self.refreshConfig()
        }
    }

    /// Launch path: bring the control plane up without a notification permission prompt.
    func ensureControlPlane() async {
        ServiceSupervisor.neutralizeLoginOrphans()
        if await client.reachable() {
            await tick()
            return
        }
        _ = ServiceSupervisor.startControlPlane()
        for _ in 0..<24 {
            try? await Task.sleep(nanoseconds: 250_000_000)
            if await client.reachable() { break }
        }
        await tick()
        await refreshConfig()
    }

    func setKeepServicesOnQuit(_ on: Bool) {
        keepServicesOnQuit = on
        ServiceSupervisor.keepServicesOnQuit = on
        ServiceSupervisor.syncKeepFlag()
    }

    func copyAPIConfig() {
        let text = """
        Base URL: \(apiBaseURL)
        API Key: \(apiKey)
        Model: \(alias)
        """
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(text, forType: .string)
    }

    func copy(_ string: String) {
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(string, forType: .string)
    }

    func openDashboard() {
        NSWorkspace.shared.open(dashboardURL)
    }

    func setRole(modelId: String, role: String) {
        perform("role") {
            let _: RoleResult = try await self.client.post("/api/models/role", body: RoleBody(modelId: modelId, role: role))
            await self.loadModels()
            await self.refreshConfig()
        }
    }

    func applyPrimaryRole() {
        guard let m = selectedModel, !isActing else { return }
        if m.isDraftCandidate {
            if m.role != "draft" { setRole(modelId: m.id, role: "draft") }
        } else if m.compatibility == "mlx" {
            if m.role != "target" { setRole(modelId: m.id, role: "target") }
        }
    }

    func scanModels() {
        perform("scan") {
            struct Scan: Decodable { var ok: Bool; var found: Int }
            let _: Scan = try await self.client.post("/api/models/scan")
            await self.loadModels()
        }
    }

    func openModelFolder(_ id: String) {
        Task {
            struct OK: Decodable { var ok: Bool }
            _ = try? await client.post("/api/models/open-folder", body: ModelIdBody(modelId: id)) as OK
        }
    }

    func updateDFlash(_ patch: DFlashPatch) {
        perform("dflash") {
            struct R: Decodable { var ok: Bool; var restartRequired: Bool? }
            let result: R = try await self.client.put("/api/dflash", body: patch)
            await self.loadDFlash()
            if result.restartRequired == true {
                self.statusNotice = Advisory(
                    level: "info",
                    title: L10n.t("dflash.restart.title"),
                    detail: L10n.t("dflash.restart.body"),
                    kind: "restart_required",
                    at: Date().timeIntervalSince1970
                )
            } else if self.statusNotice?.kind == "restart_required" {
                self.statusNotice = nil
            }
        }
    }

    func activateRecipe(_ id: String) {
        perform("recipe") {
            let r: RecipeActivateResult = try await self.client.post(
                "/api/recipes/activate",
                body: RecipeActivateBody(id: id)
            )
            await self.refreshConfig()
            await self.loadDFlash()
            if r.restartRequired == true {
                self.statusNotice = Advisory(
                    level: "info",
                    title: L10n.t("dflash.restart.title"),
                    detail: L10n.t("dflash.restart.body"),
                    kind: "restart_required",
                    at: Date().timeIntervalSince1970
                )
            }
        }
    }

    func patchSettings(_ patch: SettingsPatch) {
        perform("settings") {
            let _: SettingsPutResult = try await self.client.put("/api/settings", body: patch)
            await self.refreshConfig()
        }
    }

    private func adoptAliasDraftFromConfig() {
        guard !aliasEditing, let next = config?.api.alias, !next.isEmpty else { return }
        aliasDraft = next
    }

    func noteAliasDraftChanged() {
        let trimmed = aliasDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        aliasEditing = trimmed != alias
    }

    func commitAlias() {
        let next = aliasDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        if next.isEmpty {
            aliasDraft = alias
            aliasEditing = false
            return
        }
        if next == alias {
            aliasEditing = false
            return
        }
        aliasEditing = false
        patchSettings(SettingsPatch(api: .init(alias: next, aliasAuto: false)))
    }

    func resetAliasAuto() {
        aliasEditing = false
        patchSettings(SettingsPatch(api: .init(aliasAuto: true)))
    }

    func copyAlias() {
        let value = aliasDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        copy(value.isEmpty ? alias : value)
        commitAlias()
    }

    func installService(_ name: String) {
        perform("service") {
            struct R: Decodable { var ok: Bool }
            let _: R = try await self.client.post("/api/service/install", body: ServiceNameBody(service: name))
            await self.loadServices()
        }
    }

    func uninstallService(_ name: String) {
        perform("service") {
            struct R: Decodable { var ok: Bool }
            let _: R = try await self.client.post("/api/service/uninstall", body: ServiceNameBody(service: name))
            await self.loadServices()
        }
    }

    func startBench(_ path: String, promptKey: String? = nil) {
        perform("bench") {
            if let key = promptKey {
                let _: ActionResult = try await self.client.post(path, body: PromptKeyBody(promptKey: key))
            } else {
                let _: ActionResult = try await self.client.post(path)
            }
            await self.loadBenchmark()
        }
    }

    func pollBenchJob() async {
        benchJob = try? await client.get("/api/benchmark/job")
        if benchJob?.busy == false {
            benchHistory = (try? await client.get("/api/benchmark/history?limit=30")) ?? benchHistory
        }
    }

    func testAgents() async -> ConnectionTest? {
        try? await client.post("/api/agents/test")
    }

    func setLanguage(_ id: String) {
        applyLanguagePreference(id, persistRemote: true)
    }

    private func applyLanguagePreference(_ id: String, persistRemote: Bool) {
        let next = L10n.supported.contains(id) ? id : "system"
        let changed = next != appLanguage
        appLanguage = next
        UserDefaults.standard.set(next, forKey: "appLanguage")
        if changed {
            NotificationCenter.default.post(name: .localAILanguageChanged, object: nil)
        }
        guard persistRemote else { return }
        patchSettings(SettingsPatch(ui: .init(language: next)))
    }

    func locateProject() {
        if ProjectRoot.locateInteractive() == nil {
            locateError = L10n.t("settings.locate.fail")
        } else {
            locateError = nil
        }
    }

    func openSettings() {
        AppActivation.enter()
        NSApp.activate()
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }

    func toggleSidebar() {
        sidebarHidden.toggle()
    }
}
