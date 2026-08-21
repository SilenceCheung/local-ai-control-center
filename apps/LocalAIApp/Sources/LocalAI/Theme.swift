import AppKit
import SwiftUI
import UniformTypeIdentifiers

enum Space {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
}

enum Radius {
    static let sm: CGFloat = 6
    static let md: CGFloat = 8
    static let lg: CGFloat = 12
}

enum Stroke {
    static let hairline: CGFloat = 1
}

enum TypeScale {
    static let section: Font = .headline
    static let body: Font = .body
    static let caption: Font = .caption
    static let metric: Font = .title3.weight(.semibold).monospacedDigit()
    static let mono: Font = .body.monospaced()
    static let log: Font = .system(size: 12, design: .monospaced)
}

enum Motion {
    static let fast: Double = 0.15
}

enum Palette {
    static let accent = Color.accentColor
    static let ok = Color(nsColor: .systemGreen)
    static let warn = Color(nsColor: .systemOrange)
    static let err = Color(nsColor: .systemRed)
    static let idle = Color(nsColor: .tertiaryLabelColor)
    static let codeFill = Color.primary.opacity(0.04)

    static func status(_ life: RuntimeLife, healthy: Bool) -> Color {
        switch life {
        case .running: return healthy ? ok : warn
        case .starting, .stopping: return warn
        case .error: return err
        case .stopped: return idle
        }
    }
}

struct ToneBackdrop: View {
    var tone: Color
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        RoundedRectangle(cornerRadius: Radius.sm)
            .fill(tone.opacity(reduceTransparency ? 0.34 : 0.12))
            .overlay {
                if reduceTransparency || contrast == .increased {
                    RoundedRectangle(cornerRadius: Radius.sm)
                        .strokeBorder(tone.opacity(0.85), lineWidth: Stroke.hairline)
                }
            }
    }
}

struct CodeBackdrop: View {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        RoundedRectangle(cornerRadius: Radius.sm)
            .fill(reduceTransparency ? Color(nsColor: .textBackgroundColor) : Palette.codeFill)
            .overlay {
                if reduceTransparency || contrast == .increased {
                    RoundedRectangle(cornerRadius: Radius.sm)
                        .strokeBorder(Color.primary.opacity(0.35), lineWidth: Stroke.hairline)
                }
            }
    }
}

struct StatusGlyph: View {
    var life: RuntimeLife
    var healthy: Bool = true
    @Environment(\.accessibilityDifferentiateWithoutColor) private var withoutColor
    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(withoutColor ? Color.primary : Palette.status(life, healthy: healthy))
            .symbolRenderingMode(withoutColor ? .monochrome : .hierarchical)
            .accessibilityHidden(true)
    }

    private var symbol: String {
        switch life {
        case .stopped: return "cpu"
        case .starting, .stopping: return "clock.arrow.circlepath"
        case .running: return healthy ? "cpu.fill" : "exclamationmark.triangle.fill"
        case .error: return "xmark.octagon.fill"
        }
    }
}

struct StatusLine: View {
    var life: RuntimeLife
    var healthy: Bool = true
    var extra: String? = nil
    var body: some View {
        HStack(spacing: Space.sm) {
            StatusGlyph(life: life, healthy: healthy)
            Text(label)
                .font(TypeScale.body)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L10n.t("runtime.status"))
        .accessibilityValue(label)
    }

    private var label: String {
        if life == .running && !healthy { return L10n.t("status.unhealthy") }
        if let extra, !extra.isEmpty { return "\(life.localizedTitle) · \(extra)" }
        return life.localizedTitle
    }
}

struct StatCell: View {
    var label: String
    var value: String
    var unit: String = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(TypeScale.caption)
                .foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(value)
                    .font(TypeScale.metric)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                if !unit.isEmpty {
                    Text(unit)
                        .font(TypeScale.caption)
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
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(advisory.title)
                .font(.callout.weight(.semibold))
            Text(advisory.detail)
                .font(TypeScale.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(Space.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            ToneBackdrop(tone: (advisory.level == "critical" || advisory.level == "error") ? Palette.err : Palette.warn)
        )
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isStaticText)
    }
}

struct ErrorBanner: View {
    var title: String
    var detail: String?
    var retry: (() -> Void)?
    var body: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text(title).font(.callout.weight(.semibold))
                    Text(L10n.t("error.data_safe"))
                        .font(TypeScale.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: Space.md)
                if let retry {
                    Button(L10n.t("common.retry"), action: retry)
                }
            }
            if let detail, !detail.isEmpty {
                DisclosureGroup(L10n.t("error.detail")) {
                    Text(detail)
                        .font(TypeScale.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(Space.md)
        .background(ToneBackdrop(tone: Palette.err))
        .accessibilityElement(children: .contain)
    }
}

struct EmptyState: View {
    var title: String
    var bodyText: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text(title).font(TypeScale.section)
            Text(bodyText)
                .font(TypeScale.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .frame(maxWidth: 480, alignment: .leading)
        .padding(.vertical, Space.lg)
        .modifier(EmptyStateA11y(combine: actionTitle == nil))
    }
}

private struct EmptyStateA11y: ViewModifier {
    var combine: Bool
    @ViewBuilder
    func body(content: Content) -> some View {
        if combine {
            content.accessibilityElement(children: .combine)
        } else {
            content
        }
    }
}

struct CopyableRow: View {
    var label: String
    var value: String
    var copy: (String) -> Void
    var body: some View {
        LabeledContent(label) {
            HStack(spacing: Space.sm) {
                Text(value)
                    .font(TypeScale.mono)
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Button(L10n.t("common.copy")) { copy(value) }
                    .controlSize(.small)
                    .accessibilityLabel(String(format: L10n.t("a11y.copy_value"), label))
            }
        }
    }
}

struct EditableAliasRow: View {
    @EnvironmentObject var store: AppStore
    var label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            LabeledContent(label) {
                HStack(spacing: Space.sm) {
                    TextField(L10n.t("api.alias.placeholder"), text: $store.aliasDraft)
                        .font(TypeScale.mono)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        .onSubmit { store.commitAlias() }
                        .onChange(of: store.aliasDraft) { _, _ in
                            store.noteAliasDraftChanged()
                        }
                        .accessibilityLabel(label)
                        .accessibilityHint(L10n.t("api.alias.hint"))
                    Button(L10n.t("common.copy")) { store.copyAlias() }
                        .controlSize(.small)
                        .accessibilityLabel(String(format: L10n.t("a11y.copy_value"), label))
                }
            }
            HStack(spacing: Space.sm) {
                Text(hint)
                    .font(TypeScale.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if showReset {
                    Button(L10n.t("api.alias.reset")) { store.resetAliasAuto() }
                        .controlSize(.small)
                        .disabled(store.isActing)
                }
            }
        }
        .onDisappear { store.commitAlias() }
    }

    private var showReset: Bool {
        store.aliasEditing || !(store.config?.api.aliasAuto ?? true)
    }

    private var hint: String {
        if store.aliasEditing {
            return L10n.t("api.alias.dirty")
        }
        if store.config?.api.aliasAuto ?? true {
            return L10n.t("api.alias.auto_hint")
        }
        return L10n.t("api.alias.manual_hint")
    }
}

struct KVRow<Trailing: View>: View {
    var title: String
    var subtitle: String? = nil
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .center, spacing: Space.md) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                if let subtitle {
                    Text(subtitle)
                        .font(TypeScale.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: Space.md)
            trailing()
        }
        .padding(.vertical, Space.sm)
    }
}

struct FormWidth: ViewModifier {
    func body(content: Content) -> some View {
        content
            .frame(maxWidth: 680, alignment: .leading)
    }
}

struct CodeBlock: View {
    var text: String
    var body: some View {
        Text(text)
            .font(.system(.caption, design: .monospaced))
            .textSelection(.enabled)
            .padding(Space.sm)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CodeBackdrop())
    }
}

enum AppInfo {
    static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.4.0"
    }
    static var build: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "20"
    }
    static var versionLine: String { "\(version) (\(build))" }
}

struct LibraryDropCatcher: ViewModifier {
    @EnvironmentObject var store: AppStore

    func body(content: Content) -> some View {
        content
            .onDrop(of: [UTType.fileURL], isTargeted: Binding(
                get: { store.libraryDropTargeted },
                set: { store.libraryDropTargeted = $0 }
            )) { store.acceptLibraryDrop($0) }
            .overlay {
                if store.libraryDropTargeted {
                    RoundedRectangle(cornerRadius: Radius.md)
                        .strokeBorder(Palette.accent, style: StrokeStyle(lineWidth: max(Stroke.hairline * 2, 2), dash: [6, 4]))
                        .padding(2)
                        .allowsHitTesting(false)
                }
            }
    }
}

struct HelpView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.lg) {
                Text(L10n.t("help.title")).font(TypeScale.section)
                helpJob("1", title: L10n.t("help.job.start.title"), body: L10n.t("help.job.start.body"))
                helpJob("2", title: L10n.t("help.job.copy.title"), body: L10n.t("help.job.copy.body"))
                helpJob("3", title: L10n.t("help.job.console.title"), body: L10n.t("help.job.console.body"))
                Button(L10n.t("help.open_readme")) {
                    let readme = ProjectRoot.resolve().appendingPathComponent("README.md")
                    NSWorkspace.shared.open(readme)
                }
            }
            .padding(Space.xl)
            .frame(maxWidth: 560, alignment: .leading)
        }
        .frame(minWidth: 480, maxWidth: .infinity, maxHeight: .infinity)
    }

    private func helpJob(_ n: String, title: String, body: String) -> some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text("\(n). \(title)")
                .font(TypeScale.section)
            Text(body)
                .font(TypeScale.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }
}
