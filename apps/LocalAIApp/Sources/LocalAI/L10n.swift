import Foundation

enum L10n {
    static let supported = ["system", "en", "zh-Hans"]

    static func t(_ key: String) -> String {
        NSLocalizedString(key, tableName: "Localizable", bundle: bundle, value: key, comment: "")
    }

    /// Preference: `system` | `en` | `zh-Hans`.
    static var preference: String { AppStore.shared.appLanguage }

    /// Concrete lproj name. `system` follows macOS preferred languages (any `zh*` → 简体).
    static var resolvedCode: String {
        resolve(preference)
    }

    static func resolve(_ pref: String) -> String {
        if pref == "en" { return "en" }
        if pref == "zh-Hans" { return "zh-Hans" }
        for lang in Locale.preferredLanguages {
            let id = lang.lowercased().replacingOccurrences(of: "_", with: "-")
            if id == "zh" || id.hasPrefix("zh-") { return "zh-Hans" }
        }
        if let code = Locale.autoupdatingCurrent.language.languageCode?.identifier.lowercased(),
           code == "zh" {
            return "zh-Hans"
        }
        return "en"
    }

    /// Always load an explicit .lproj. Bundle.main's automatic matching follows
    /// CFBundleDevelopmentRegion (en) and silently stays English on some SwiftPM apps.
    static var bundle: Bundle {
        let code = resolvedCode
        if let path = Bundle.main.path(forResource: code, ofType: "lproj"),
           let b = Bundle(path: path) {
            return b
        }
        if code != "en",
           let path = Bundle.main.path(forResource: "en", ofType: "lproj"),
           let b = Bundle(path: path) {
            return b
        }
        return .main
    }

    static var locale: Locale {
        switch resolvedCode {
        case "zh-Hans": return Locale(identifier: "zh-Hans")
        default: return Locale(identifier: "en")
        }
    }
}

extension RuntimeLife {
    var localizedTitle: String {
        switch self {
        case .stopped: return L10n.t("status.stopped")
        case .starting: return L10n.t("status.starting")
        case .running: return L10n.t("status.running")
        case .stopping: return L10n.t("status.stopping")
        case .error: return L10n.t("status.error")
        }
    }
}

extension RuntimeMode {
    var localizedTitle: String { self == .fast ? L10n.t("mode.fast") : L10n.t("mode.safe") }
    var localizedSubtitle: String {
        self == .fast ? L10n.t("mode.fast.sub") : L10n.t("mode.safe.sub")
    }
}
