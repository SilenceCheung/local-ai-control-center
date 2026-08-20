import AppKit
import Combine
import Foundation

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

    private var pollTask: Task<Void, Never>?
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
    var alias: String { config?.api.alias ?? "qwen3.8-27b-local" }

    func start() {
        Notifier.request()
        pollTask?.cancel()
        pollTask = Task { @MainActor [weak self] in
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

            if popoverVisible || consoleVisible {
                let snap: MonitorSnapshot = try await client.get("/api/monitor/snapshot?n=90")
                samples = snap.samples
                latestSample = snap.samples.last
                memoryAdvisory = snap.memoryAdvisory
                if let adv = snap.memoryAdvisory, adv.level != lastMemoryLevel {
                    lastMemoryLevel = adv.level
                    if adv.level == "critical" || adv.level == "warning" {
                        Notifier.post(id: "memory", title: adv.title, body: adv.detail)
                    }
                } else if snap.memoryAdvisory == nil {
                    lastMemoryLevel = nil
                }
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
                title: "Fell back to Safe Mode",
                body: next.advisory?.detail ?? "DFlash crashed and the runtime restarted target-only."
            )
        } else if let count = next.fallbackCount {
            lastFallbackCount = count
        }
        if previous == .starting && next.status == .running {
            Notifier.post(id: "running", title: "Local AI Runtime is ready",
                          body: next.targetModel ?? alias)
        }
        if previous == .running && next.status == .error {
            Notifier.post(id: "error", title: "Runtime error",
                          body: next.error ?? "See Logs in Local AI.")
        }
        if let adv = next.advisory, adv.kind == "low_acceptance" {
            Notifier.post(id: "acceptance", title: adv.title, body: adv.detail)
        }
    }

    func refreshConfig() async {
        do { config = try await client.get("/api/settings") }
        catch { lastError = error.localizedDescription }
    }

    func loadOverviewExtras() async {
        async let c: AppConfig? = try? await client.get("/api/settings")
        async let a: [AgentInfo]? = try? await client.get("/api/agents")
        async let g: GatewayStatsEnvelope? = try? await client.get("/api/gateway/stats")
        config = await c
        agents = await a ?? []
        gateway = await g
    }

    func loadModels() async {
        do { models = try await client.get("/api/models") }
        catch { lastError = error.localizedDescription }
    }

    func loadDFlash() async {
        do { dflash = try await client.get("/api/dflash") }
        catch { lastError = error.localizedDescription }
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
        perform("start") {
            let _: RuntimeStatus = try await self.client.post("/api/runtime/start")
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
        }
    }

    func setMode(_ mode: RuntimeMode) {
        perform("mode") {
            let _: RuntimeStatus = try await self.client.post("/api/runtime/mode", body: ModeBody(mode: mode.rawValue))
            await self.refreshConfig()
        }
    }

    func startControlPlane() {
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
            let _: R = try await self.client.put("/api/dflash", body: patch)
            await self.loadDFlash()
        }
    }

    func patchSettings(_ patch: SettingsPatch) {
        perform("settings") {
            let _: SettingsPutResult = try await self.client.put("/api/settings", body: patch)
            await self.refreshConfig()
        }
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
}
