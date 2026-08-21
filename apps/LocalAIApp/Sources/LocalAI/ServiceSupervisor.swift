import AppKit
import Foundation

enum ProjectRoot {
    static let defaultsKey = "projectRoot"

    static func isValid(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.appendingPathComponent("backend/main.py").path)
    }

    static func resolve() -> URL {
        if let stored = UserDefaults.standard.string(forKey: defaultsKey) {
            let url = URL(fileURLWithPath: stored)
            if isValid(url) { return url }
        }
        for url in candidates() where isValid(url) {
            return url
        }
        return candidates().first ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("AI/local-ai-control-center")
    }

    static func locateInteractive() -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = L10n.t("settings.locate_prompt")
        panel.prompt = L10n.t("settings.locate")
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        guard isValid(url) else { return nil }
        UserDefaults.standard.set(url.path, forKey: defaultsKey)
        return url
    }

    private static func candidates() -> [URL] {
        var urls: [URL] = []
        var cursor = Bundle.main.bundleURL
        for _ in 0..<6 {
            cursor.deleteLastPathComponent()
            urls.append(cursor)
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        urls.append(home.appendingPathComponent("AI/local-ai-control-center"))
        return urls
    }
}

enum ServiceSupervisor {
    static let backendLabel = "com.localai.controlcenter.backend"
    static let gatewayLabel = "com.localai.controlcenter.gateway"

    static func uid() -> String {
        String(getuid())
    }

    static func launchctl(_ args: [String]) -> (Int32, String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        let out = Pipe()
        p.standardOutput = out
        p.standardError = out
        do {
            try p.run()
            p.waitUntilExit()
        } catch {
            return (1, error.localizedDescription)
        }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    static func isLoaded(_ label: String) -> Bool {
        launchctl(["list", label]).0 == 0
    }

    @discardableResult
    static func startControlPlane() -> String {
        let domain = "gui/\(uid())"
        var notes: [String] = []
        for label in [backendLabel, gatewayLabel] {
            let (code, out) = launchctl(["kickstart", "-k", "\(domain)/\(label)"])
            if code == 0 {
                notes.append("\(label) kickstarted")
            } else {
                notes.append("\(label) kickstart failed (\(code)): \(out)")
            }
        }
        if !notes.contains(where: { $0.contains("kickstarted") }) {
            notes.append(spawnUvicorn())
        }
        return notes.joined(separator: "\n")
    }

    private static func spawnUvicorn() -> String {
        let root = ProjectRoot.resolve()
        let py = root.appendingPathComponent(".venv/bin/python").path
        guard FileManager.default.isExecutableFile(atPath: py) else {
            return "No venv python at \(py)"
        }
        let logs = root.appendingPathComponent("logs")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        spawn(python: py, module: "backend.main:app", port: 8787, cwd: root, log: logs.appendingPathComponent("backend.log"))
        spawn(python: py, module: "backend.gateway:app", port: 8080, cwd: root, log: logs.appendingPathComponent("gateway.log"))
        return "spawned uvicorn backend:8787 gateway:8080"
    }

    private static func spawn(python: String, module: String, port: Int, cwd: URL, log: URL) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["-m", "uvicorn", module, "--host", "127.0.0.1", "--port", "\(port)"]
        p.currentDirectoryURL = cwd
        p.environment = ProcessInfo.processInfo.environment.merging(["PYTHONUNBUFFERED": "1"]) { _, n in n }
        if let handle = try? FileHandle(forWritingTo: log) {
            p.standardOutput = handle
            p.standardError = handle
        } else {
            FileManager.default.createFile(atPath: log.path, contents: nil)
            let handle = try? FileHandle(forWritingTo: log)
            p.standardOutput = handle
            p.standardError = handle
        }
        do {
            try p.run()
            spawnedLock.lock()
            spawned.append(p)
            spawnedLock.unlock()
        } catch {
            NSLog("spawn \(module) failed: \(error)")
        }
    }

    // MARK: - Session ownership (Quit tears the stack down)

    private static var spawned: [Process] = []
    private static let spawnedLock = NSLock()
    private static var watchdog: Process?
    private static let watchdogLock = NSLock()

    static var keepServicesOnQuit: Bool {
        get { UserDefaults.standard.bool(forKey: "keepServicesOnQuit") }
        set { UserDefaults.standard.set(newValue, forKey: "keepServicesOnQuit") }
    }

    private static var supportDir: URL {
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Local AI", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private static var keepFlagURL: URL {
        supportDir.appendingPathComponent("keep-on-quit.flag")
    }

    static func writeKeepFlag(_ on: Bool) {
        if on {
            FileManager.default.createFile(atPath: keepFlagURL.path, contents: Data("1".utf8))
        } else {
            try? FileManager.default.removeItem(at: keepFlagURL)
        }
    }

    static func syncKeepFlag() {
        writeKeepFlag(keepServicesOnQuit)
    }

    /// Survives Force Quit: when the app PID disappears and the keep flag is
    /// absent, bootout launchd and free 8787 / 8080 / 18080.
    static func startSessionWatchdog() {
        syncKeepFlag()
        let script = supportDir.appendingPathComponent("session-watch.sh")
        let body = """
        #!/bin/sh
        pid="$1"
        flag="$2"
        uid="$(/usr/bin/id -u)"
        while /bin/kill -0 "$pid" 2>/dev/null; do
          /bin/sleep 1
        done
        if [ -f "$flag" ]; then
          exit 0
        fi
        /bin/launchctl bootout "gui/${uid}/com.localai.controlcenter.backend" >/dev/null 2>&1
        /bin/launchctl bootout "gui/${uid}/com.localai.controlcenter.gateway" >/dev/null 2>&1
        for port in 18080 8787 8080; do
          for p in $(/usr/sbin/lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null); do
            /bin/kill -TERM "$p" 2>/dev/null
          done
        done
        /bin/sleep 0.4
        for port in 18080 8787 8080; do
          for p in $(/usr/sbin/lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null); do
            /bin/kill -KILL "$p" 2>/dev/null
          done
        done
        exit 0
        """
        try? body.write(to: script, atomically: true, encoding: .utf8)
        watchdogLock.lock()
        if let old = watchdog, old.isRunning { old.terminate() }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = [script.path, String(getpid()), keepFlagURL.path]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do {
            try p.run()
            watchdog = p
        } catch {
            NSLog("session watchdog failed: \(error)")
        }
        watchdogLock.unlock()
    }

    /// Stop the model, bootout launchd jobs, and free 8787 / 8080 / 18080.
    /// Safe to call from a background thread during applicationShouldTerminate.
    static func shutdownOwnedStack(stopRuntimeFirst: Bool) {
        writeKeepFlag(false)
        watchdogLock.lock()
        if let dog = watchdog, dog.isRunning { dog.terminate() }
        watchdog = nil
        watchdogLock.unlock()

        neutralizeLoginOrphans()
        if stopRuntimeFirst {
            postRuntimeStop()
        }
        let domain = "gui/\(uid())"
        let agents = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents")
        for label in [backendLabel, gatewayLabel] {
            _ = launchctl(["bootout", "\(domain)/\(label)"])
            let plist = agents.appendingPathComponent("\(label).plist")
            if FileManager.default.fileExists(atPath: plist.path) {
                _ = launchctl(["bootout", domain, plist.path])
            }
        }
        spawnedLock.lock()
        let kids = spawned
        spawned = []
        spawnedLock.unlock()
        for p in kids {
            if p.isRunning { p.terminate() }
        }
        for port in [18080, 8787, 8080] {
            killListening(port: port, signal: SIGTERM)
        }
        Thread.sleep(forTimeInterval: 0.35)
        for port in [18080, 8787, 8080] {
            killListening(port: port, signal: SIGKILL)
        }
    }

    /// Existing LaunchAgents were installed with RunAtLoad=true, which starts
    /// 8787 at login without the app. Rewrite to false so login is app-owned.
    static func neutralizeLoginOrphans() {
        let dir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents")
        for label in [backendLabel, gatewayLabel] {
            let url = dir.appendingPathComponent("\(label).plist")
            guard FileManager.default.fileExists(atPath: url.path),
                  let data = try? Data(contentsOf: url),
                  var plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
            else { continue }
            if plist["RunAtLoad"] as? Bool == false { continue }
            plist["RunAtLoad"] = false
            guard let out = try? PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0) else { continue }
            try? out.write(to: url)
        }
    }

    private static func postRuntimeStop() {
        guard let url = URL(string: "http://127.0.0.1:8787/api/runtime/stop") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 3
        let sem = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { _, _, _ in sem.signal() }.resume()
        _ = sem.wait(timeout: .now() + 3.2)
    }

    private static func killListening(port: Int, signal: Int32) {
        for pid in listeningPIDs(port: port) where pid > 1 {
            kill(pid, signal)
        }
    }

    private static func listeningPIDs(port: Int) -> [pid_t] {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        p.arguments = ["-nP", "-iTCP:\(port)", "-sTCP:LISTEN", "-t"]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = Pipe()
        do { try p.run() } catch { return [] }
        p.waitUntilExit()
        let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return text.split { $0.isNewline || $0.isWhitespace }.compactMap { pid_t($0) }
    }
}
