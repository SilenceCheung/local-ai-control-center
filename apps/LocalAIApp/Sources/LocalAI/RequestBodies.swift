struct ModeBody: Encodable { var mode: String }
struct PromptKeyBody: Encodable { var promptKey: String }
struct RoleBody: Encodable { var modelId: String; var role: String }
struct ServiceNameBody: Encodable { var service: String }
struct ModelIdBody: Encodable { var modelId: String }
struct DeleteInstalledModelBody: Encodable {
    var modelId: String
    var confirmModelId: String
    var scope = "installed_model"
}

struct DFlashPatch: Encodable {
    var enabled: Bool?
    var verifyMode: String?
    var verifyLenCap: Int?
    var draftModel: String?
    var draftQuant: String?
    var runtimeBlockSize: Int?
    var draftBits: Int?
    var reasoning: String?
}

struct RecipesStatus: Codable {
    var active: String
    var generation: String?
    var missing: [DFlashState.MissingModel]?
    var engine: DFlashState.EngineInfo?
}

struct RecipeActivateBody: Encodable { var id: String }
struct RecipeActivateResult: Decodable {
    var ok: Bool
    var restartRequired: Bool?
}

struct PullBody: Encodable {
    var repoId: String
    var assignRole: String?
}

struct PullCtrlBody: Encodable {
    var repoId: String?
}

struct LibraryBody: Encodable { var path: String }
struct LibraryResult: Decodable {
    var ok: Bool
    var library: String
    var modelDirs: [String]?
}

struct SettingsPatch: Encodable {
    var runtime: RuntimePatch?
    var dflash: DFlashPatch?
    var api: AliasPatch?
    var logging: LoggingPatch?
    var memory: MemoryPatch?
    var privacy: PrivacyPatch?
    var ui: UIPatch?

    enum CodingKeys: String, CodingKey {
        case runtime, dflash, api, logging, memory, privacy, ui
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(runtime, forKey: .runtime)
        try c.encodeIfPresent(dflash, forKey: .dflash)
        try c.encodeIfPresent(api, forKey: .api)
        try c.encodeIfPresent(logging, forKey: .logging)
        try c.encodeIfPresent(memory, forKey: .memory)
        try c.encodeIfPresent(privacy, forKey: .privacy)
        try c.encodeIfPresent(ui, forKey: .ui)
    }

    struct RuntimePatch: Encodable {
        var maxContext: Int?
        var defaultMaxTokens: Int?
        var enableThinking: Bool?
        var autoLoad: Bool?
        var targetModel: String?
        var draftModel: String?
        var mode: String?
    }
    struct AliasPatch: Encodable {
        var alias: String?
        var aliasAuto: Bool?

        enum CodingKeys: String, CodingKey { case alias, aliasAuto }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encodeIfPresent(alias, forKey: .alias)
            try c.encodeIfPresent(aliasAuto, forKey: .aliasAuto)
        }
    }
    struct LoggingPatch: Encodable { var level: String? }
    struct MemoryPatch: Encodable { var swapWarnGb: Double? }
    struct PrivacyPatch: Encodable { var logPrompts: Bool? }
    struct UIPatch: Encodable { var language: String? }
}
