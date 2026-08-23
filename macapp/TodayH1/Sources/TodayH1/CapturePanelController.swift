import Cocoa

/// The floating "quick capture" panel shown on the Cmd-Cmd hotkey.
/// Uses .nonactivatingPanel so it can accept keyboard input without
/// stealing focus (Dock/menu bar) from whatever app was frontmost.
final class CapturePanelController: NSObject, NSWindowDelegate {
    var onSubmit: ((String) -> Void)?

    private var panel: NSPanel!
    private var textView: BulletTextView!
    private var scrollView: NSScrollView!

    override init() {
        super.init()
        buildPanel()
    }

    private func buildPanel() {
        let width: CGFloat = 480
        let height: CGFloat = 220

        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: width, height: height),
            styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.delegate = self

        let content = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        content.wantsLayer = true
        content.layer?.cornerRadius = 12
        content.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor

        scrollView = NSScrollView(frame: NSRect(x: 16, y: 40, width: width - 32, height: height - 56))
        scrollView.autoresizingMask = [.width, .height]
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .noBorder
        scrollView.drawsBackground = false

        textView = BulletTextView(frame: scrollView.bounds)
        textView.minSize = NSSize(width: 0, height: scrollView.bounds.height)
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.font = NSFont.systemFont(ofSize: 15)
        textView.isRichText = false
        textView.allowsUndo = true
        textView.textContainerInset = NSSize(width: 8, height: 8)
        textView.drawsBackground = false
        textView.submitHandler = { [weak self] in self?.submit() }
        textView.cancelHandler = { [weak self] in self?.cancel() }
        scrollView.documentView = textView

        let hint = NSTextField(labelWithString: "\u{2318}Return で保存 ・ Esc でキャンセル")
        hint.frame = NSRect(x: 16, y: 12, width: width - 32, height: 18)
        hint.font = NSFont.systemFont(ofSize: 11)
        hint.textColor = .secondaryLabelColor
        hint.autoresizingMask = [.width]

        content.addSubview(scrollView)
        content.addSubview(hint)
        panel.contentView = content
    }

    func show() {
        resetText()
        centerOnActiveScreen()
        panel.makeKeyAndOrderFront(nil)
        panel.makeFirstResponder(textView)
    }

    private func resetText() {
        textView.string = "# "
        textView.setSelectedRange(NSRange(location: 2, length: 0))
    }

    private func centerOnActiveScreen() {
        guard let screen = NSScreen.main else { return }
        let sf = screen.visibleFrame
        let size = panel.frame.size
        let origin = NSPoint(
            x: sf.midX - size.width / 2,
            y: sf.midY - size.height / 2 + sf.height * 0.15
        )
        panel.setFrameOrigin(origin)
    }

    private func submit() {
        let text = textView.string.trimmingCharacters(in: .newlines)
        let hasTitle = !text.replacingOccurrences(of: "#", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        guard hasTitle else {
            NSSound.beep()
            return
        }
        panel.orderOut(nil)
        onSubmit?(text)
    }

    private func cancel() {
        panel.orderOut(nil)
    }

    func windowDidResignKey(_ notification: Notification) {
        panel.orderOut(nil)
    }
}
