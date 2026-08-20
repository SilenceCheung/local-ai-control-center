import SwiftUI

struct StatusPopover: View {
    @EnvironmentObject var store: AppStore
    var onOpenConsole: () -> Void
    var onQuit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            if let err = store.lastError, !store.backendReachable {
                ErrorBanner(title: "Control plane is not running", detail: err) {
                    store.startControlPlane()
                }
            } else if let err = store.lastError {
                ErrorBanner(title: "Something went wrong", detail: err)
            }
            if let adv = store.runtime.advisory {
                AdvisoryBanner(advisory: adv)
            }
            if store.backendReachable {
                metrics
                controls
                modePicker
            } else {
                Button("Start Control Plane") { store.startControlPlane() }
                    .keyboardShortcut("k", modifiers: [.command])
                    .disabled(store.isActing)
            }
            Divider()
            footer
        }
        .padding(16)
        .frame(width: 340)
        .onAppear {
            store.popoverVisible = true
            Task { await store.tick(); await store.refreshConfig() }
        }
        .onDisappear { store.popoverVisible = false }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            StatusDot(life: store.backendReachable ? store.runtime.status : .error,
                      healthy: store.runtime.httpHealthy)
            VStack(alignment: .leading, spacing: 2) {
                Text("Local AI Runtime")
                    .font(.headline)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer()
        }
        .accessibilityElement(children: .combine)
    }

    private var subtitle: String {
        if !store.backendReachable { return "Control plane unreachable" }
        if store.isActing { return "\(store.busyAction?.capitalized ?? "Working")…" }
        let life = store.runtime.status.rawValue
        let model = store.runtime.targetModel?.split(separator: "/").last.map(String.init)
        if let model, store.running {
            return "\(life) · \(model)"
        }
        return life
    }

    private var metrics: some View {
        let rm = store.latestSample?.runtime
        return HStack(alignment: .top, spacing: 8) {
            StatCell(label: "Memory", value: Formatters.num(store.latestSample?.memUsedGb), unit: "GB")
            StatCell(label: "Speed", value: Formatters.num(rm?.decodeTokS), unit: "tok/s")
            StatCell(label: "Accept", value: store.runtime.mode == .fast ? Formatters.pct(rm?.acceptanceRate) : "—")
        }
    }

    private var controls: some View {
        HStack(spacing: 8) {
            if store.running {
                Button("Restart") { store.restartRuntime() }
                    .disabled(store.isActing)
                Button("Stop", role: .destructive) { store.stopRuntime() }
                    .disabled(store.isActing)
            } else {
                Button("Start") { store.startRuntime() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(store.isActing || !store.backendReachable)
            }
            if store.isActing {
                ProgressView().controlSize(.small)
            }
            Spacer()
        }
        .controlSize(.regular)
    }

    private var modePicker: some View {
        Picker("Mode", selection: Binding(
            get: { store.runtime.mode },
            set: { store.setMode($0) }
        )) {
            ForEach(RuntimeMode.allCases) { mode in
                Text(mode.title).tag(mode)
            }
        }
        .pickerStyle(.segmented)
        .disabled(store.isActing || !store.backendReachable)
        .accessibilityLabel("Runtime mode")
        .help("Fast uses DFlash speculative decoding. Safe is target-only.")
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Button("Copy API Config") { store.copyAPIConfig() }
                Button("Dashboard") { store.openDashboard() }
            }
            HStack {
                Button("Open Console…") { onOpenConsole() }
                    .keyboardShortcut("l", modifiers: [.command])
                Spacer()
                Button("Quit Local AI") { onQuit() }
                    .keyboardShortcut("q")
            }
        }
        .controlSize(.small)
    }
}
