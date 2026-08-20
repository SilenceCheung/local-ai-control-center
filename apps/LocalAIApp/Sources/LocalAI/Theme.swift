import AppKit
import SwiftUI

enum Palette {
    static let accent = Color(nsColor: NSColor(srgbRed: 0.29, green: 0.37, blue: 0.76, alpha: 1))
    static let ok = Color(nsColor: NSColor(srgbRed: 0.24, green: 0.48, blue: 0.32, alpha: 1))
    static let warn = Color(nsColor: NSColor(srgbRed: 0.66, green: 0.46, blue: 0.17, alpha: 1))
    static let err = Color(nsColor: NSColor(srgbRed: 0.71, green: 0.27, blue: 0.24, alpha: 1))
    static let idle = Color(nsColor: NSColor.tertiaryLabelColor)

    static func status(_ life: RuntimeLife, healthy: Bool) -> Color {
        switch life {
        case .running: return healthy ? ok : warn
        case .starting, .stopping: return warn
        case .error: return err
        case .stopped: return idle
        }
    }
}

struct StatusDot: View {
    var life: RuntimeLife
    var healthy: Bool = true
    var body: some View {
        Circle()
            .fill(Palette.status(life, healthy: healthy))
            .frame(width: 8, height: 8)
            .accessibilityHidden(true)
    }
}

struct StatCell: View {
    var label: String
    var value: String
    var unit: String = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(value)
                    .font(.title3.weight(.semibold).monospacedDigit())
                    .lineLimit(1)
                if !unit.isEmpty {
                    Text(unit)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label), \(value) \(unit)")
    }
}

struct AdvisoryBanner: View {
    var advisory: Advisory
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(advisory.title)
                .font(.callout.weight(.semibold))
            Text(advisory.detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(advisory.level == "critical" || advisory.level == "error"
                      ? Palette.err.opacity(0.12)
                      : Palette.warn.opacity(0.14))
        )
        .accessibilityElement(children: .combine)
    }
}

struct ErrorBanner: View {
    var title: String
    var detail: String?
    var retry: (() -> Void)?
    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.callout.weight(.semibold))
                if let detail, !detail.isEmpty {
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
            Spacer()
            if let retry {
                Button("Retry", action: retry)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Palette.err.opacity(0.12)))
    }
}

struct KVRow<Trailing: View>: View {
    var title: String
    var subtitle: String? = nil
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                if let subtitle {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 12)
            trailing()
        }
        .padding(.vertical, 6)
    }
}
