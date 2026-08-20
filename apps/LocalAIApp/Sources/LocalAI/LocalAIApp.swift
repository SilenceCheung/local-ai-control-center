import AppKit
import SwiftUI

extension Notification.Name {
    static let localAIOpenConsole = Notification.Name("localAI.openConsole")
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

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSPopoverDelegate {
    let store = AppStore.shared
    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private var consoleWindow: NSWindow?
    private var appearanceObserver: NSObjectProtocol?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        store.start()
        setupStatusItem()
        appearanceObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil, queue: .main
        ) { [weak self] _ in self?.refreshIcon() }
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refreshIcon() }
        }
        NotificationCenter.default.addObserver(forName: .localAIOpenConsole, object: nil, queue: .main) { [weak self] _ in
            self?.openConsole()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        store.stopPolling()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openConsole()
        return true
    }

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = StatusIcon.image(kind: .idle, appearance: NSApp.effectiveAppearance)
        item.button?.imagePosition = .imageOnly
        item.button?.target = self
        item.button?.action = #selector(togglePopover)
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        item.button?.toolTip = "Local AI"
        item.button?.setAccessibilityLabel("Local AI")
        statusItem = item

        let pop = NSPopover()
        pop.behavior = .transient
        pop.animates = true
        pop.delegate = self
        popover = pop
        refreshPopoverContent()
    }

    func refreshPopoverContent() {
        let view = StatusPopover(
            onOpenConsole: { [weak self] in
                self?.popover?.performClose(nil)
                self?.openConsole()
            },
            onQuit: { NSApp.terminate(nil) }
        )
        .environmentObject(store)
        popover?.contentSize = NSSize(width: 340, height: 420)
        popover?.contentViewController = NSHostingController(rootView: view)
    }

    func refreshIcon() {
        let kind = StatusKind.from(store.runtime, backendUp: store.backendReachable)
        statusItem?.button?.image = StatusIcon.image(kind: kind, appearance: NSApp.effectiveAppearance)
        statusItem?.button?.setAccessibilityLabel(kind.accessibilityLabel)
        statusItem?.button?.toolTip = "Local AI — \(kind.accessibilityLabel)"
    }

    @objc private func togglePopover(_ sender: Any?) {
        guard let button = statusItem?.button, let popover else { return }
        if NSApp.currentEvent?.type == .rightMouseUp {
            showStatusMenu(from: button)
            return
        }
        if popover.isShown {
            popover.performClose(sender)
        } else {
            refreshPopoverContent()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    private func showStatusMenu(from button: NSStatusBarButton) {
        let menu = NSMenu()
        menu.addItem(withTitle: "Open Console…", action: #selector(openConsoleMenu), keyEquivalent: "")
        menu.addItem(withTitle: "Open Dashboard", action: #selector(openDashboardMenu), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Local AI", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.items.forEach { $0.target = $0.action == #selector(NSApplication.terminate(_:)) ? nil : self }
        statusItem?.menu = menu
        statusItem?.button?.performClick(nil)
        statusItem?.menu = nil
        button.target = self
        button.action = #selector(togglePopover)
    }

    @objc private func openConsoleMenu() { openConsole() }
    @objc private func openDashboardMenu() { store.openDashboard() }

    func openConsole() {
        AppActivation.enter()
        if consoleWindow == nil {
            let host = NSHostingController(rootView: ConsoleView().environmentObject(store))
            let window = NSWindow(contentViewController: host)
            window.title = "Local AI"
            window.setContentSize(NSSize(width: 980, height: 680))
            window.minSize = NSSize(width: 800, height: 520)
            window.styleMask.insert([.titled, .closable, .miniaturizable, .resizable])
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.setFrameAutosaveName("LocalAIConsole")
            consoleWindow = window
        }
        consoleWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    func windowWillClose(_ notification: Notification) {
        if notification.object as? NSWindow === consoleWindow {
            AppActivation.leave()
        }
    }
}

@main
struct LocalAIApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            SettingsPage()
                .environmentObject(AppStore.shared)
                .frame(minWidth: 520, minHeight: 420)
                .padding(20)
        }
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("Runtime") {
                Button("Start") { AppStore.shared.startRuntime() }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(AppStore.shared.running || AppStore.shared.isActing)
                Button("Stop") { AppStore.shared.stopRuntime() }
                    .keyboardShortcut(".", modifiers: [.command, .shift])
                    .disabled(!AppStore.shared.running || AppStore.shared.isActing)
                Button("Restart") { AppStore.shared.restartRuntime() }
                    .disabled(!AppStore.shared.running || AppStore.shared.isActing)
                Divider()
                Button("Copy API Config") { AppStore.shared.copyAPIConfig() }
                    .keyboardShortcut("c", modifiers: [.command, .shift])
                Button("Open Dashboard") { AppStore.shared.openDashboard() }
            }
            CommandGroup(after: .windowList) {
                Button("Console") { NotificationCenter.default.post(name: .localAIOpenConsole, object: nil) }
                    .keyboardShortcut("l", modifiers: [.command])
            }
            CommandGroup(replacing: .help) {
                Button("Local AI Help") {
                    let readme = ProjectRoot.resolve().appendingPathComponent("README.md")
                    NSWorkspace.shared.open(readme)
                }
            }
        }
    }
}
