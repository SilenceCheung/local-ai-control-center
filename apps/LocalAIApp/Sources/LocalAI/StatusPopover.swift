import SwiftUI

struct StatusPopover: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.dynamicTypeSize) private var typeSize
    var onOpenConsole: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            header
            if !store.backendReachable {
                firstRun
            } else {
                if let err = store.lastError {
                    ErrorBanner(title: L10n.t("popover.generic_error"), detail: err)
                }
                if let notice = store.statusNotice {
                    AdvisoryBanner(advisory: notice)
                }
                if let adv = store.runtime.advisory {
                    AdvisoryBanner(advisory: adv)
                }
                metrics
                controls
                modePicker
            }
            Divider()
            footer
        }
        .padding(Space.lg)
        .frame(width: typeSize.isAccessibilitySize ? 380 : 320)
        .background {
            if reduceTransparency {
                Color(nsColor: .windowBackgroundColor)
            }
        }
        .onAppear {
            store.popoverVisible = true
            Task { await store.tick(); await store.refreshConfig() }
        }
        .onDisappear { store.popoverVisible = false }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(L10n.t("popover.title"))
                .font(TypeScale.section)
            StatusLine(
                life: store.backendReachable ? store.runtime.status : .error,
                healthy: store.runtime.httpHealthy,
                extra: subtitleExtra
            )
        }
        .accessibilityElement(children: .combine)
    }

    private var subtitleExtra: String? {
        if !store.backendReachable { return L10n.t("status.control_down") }
        if store.isActing { return L10n.t("status.working") }
        return store.runtime.targetModel?.split(separator: "/").last.map(String.init)
    }

    private var firstRun: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            EmptyState(
                title: L10n.t("popover.first_run.title"),
                bodyText: L10n.t("popover.first_run.body"),
                actionTitle: store.isActing ? nil : L10n.t("popover.start_control"),
                action: store.isActing ? nil : { store.startControlPlane() }
            )
            if store.isActing {
                ProgressView().controlSize(.small)
                    .accessibilityLabel(L10n.t("status.working"))
            }
            if let err = store.lastError {
                ErrorBanner(title: L10n.t("popover.control_error"), detail: err) {
                    store.startControlPlane()
                }
            }
        }
    }

    private var metrics: some View {
        let rm = store.latestSample?.runtime
        return HStack(alignment: .top, spacing: Space.sm) {
            StatCell(label: L10n.t("popover.memory"), value: Formatters.num(store.latestSample?.memUsedGb), unit: L10n.t("popover.unit.gb"))
            StatCell(label: L10n.t("popover.speed"), value: Formatters.num(rm?.decodeTokS), unit: L10n.t("popover.unit.toks"))
            StatCell(
                label: L10n.t("popover.accept"),
                value: store.runtime.mode == .fast ? Formatters.pct(rm?.acceptanceRate) : L10n.t("emdash")
            )
        }
    }

    private var controls: some View {
        HStack(spacing: Space.sm) {
            if store.running {
                Button(L10n.t("popover.stop")) { store.stopRuntime() }
                    .disabled(store.isActing)
                    .accessibilityHint(L10n.t("menu.stop.hint"))
            } else {
                Button(L10n.t("popover.start")) { store.startRuntime() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(store.isActing || !store.backendReachable)
                    .accessibilityHint(L10n.t("menu.start.hint"))
            }
            if store.isActing {
                ProgressView().controlSize(.small)
                    .accessibilityLabel(L10n.t("status.working"))
            }
            Spacer()
        }
        .controlSize(.regular)
    }

    private var modePicker: some View {
        Picker(L10n.t("runtime.mode"), selection: Binding(
            get: { store.runtime.mode },
            set: { store.setMode($0) }
        )) {
            ForEach(RuntimeMode.allCases) { mode in
                Text(mode.localizedTitle).tag(mode)
            }
        }
        .pickerStyle(.segmented)
        .disabled(store.isActing || !store.backendReachable)
        .accessibilityLabel(L10n.t("runtime.mode"))
        .accessibilityHint(L10n.t("mode.help"))
        .help(L10n.t("mode.help"))
    }

    private var footer: some View {
        HStack {
            Button(L10n.t("popover.copy")) { store.copyAPIConfig() }
                .accessibilityHint(L10n.t("popover.copy.hint"))
            Spacer()
            Button(L10n.t("popover.console")) { onOpenConsole() }
                .keyboardShortcut("l", modifiers: [.command])
                .accessibilityHint(L10n.t("help.job.console.body"))
        }
        .controlSize(.small)
    }
}
