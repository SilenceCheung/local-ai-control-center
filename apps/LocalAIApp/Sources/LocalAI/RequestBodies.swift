struct ModeBody: Encodable { var mode: String }
struct PromptKeyBody: Encodable { var promptKey: String }
struct RoleBody: Encodable { var modelId: String; var role: String }
struct ServiceNameBody: Encodable { var service: String }
struct ModelIdBody: Encodable { var modelId: String }

struct DFlashPatch: Encodable {
    var enabled: Bool?
    var verifyMode: String?
    var verifyLenCap: Int?
    var draftModel: String?
}

struct SettingsPatch: Encodable {
    var runtime: RuntimePatch?
    var dflash: DFlashPatch?
    var api: AliasPatch?
    var logging: LoggingPatch?
    var memory: MemoryPatch?
    var privacy: PrivacyPatch?

    struct RuntimePatch: Encodable {
        var maxContext: Int?
        var defaultMaxTokens: Int?
        var enableThinking: Bool?
        var autoLoad: Bool?
        var targetModel: String?
        var draftModel: String?
        var mode: String?
    }
    struct AliasPatch: Encodable { var alias: String? }
    struct LoggingPatch: Encodable { var level: String? }
    struct MemoryPatch: Encodable { var swapWarnGb: Double? }
    struct PrivacyPatch: Encodable { var logPrompts: Bool? }
}
