import Cocoa
import ApplicationServices

final class SettingsWindowController: NSObject {
    private var window: NSWindow!
    private var seedField: NSTextField!
    private var urlField: NSTextField!
    private var statusLabel: NSTextField!
    private var accessibilityLabel: NSTextField!

    override init() {
        super.init()
        build()
    }

    private func build() {
        let width: CGFloat = 440

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: width, height: 320),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "TodayH1 設定"
        window.isReleasedWhenClosed = false

        let content = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 320))
        var y: CGFloat = 276

        let intro = NSTextField(wrappingLabelWithString: "Daily NotesのWebアプリの「設定 > 同期」パネルにあるシード文字列を貼り付けてください。")
        intro.frame = NSRect(x: 20, y: y, width: width - 40, height: 36)
        intro.font = .systemFont(ofSize: 12)
        intro.textColor = .secondaryLabelColor
        content.addSubview(intro)
        y -= 46

        let seedLabel = NSTextField(labelWithString: "同期シード:")
        seedLabel.frame = NSRect(x: 20, y: y + 3, width: 90, height: 20)
        content.addSubview(seedLabel)

        seedField = NSTextField(frame: NSRect(x: 112, y: y, width: width - 132, height: 24))
        seedField.placeholderString = "xxxxxxxxxxxxxxxxxxxxxx"
        seedField.stringValue = SettingsStore.shared.seed ?? ""
        content.addSubview(seedField)
        y -= 36

        let urlLabel = NSTextField(labelWithString: "API URL:")
        urlLabel.frame = NSRect(x: 20, y: y + 3, width: 90, height: 20)
        content.addSubview(urlLabel)

        urlField = NSTextField(frame: NSRect(x: 112, y: y, width: width - 132, height: 24))
        urlField.stringValue = SettingsStore.shared.apiBaseURL
        content.addSubview(urlField)
        y -= 44

        let saveButton = NSButton(title: "保存", target: self, action: #selector(saveTapped))
        saveButton.frame = NSRect(x: width - 100, y: y, width: 80, height: 28)
        saveButton.bezelStyle = .rounded
        saveButton.keyEquivalent = "\r"
        content.addSubview(saveButton)

        statusLabel = NSTextField(labelWithString: "")
        statusLabel.frame = NSRect(x: 20, y: y + 4, width: width - 140, height: 20)
        statusLabel.textColor = .systemGreen
        statusLabel.font = .systemFont(ofSize: 11)
        content.addSubview(statusLabel)
        y -= 50

        let divider = NSBox(frame: NSRect(x: 20, y: y + 30, width: width - 40, height: 1))
        divider.boxType = .separator
        content.addSubview(divider)

        accessibilityLabel = NSTextField(wrappingLabelWithString: "")
        accessibilityLabel.frame = NSRect(x: 20, y: y - 26, width: width - 40, height: 50)
        accessibilityLabel.font = .systemFont(ofSize: 11)
        accessibilityLabel.textColor = .secondaryLabelColor
        content.addSubview(accessibilityLabel)
        y -= 82

        let openAccessibilityButton = NSButton(
            title: "アクセシビリティ設定を開く",
            target: self,
            action: #selector(openAccessibility)
        )
        openAccessibilityButton.frame = NSRect(x: 20, y: y, width: 220, height: 28)
        openAccessibilityButton.bezelStyle = .rounded
        content.addSubview(openAccessibilityButton)

        window.contentView = content
    }

    private func accessibilityStatusText() -> String {
        AXIsProcessTrusted()
            ? "アクセシビリティ権限: 許可済み。\u{2318}\u{2318}(Commandキーを素早く2回)で書き込みパネルを呼び出せます。"
            : "アクセシビリティ権限: 未許可。\u{2318}\u{2318}のホットキーを使うには、下のボタンからこのアプリを許可してください。"
    }

    @objc private func saveTapped() {
        let seed = seedField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let url = urlField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        SettingsStore.shared.seed = seed
        SettingsStore.shared.apiBaseURL = url.isEmpty ? SettingsStore.shared.defaultBaseURL : url
        statusLabel.stringValue = "保存しました"
    }

    @objc private func openAccessibility() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!
        NSWorkspace.shared.open(url)
    }

    func show() {
        statusLabel.stringValue = ""
        accessibilityLabel.stringValue = accessibilityStatusText()
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
