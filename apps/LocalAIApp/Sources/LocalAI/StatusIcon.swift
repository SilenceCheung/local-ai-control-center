import AppKit

enum StatusKind: Equatable {
    case idle, starting, running, warn, error

    static func from(_ rt: RuntimeStatus, backendUp: Bool) -> StatusKind {
        if !backendUp { return .error }
        switch rt.status {
        case .running: return rt.httpHealthy ? .running : .warn
        case .starting, .stopping: return .starting
        case .error: return .error
        case .stopped: return .idle
        }
    }

    var symbolName: String {
        switch self {
        case .idle: return "cpu"
        case .starting: return "clock.arrow.circlepath"
        case .running: return "cpu.fill"
        case .warn: return "exclamationmark.triangle.fill"
        case .error: return "xmark.octagon.fill"
        }
    }

    var accessibilityLabel: String {
        switch self {
        case .idle: return L10n.t("status.stopped")
        case .starting: return L10n.t("status.starting")
        case .running: return L10n.t("status.running")
        case .warn: return L10n.t("status.unhealthy")
        case .error: return L10n.t("status.control_down")
        }
    }

    var accessibilityValue: String { accessibilityLabel }
}

enum StatusIcon {
    /// Menu-bar extra: template SF Symbol so Aqua/Dark menu bars tint it.
    /// State is the glyph, not a color-only pip.
    static func image(kind: StatusKind) -> NSImage {
        let config = NSImage.SymbolConfiguration(pointSize: 14, weight: .medium)
        let named = NSImage(systemSymbolName: kind.symbolName, accessibilityDescription: kind.accessibilityLabel)
        let configured = named?.withSymbolConfiguration(config)
        let image = (configured?.copy() as? NSImage) ?? named ?? NSImage(size: NSSize(width: 18, height: 18))
        image.isTemplate = true
        return image
    }
}
