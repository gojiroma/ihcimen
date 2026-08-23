import Cocoa
import ApplicationServices
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let hotkeyMonitor = HotkeyMonitor()
    private var capturePanelController: CapturePanelController?
    private var settingsWindowController: SettingsWindowController?
    private let pendingQueue = PendingQueue()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupStatusItem()
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        hotkeyMonitor.delegate = self
        requestAccessibilityIfNeeded()
        hotkeyMonitor.start()

        Task { await flushPendingQueue(announce: true) }
    }

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "square.and.pencil", accessibilityDescription: "TodayH1")
        }

        let menu = NSMenu()
        let captureItem = NSMenuItem(title: "今日のページに書き込む", action: #selector(showCapturePanel), keyEquivalent: "")
        menu.addItem(captureItem)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "設定…", action: #selector(showSettings), keyEquivalent: ","))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "終了", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        menu.items.forEach { $0.target = self }
        statusItem.menu = menu
    }

    private func requestAccessibilityIfNeeded() {
        let options: NSDictionary = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        _ = AXIsProcessTrustedWithOptions(options)
    }

    @objc private func showCapturePanel() {
        guard SettingsStore.shared.isConfigured else {
            showSettings()
            return
        }
        if capturePanelController == nil {
            let controller = CapturePanelController()
            controller.onSubmit = { [weak self] text in
                self?.handleSubmit(text: text)
            }
            capturePanelController = controller
        }
        capturePanelController?.show()
    }

    @objc private func showSettings() {
        if settingsWindowController == nil {
            settingsWindowController = SettingsWindowController()
        }
        settingsWindowController?.show()
    }

    private func handleSubmit(text: String) {
        Task {
            await submit(text: text)
        }
    }

    private func submit(text: String) async {
        guard let seed = SettingsStore.shared.seed, !seed.isEmpty else {
            notify(title: "TodayH1", body: "設定でシードを登録してください")
            return
        }
        do {
            let client = try SyncClient(baseURLString: SettingsStore.shared.apiBaseURL, seedString: seed)
            try await client.prependToday(blockText: text)
            notify(title: "今日のページに追加しました", body: firstLine(of: text))
            await flushPendingQueue(announce: true)
        } catch {
            pendingQueue.append(text)
            notify(title: "保存を保留しました", body: "オフラインか通信エラーです。次回接続時に自動で再送します")
        }
    }

    private func flushPendingQueue(announce: Bool) async {
        let entries = pendingQueue.load()
        guard !entries.isEmpty else { return }
        guard let seed = SettingsStore.shared.seed, !seed.isEmpty else { return }
        guard let client = try? SyncClient(baseURLString: SettingsStore.shared.apiBaseURL, seedString: seed) else { return }

        var remaining: [PendingEntry] = []
        for entry in entries {
            do {
                try await client.prependToday(blockText: entry.text)
            } catch {
                remaining.append(entry)
            }
        }
        pendingQueue.save(remaining)

        let flushedCount = entries.count - remaining.count
        if announce, flushedCount > 0 {
            notify(title: "保留していた内容を保存しました", body: "\(flushedCount)件")
        }
    }

    private func firstLine(of text: String) -> String {
        text.components(separatedBy: "\n").first?.replacingOccurrences(of: "# ", with: "") ?? ""
    }

    private func notify(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}

extension AppDelegate: HotkeyMonitorDelegate {
    func hotkeyMonitorDidTriggerDoubleCommand(_ monitor: HotkeyMonitor) {
        showCapturePanel()
    }
}
