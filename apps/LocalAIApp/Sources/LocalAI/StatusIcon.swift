import AppKit

enum StatusKind {
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

    var accessibilityLabel: String {
        switch self {
        case .idle: return "Runtime stopped"
        case .starting: return "Runtime starting"
        case .running: return "Runtime running"
        case .warn: return "Runtime running, not healthy"
        case .error: return "Control plane or runtime error"
        }
    }
}

enum StatusIcon {
    static func image(kind: StatusKind, appearance: NSAppearance?) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            let dark = appearance?.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            let glyph = dark ? NSColor.white : NSColor.black
            let cpu = NSImage(systemSymbolName: "cpu", accessibilityDescription: nil)
            let config = NSImage.SymbolConfiguration(pointSize: 13, weight: .medium)
            if let cpu = cpu?.withSymbolConfiguration(config) {
                let framed = NSRect(x: 0, y: 2, width: 14, height: 14)
                cpu.draw(in: framed, from: .zero, operation: .sourceOver, fraction: 0.92)
            } else {
                glyph.setFill()
                NSBezierPath(ovalIn: NSRect(x: 4, y: 4, width: 8, height: 8)).fill()
            }
            let color: NSColor = {
                switch kind {
                case .idle: return NSColor.tertiaryLabelColor
                case .starting: return NSColor.systemOrange
                case .running: return NSColor.systemGreen
                case .warn: return NSColor.systemOrange
                case .error: return NSColor.systemRed
                }
            }()
            color.setFill()
            NSBezierPath(ovalIn: NSRect(x: 11, y: 1, width: 6, height: 6)).fill()
            return true
        }
        image.isTemplate = false
        return image
    }
}
