import AppKit
import Combine
import SwiftUI

extension Notification.Name {
    static let localAIOpenConsole = Notification.Name("localAI.openConsole")
    static let localAIOpenHelp = Notification.Name("localAI.openHelp")
    static let localAIOpenAbout = Notification.Name("localAI.openAbout")
    static let localAILanguageChanged = Notification.Name("localAI.languageChanged")
}

enum AppActivation {
    private static var count = 0

    static func enter() {
        count += 1
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
    }

    static func leave() {
        count = max(0, count - 1)
        guard count == 0 else { return }
        NSApp.setActivationPolicy(.accessory)
    }
}

/// SwiftUI hosted in an NSWindow must not drive the frame.
/// Default NSHostingController.sizingOptions tracks intrinsicContentSize, so
/// switching Console pages (Table / logs) would grow the window.
enum HostedWindow {
    static func wrap(
        _ host: NSHostingController<AnyView>,
        title: String,
        contentSize: NSSize,
        minSize: NSSize,
        autosave: String,
        delegate: NSWindowDelegate?
    ) -> NSWindow {
        host.sizingOptions = []
        host.view.setContentHuggingPriority(.windowSizeStayPut, for: .vertical)
        host.view.setContentHuggingPriority(.windowSizeStayPut, for: .horizontal)
        host.view.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        host.view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let window = NSWindow(contentViewController: host)
        window.styleMask.insert([.titled, .closable, .miniaturizable, .resizable])
        window.setContentSize(contentSize)
        window.minSize = minSize
        window.contentMinSize = minSize
        window.isReleasedWhenClosed = false
        window.delegate = delegate
        window.setFrameAutosaveName(autosave)
        window.identifier = NSUserInterfaceItemIdentifier(autosave)
        window.title = title
        return window
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSPopoverDelegate {
    let store = AppStore.shared
    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private var consoleWindow: NSWindow?
    private var helpWindow: NSWindow?
    private var consoleHost: NSHostingController<AnyView>?
    private var helpHost: NSHostingController<AnyView>?
    private var cancellables = Set<AnyCancellable>()
    private var aboutCloseObserver: NSObjectProtocol?
    private var aboutActivationHeld = false
    private var showingStatusMenu = false
    private var pendingStatusAction: (() -> Void)?

    private var isShuttingDown = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        ProcessInfo.processInfo.disableSuddenTermination()
        NSApp.setActivationPolicy(.accessory)
        ServiceSupervisor.neutralizeLoginOrphans()
        ServiceSupervisor.startSessionWatchdog()
        store.start()
        setupStatusItem()
        bindStore()
        NotificationCenter.default.addObserver(forName: .localAIOpenConsole, object: nil, queue: .main) { [weak self] _ in
            self?.openConsole()
        }
        NotificationCenter.default.addObserver(forName: .localAIOpenHelp, object: nil, queue: .main) { [weak self] _ in
            self?.openHelp()
        }
        NotificationCenter.default.addObserver(forName: .localAIOpenAbout, object: nil, queue: .main) { [weak self] _ in
            self?.showAbout()
        }
        NotificationCenter.default.addObserver(forName: .localAILanguageChanged, object: nil, queue: .main) { [weak self] _ in
            self?.applyLanguage()
        }
        NotificationCenter.default.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
            object: NSWorkspace.shared,
            queue: .main
        ) { [weak self] _ in
            self?.applyDisplayPrefs()
        }
        applyDisplayPrefs()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if isShuttingDown { return .terminateNow }
        isShuttingDown = true
        store.stopPolling()

        if store.keepServicesOnQuit {
            ServiceSupervisor.writeKeepFlag(true)
            return .terminateNow
        }

        if store.running {
            let alert = NSAlert()
            alert.messageText = L10n.t("quit.confirm.title")
            alert.informativeText = L10n.t("quit.confirm.body")
            alert.addButton(withTitle: L10n.t("quit.confirm.quit"))
            alert.addButton(withTitle: L10n.t("quit.confirm.keep"))
            alert.addButton(withTitle: L10n.t("common.cancel"))
            switch alert.runModal() {
            case .alertFirstButtonReturn:
                break
            case .alertSecondButtonReturn:
                ServiceSupervisor.writeKeepFlag(true)
                return .terminateNow
            default:
                isShuttingDown = false
                return .terminateCancel
            }
        }

        DispatchQueue.global(qos: .userInitiated).async {
            ServiceSupervisor.shutdownOwnedStack(stopRuntimeFirst: true)
            DispatchQueue.main.async {
                NSApp.reply(toApplicationShouldTerminate: true)
            }
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ notification: Notification) {
        store.stopPolling()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openConsole()
        return true
    }

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = StatusIcon.image(kind: .idle)
        item.button?.imagePosition = .imageOnly
        item.button?.target = self
        item.button?.action = #selector(togglePopover)
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        item.button?.toolTip = L10n.t("app.name")
        item.button?.setAccessibilityLabel(L10n.t("app.name"))
        item.button?.setAccessibilityRole(.button)
        item.button?.setAccessibilityHelp(L10n.t("status.item.help"))
        statusItem = item

        let pop = NSPopover()
        pop.behavior = .transient
        pop.animates = true
        pop.delegate = self
        popover = pop
        refreshPopoverContent()
    }

    func refreshPopoverContent() {
        let view = StatusPopover(onOpenConsole: { [weak self] in
            self?.popover?.performClose(nil)
            self?.openConsole()
        })
        .environmentObject(store)
        .environment(\.locale, store.swiftLocale)
        .id(store.appLanguage + L10n.resolvedCode)

        let host = NSHostingController(rootView: view)
        applyDisplayPrefs()
        host.view.frame = NSRect(x: 0, y: 0, width: 380, height: 10)
        host.view.layoutSubtreeIfNeeded()
        var size = host.view.fittingSize
        if size.width < 320 { size.width = 320 }
        if size.height < 120 { size.height = 120 }
        popover?.contentSize = size
        popover?.contentViewController = host
    }

    private func applyDisplayPrefs() {
        popover?.animates = !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }

    private func bindStore() {
        store.$runtime
            .combineLatest(store.$backendReachable)
            .map { StatusKind.from($0, backendUp: $1) }
            .removeDuplicates()
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshIcon() }
            .store(in: &cancellables)

        store.$consolePage
            .receive(on: RunLoop.main)
            .sink { [weak self] page in
                self?.consoleWindow?.title = page.title
            }
            .store(in: &cancellables)
    }

    func refreshIcon() {
        let kind = StatusKind.from(store.runtime, backendUp: store.backendReachable)
        statusItem?.button?.image = StatusIcon.image(kind: kind)
        statusItem?.button?.setAccessibilityLabel(L10n.t("app.name"))
        statusItem?.button?.setAccessibilityValue(kind.accessibilityLabel)
        statusItem?.button?.setAccessibilityHelp(L10n.t("status.item.help"))
        statusItem?.button?.toolTip = "\(L10n.t("app.name")) — \(kind.accessibilityLabel)"
    }

    @objc private func togglePopover(_ sender: Any?) {
        if showingStatusMenu { return }
        guard let button = statusItem?.button, let popover else { return }
        if NSApp.currentEvent?.type == .rightMouseUp {
            showStatusMenu(from: button)
            return
        }
        if popover.isShown {
            popover.performClose(sender)
        } else {
            refreshPopoverContent()
            NSApp.activate()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    private func showStatusMenu(from button: NSStatusBarButton) {
        popover?.performClose(nil)
        let menu = NSMenu()
        menu.autoenablesItems = true
        let console = NSMenuItem(title: L10n.t("menu.console"), action: #selector(queueOpenConsoleMenu), keyEquivalent: "")
        console.target = self
        menu.addItem(console)
        let copy = NSMenuItem(title: L10n.t("menu.copy_api"), action: #selector(queueCopyAPIMenu), keyEquivalent: "")
        copy.target = self
        menu.addItem(copy)
        let dash = NSMenuItem(title: L10n.t("menu.dashboard"), action: #selector(queueOpenDashboardMenu), keyEquivalent: "")
        dash.target = self
        menu.addItem(dash)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: L10n.t("menu.quit"), action: #selector(queueQuitMenu), keyEquivalent: "")
        quit.target = self
        menu.addItem(quit)

        // Anchor at the button's bottom edge so the menu grows downward, clear of
        // the system menu bar. Top-edge popUp overlaps the bar; highlighting the
        // first item then shoves the whole menu down.
        let anchor = NSPoint(
            x: 0,
            y: button.isFlipped ? button.bounds.maxY : button.bounds.minY
        )
        showingStatusMenu = true
        pendingStatusAction = nil
        menu.popUp(positioning: nil, at: anchor, in: button)
        showingStatusMenu = false
        let action = pendingStatusAction
        pendingStatusAction = nil
        action?()
    }

    @objc private func queueOpenConsoleMenu() {
        pendingStatusAction = { [weak self] in self?.openConsole() }
    }

    @objc private func queueCopyAPIMenu() {
        pendingStatusAction = { [weak self] in self?.store.copyAPIConfig() }
    }

    @objc private func queueOpenDashboardMenu() {
        pendingStatusAction = { [weak self] in self?.store.openDashboard() }
    }

    @objc private func queueQuitMenu() {
        pendingStatusAction = { NSApp.terminate(nil) }
    }

    func openConsole() {
        AppActivation.enter()
        if consoleWindow == nil {
            let host = NSHostingController(rootView: consoleRoot())
            consoleHost = host
            consoleWindow = HostedWindow.wrap(
                host,
                title: store.consolePage.title,
                contentSize: NSSize(width: 980, height: 680),
                minSize: NSSize(width: 720, height: 480),
                autosave: "LocalAIConsole.v2",
                delegate: self
            )
        }
        consoleWindow?.title = store.consolePage.title
        DispatchQueue.main.async { [weak self] in
            self?.consoleWindow?.makeKeyAndOrderFront(nil)
            NSApp.activate()
        }
    }

    func openHelp() {
        AppActivation.enter()
        if helpWindow == nil {
            let host = NSHostingController(rootView: helpRoot())
            helpHost = host
            helpWindow = HostedWindow.wrap(
                host,
                title: L10n.t("help.title"),
                contentSize: NSSize(width: 520, height: 420),
                minSize: NSSize(width: 400, height: 280),
                autosave: "LocalAIHelp.v2",
                delegate: self
            )
        }
        helpWindow?.title = L10n.t("help.title")
        helpWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    private func consoleRoot() -> AnyView {
        AnyView(
            ConsoleView()
                .environmentObject(store)
                .environment(\.locale, L10n.locale)
                .id(store.appLanguage + L10n.resolvedCode)
        )
    }

    private func helpRoot() -> AnyView {
        AnyView(
            HelpView()
                .environmentObject(store)
                .environment(\.locale, L10n.locale)
                .id(store.appLanguage + L10n.resolvedCode)
        )
    }

    func applyLanguage() {
        consoleHost?.rootView = consoleRoot()
        helpHost?.rootView = helpRoot()
        consoleWindow?.title = store.consolePage.title
        helpWindow?.title = L10n.t("help.title")
        refreshPopoverContent()
        refreshIcon()
    }

    func showAbout() {
        if !aboutActivationHeld {
            AppActivation.enter()
            aboutActivationHeld = true
        }
        NSApp.activate()
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: L10n.t("app.name"),
            .credits: NSAttributedString(
                string: L10n.t("about.subtitle"),
                attributes: [
                    .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
                    .foregroundColor: NSColor.secondaryLabelColor
                ]
            )
        ])
        if let existing = aboutCloseObserver {
            NotificationCenter.default.removeObserver(existing)
            aboutCloseObserver = nil
        }
        aboutCloseObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let self else { return }
            guard let window = note.object as? NSWindow else { return }
            guard window !== self.consoleWindow, window !== self.helpWindow else { return }
            let title = window.title
            let isAbout = title.hasPrefix("About") || title.hasPrefix("关于") || window.className.contains("About")
            guard isAbout, self.aboutActivationHeld else { return }
            self.aboutActivationHeld = false
            AppActivation.leave()
            if let obs = self.aboutCloseObserver {
                NotificationCenter.default.removeObserver(obs)
                self.aboutCloseObserver = nil
            }
        }
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        if window === consoleWindow || window === helpWindow {
            AppActivation.leave()
        }
    }
}

@main
struct LocalAIApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            SettingsRoot()
                .environmentObject(AppStore.shared)
                .environment(\.locale, AppStore.shared.swiftLocale)
                .id(AppStore.shared.appLanguage + L10n.resolvedCode)
                .onAppear {
                    AppActivation.enter()
                    DispatchQueue.main.async {
                        NSApp.keyWindow?.standardWindowButton(.zoomButton)?.isEnabled = false
                    }
                }
                .onDisappear { AppActivation.leave() }
        }
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button(L10n.t("menu.about")) {
                    NotificationCenter.default.post(name: .localAIOpenAbout, object: nil)
                }
            }
            CommandGroup(replacing: .newItem) {
                Button(L10n.t("menu.open_console")) {
                    NotificationCenter.default.post(name: .localAIOpenConsole, object: nil)
                }
                Button(L10n.t("menu.dashboard")) { AppStore.shared.openDashboard() }
                Button(L10n.t("menu.reveal_library")) { AppStore.shared.revealLibrary() }
            }
            CommandGroup(after: .pasteboard) {
                Button(L10n.t("menu.copy_api")) { AppStore.shared.copyAPIConfig() }
                    .keyboardShortcut("c", modifiers: [.command, .shift])
            }
            CommandGroup(after: .sidebar) {
                Button(L10n.t("menu.sidebar")) {
                    AppStore.shared.toggleSidebar()
                }
                .keyboardShortcut("s", modifiers: [.command, .control])
                Button(L10n.t("models.rescan")) { AppStore.shared.scanModels() }
                    .keyboardShortcut("r", modifiers: [.command])
            }
            CommandMenu(L10n.t("menu.navigate")) {
                ForEach(Array(ConsolePage.allCases.enumerated()), id: \.element) { index, page in
                    Button(page.title) {
                        AppStore.shared.consolePage = page
                        NotificationCenter.default.post(name: .localAIOpenConsole, object: nil)
                    }
                    .keyboardShortcut(KeyEquivalent(Character(String(index + 1))), modifiers: [.command])
                }
            }
            CommandMenu(L10n.t("menu.runtime")) {
                Button(L10n.t("menu.start")) { AppStore.shared.startRuntime() }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(AppStore.shared.running || AppStore.shared.isActing)
                Button(L10n.t("menu.stop")) { AppStore.shared.stopRuntime() }
                    .keyboardShortcut("k", modifiers: [.command, .shift])
                    .disabled(!AppStore.shared.running || AppStore.shared.isActing)
                Button(L10n.t("menu.restart")) { AppStore.shared.restartRuntime() }
                    .keyboardShortcut("r", modifiers: [.command, .option])
                    .disabled(!AppStore.shared.running || AppStore.shared.isActing)
            }
            CommandGroup(after: .windowList) {
                Button(L10n.t("menu.console")) {
                    NotificationCenter.default.post(name: .localAIOpenConsole, object: nil)
                }
                .keyboardShortcut("l", modifiers: [.command])
            }
            CommandGroup(replacing: .help) {
                Button(L10n.t("menu.help")) {
                    NotificationCenter.default.post(name: .localAIOpenHelp, object: nil)
                }
                .keyboardShortcut("?", modifiers: [.command])
            }
        }
    }
}
