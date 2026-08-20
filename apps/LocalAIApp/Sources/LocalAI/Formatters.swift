import Foundation

enum Formatters {
    static func bytes(_ n: Int?) -> String {
        guard let n, n > 0 else { return "—" }
        let d = Double(n)
        if d > 1e9 { return String(format: "%.1f GB", d / 1e9) }
        if d > 1e6 { return String(format: "%.0f MB", d / 1e6) }
        return String(format: "%.0f KB", d / 1e3)
    }

    static func num(_ n: Double?, digits: Int = 1) -> String {
        guard let n, n.isFinite else { return "—" }
        return String(format: "%.\(digits)f", n)
    }

    static func pct(_ n: Double?) -> String {
        guard let n, n.isFinite else { return "—" }
        let v = n > 1 ? n : n * 100
        return String(format: "%.1f%%", v)
    }

    static func uptime(_ s: Double?) -> String {
        guard let s, s > 0 else { return "—" }
        if s < 60 { return "\(Int(s))s" }
        if s < 3600 { return "\(Int(s / 60))m \(Int(s.truncatingRemainder(dividingBy: 60)))s" }
        return "\(Int(s / 3600))h \(Int((s.truncatingRemainder(dividingBy: 3600)) / 60))m"
    }

    static func time(_ t: Double?) -> String {
        guard let t, t > 0 else { return "—" }
        let date = Date(timeIntervalSince1970: t)
        return DateFormatter.localizedString(from: date, dateStyle: .short, timeStyle: .medium)
    }

    static func pressure(_ level: Int?) -> String {
        switch level {
        case 1: return "Normal"
        case 2: return "Warning"
        case 4: return "Critical"
        default: return "—"
        }
    }
}
