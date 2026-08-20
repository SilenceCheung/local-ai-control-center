import Foundation

enum RuntimeMode: String, Codable, CaseIterable, Identifiable {
    case safe, fast
    var id: String { rawValue }
    var title: String { self == .fast ? "Fast" : "Safe" }
    var subtitle: String {
        self == .fast ? "Target + DFlash" : "Target only"
    }
}

enum RuntimeLife: String, Codable {
    case stopped, starting, running, stopping, error
}

struct Advisory: Codable, Equatable {
    var level: String
    var title: String
    var detail: String
    var kind: String?
    var at: Double?
}

struct RuntimeStatus: Codable, Equatable {
    var status: RuntimeLife
    var mode: RuntimeMode
    var provider: String?
    var pid: Int?
    var alias: String?
    var targetModel: String?
    var draftModel: String?
    var error: String?
    var processAlive: Bool
    var httpHealthy: Bool
    var engine: String?
    var uptimeS: Double?
    var advisory: Advisory?
    var fallbackCount: Int?

    static let empty = RuntimeStatus(
        status: .stopped, mode: .fast, provider: nil, pid: nil, alias: nil,
        targetModel: nil, draftModel: nil, error: nil, processAlive: false,
        httpHealthy: false, engine: nil, uptimeS: nil, advisory: nil, fallbackCount: 0
    )
}

struct HealthResponse: Codable {
    var backend: String
    var runtime: NestedRuntime
    var api: GatewayHealth
    var ports: Ports

    struct NestedRuntime: Codable {
        var status: RuntimeLife
        var mode: RuntimeMode
        var processAlive: Bool
        var httpHealthy: Bool
        var modelLoaded: Bool
        var draftLoaded: Bool
        var error: String?
    }

    struct GatewayHealth: Codable {
        var ok: Bool
    }

    struct Ports: Codable {
        var dashboard: Int
        var api: Int
    }
}

struct ModelInfo: Codable, Identifiable, Hashable {
    var id: String
    var displayName: String
    var architecture: String?
    var parameterSize: String?
    var quantization: String?
    var format: String?
    var localPath: String?
    var huggingfaceRepo: String?
    var role: String
    var compatibility: String?
    var contextLength: Int?
    var memoryEstimateGb: Double?
    var sizeBytes: Int?
    var status: String?
    var extra: Extra?

    struct Extra: Codable, Hashable {
        var isDflashDraft: Bool?
        var blockSize: Int?
        var modelType: String?
    }

    var isDraftCandidate: Bool { extra?.isDflashDraft == true }
}

struct DFlashState: Codable {
    var config: DFlashConfig
    var mode: RuntimeMode
    var active: Bool
    var draftModel: String
    var blockSizeTrained: Int?
    var metrics: MetricsEnvelope
    var fallbackCount: Int
    var advisory: Advisory?

    struct DFlashConfig: Codable {
        var enabled: Bool
        var verifyMode: String
        var verifyLenCap: Int
        var draftQuant: String?
        var fastpathMaxTokens: Int?
        var prefixCache: Bool?
    }

    struct MetricsEnvelope: Codable {
        var available: Bool
        var reason: String?
        var data: MetricsData?
    }

    struct MetricsData: Codable {
        var rates: [String: Double]?
        var rssGb: Double?
        var recentRequests: [RecentRequest]?
        var currentRequest: [String: JSONValue]?
    }

    struct RecentRequest: Codable {
        var generatedTokens: Int?
        var tokens: Int?
        var decodeTokS: Double?
        var acceptanceRate: Double?
        var tokensPerCycle: Double?
        var cycles: Int?
    }
}

struct MetricSample: Codable, Identifiable {
    var t: Double
    var cpuPct: Double?
    var memUsedGb: Double?
    var memTotalGb: Double?
    var memPct: Double?
    var swapUsedGb: Double?
    var pressureLevel: Int?
    var runtime: RuntimeSample?

    var id: Double { t }

    struct RuntimeSample: Codable {
        var decodeTokS: Double?
        var prefillTokS: Double?
        var rssGb: Double?
        var acceptanceRate: Double?
        var ttftS: Double?
        var activeRequest: Bool?
    }
}

struct MonitorSnapshot: Codable {
    var samples: [MetricSample]
    var memoryAdvisory: Advisory?
}

struct AppConfig: Codable {
    var api: API
    var dashboard: HostPort
    var runtime: Runtime
    var dflash: DFlashState.DFlashConfig
    var memory: Memory
    var logging: Logging
    var privacy: Privacy
    var modelDirs: [String]?

    struct API: Codable {
        var host: String
        var port: Int
        var apiKey: String
        var alias: String
    }
    struct HostPort: Codable {
        var host: String
        var port: Int
    }
    struct Runtime: Codable {
        var provider: String?
        var internalPort: Int?
        var mode: RuntimeMode
        var autoLoad: Bool
        var targetModel: String
        var draftModel: String
        var maxContext: Int
        var defaultMaxTokens: Int
        var enableThinking: Bool?
    }
    struct Memory: Codable {
        var swapWarnGb: Double
        var pressureWarnPct: Double?
    }
    struct Logging: Codable { var level: String }
    struct Privacy: Codable { var logPrompts: Bool }
}

struct GatewayStatsEnvelope: Codable {
    var ok: Bool
    var live: Bool?
    var stats: Stats?

    struct Stats: Codable {
        var startedAt: Double?
        var requestsTotal: Int?
        var requestsActive: Int?
        var errorsTotal: Int?
        var tokensGenerated: Int?
        var lastRequestAt: Double?
        var agentsSeen: [String: Double]?
    }
}

struct AgentInfo: Codable, Identifiable {
    var id: String
    var name: String
    var status: String
    var protocolName: String?
    var instructions: String
    var configSnippet: String?
    var notSupportedNatively: Bool?
    var config: Endpoint

    enum CodingKeys: String, CodingKey {
        case id, name, status, instructions
        case protocolName = "protocol"
        case configSnippet, notSupportedNatively, config
    }

    struct Endpoint: Codable {
        var baseUrl: String
        var apiKey: String
        var model: String
    }
}

struct BenchPrompt: Codable {
    var label: String
    var maxTokens: Int
}

struct BenchJob: Codable {
    var busy: Bool
    var job: Job?

    struct Job: Codable {
        var kind: String
        var status: String
        var current: String?
        var error: String?
        var steps: [Step]?
        var result: [String: JSONValue]?
        var startedAt: Double?
        var finishedAt: Double?
    }

    struct Step: Codable {
        var step: String
        var detail: String?
        var t: Double?
    }
}

struct BenchRun: Codable, Identifiable {
    var id: Int
    var kind: String
    var label: String?
    var mode: String?
    var promptKey: String?
    var results: [String: JSONValue]
    var createdAt: Double
}

struct LogPayload: Codable {
    var ok: Bool
    var lines: [String]?
    var path: String?
    var error: String?
    var totalLines: Int?
}

struct EventRow: Codable, Identifiable {
    var id: Int
    var kind: String
    var detail: String?
    var createdAt: Double
}

struct ServiceStatus: Codable {
    var service: String?
    var label: String?
    var installed: Bool
    var loaded: Bool
    var pid: Int?
}

struct RoleResult: Codable {
    var ok: Bool
    var restartRequired: Bool?
}

struct SettingsPutResult: Codable {
    var ok: Bool
    var restartRequired: Bool?
}

struct ConnectionTest: Codable {
    var ok: Bool
    var modelsOk: Bool?
    var chatOk: Bool?
    var reply: String?
    var elapsedS: Double?
    var error: String?
}

struct ActionResult: Codable {
    var ok: Bool?
    var error: String?
}

// MARK: - Flexible JSON

enum JSONValue: Codable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        if let v = try? c.decode(Double.self) { self = .number(v); return }
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode([JSONValue].self) { self = .array(v); return }
        if let v = try? c.decode([String: JSONValue].self) { self = .object(v); return }
        self = .null
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    var double: Double? {
        if case .number(let n) = self { return n }
        return nil
    }
    var bool: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }
    var string: String? {
        if case .string(let s) = self { return s }
        return nil
    }
    var object: [String: JSONValue]? {
        if case .object(let o) = self { return o }
        return nil
    }
}

extension Dictionary where Key == String, Value == JSONValue {
    func nested(_ key: String) -> [String: JSONValue]? { self[key]?.object }
    func number(_ key: String) -> Double? { self[key]?.double }
    func bool(_ key: String) -> Bool? { self[key]?.bool }
}
