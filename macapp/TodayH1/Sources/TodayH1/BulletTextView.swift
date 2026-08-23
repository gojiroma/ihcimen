import Cocoa

/// Ports index.html's applyMarkdownEditorKeydown (h1 "# " / bullet "- "
/// auto-continue, Tab indent, Backspace-out-of-empty-bullet) onto an
/// NSTextView, so the capture panel behaves exactly like the web app's
/// main editor. Alt+Up/Down line reordering is intentionally not
/// ported — it's a general editing feature, not part of "bullet input."
final class BulletTextView: NSTextView {
    var submitHandler: (() -> Void)?
    var cancelHandler: (() -> Void)?

    override func keyDown(with event: NSEvent) {
        if hasMarkedText() {
            super.keyDown(with: event)
            return
        }

        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)

        if event.keyCode == 36, flags.contains(.command) {  // Cmd+Return
            submitHandler?()
            return
        }
        if event.keyCode == 53 {  // Escape
            cancelHandler?()
            return
        }

        if handleMarkdownKeyDown(event) {
            return
        }
        super.keyDown(with: event)
    }

    // MARK: - Ported logic

    private func handleMarkdownKeyDown(_ event: NSEvent) -> Bool {
        let ns = string as NSString
        let sel = selectedRange()

        switch event.keyCode {
        case 48:  // Tab
            handleTab(shift: event.modifierFlags.contains(.shift), ns: ns, sel: sel)
            return true
        case 36:  // Return
            return handleReturn(ns: ns, cursor: sel.location)
        case 51:  // Backspace
            return handleBackspace(ns: ns, cursor: sel.location, hasSelection: sel.length > 0)
        default:
            break
        }

        if event.charactersIgnoringModifiers == "#",
            event.modifierFlags.intersection([.command, .option, .control]).isEmpty
        {
            return handleHashKey(ns: ns, cursor: sel.location)
        }

        return false
    }

    private func currentLineInfo(ns: NSString, cursor: Int) -> (before: String, lines: [String], lineIndex: Int, currentLine: String) {
        let before = ns.substring(to: cursor)
        let lines = before.components(separatedBy: "\n")
        let idx = lines.count - 1
        return (before, lines, idx, lines[idx])
    }

    private func bulletIndent(of line: String) -> String? {
        guard let range = line.range(of: "^(\\s*)- ", options: .regularExpression) else { return nil }
        let matched = String(line[range])
        return String(matched.prefix(matched.count - 2))
    }

    private func isHeadingLine(_ line: String) -> Bool {
        line.range(of: "^#\\s", options: .regularExpression) != nil
    }

    /// Replaces the whole buffer via insertText(_:replacementRange:) so
    /// undo/redo keep working, then repositions the cursor — mirrors
    /// the JS code directly assigning el.value + selectionStart.
    private func setText(_ newText: String, cursor: Int) {
        let full = NSRange(location: 0, length: (string as NSString).length)
        insertText(newText, replacementRange: full)
        setSelectedRange(NSRange(location: cursor, length: 0))
    }

    private func handleReturn(ns: NSString, cursor t: Int) -> Bool {
        let (before, lines, n, o) = currentLineInfo(ns: ns, cursor: t)
        let after = ns.substring(from: t)

        if let indent = bulletIndent(of: o) {
            if o.trimmingCharacters(in: .whitespaces) == "-" {
                var l = lines
                l.removeLast()
                let newText = l.joined(separator: "\n") + "\n" + after
                setText(newText, cursor: t - (o as NSString).length + 1)
            } else {
                let inserted = "\n" + indent + "- "
                setText(before + inserted + after, cursor: t + (inserted as NSString).length)
            }
            return true
        } else if isHeadingLine(o) {
            let titleLen = o.trimmingCharacters(in: .whitespaces).count
            if titleLen > 2 {
                let inserted = "\n- "
                setText(before + inserted + after, cursor: t + (inserted as NSString).length)
            } else {
                var l = lines
                l.removeLast()
                let newText = l.joined(separator: "\n") + "\n" + after
                setText(newText, cursor: t - (o as NSString).length + 1)
            }
            return true
        } else if n > 1 {
            let inserted = "\n\n# "
            setText(before + inserted + after, cursor: t + (inserted as NSString).length)
            return true
        }
        return false
    }

    private func handleBackspace(ns: NSString, cursor t: Int, hasSelection: Bool) -> Bool {
        guard !hasSelection else { return false }
        let (_, lines, _, o) = currentLineInfo(ns: ns, cursor: t)
        guard o.trimmingCharacters(in: .whitespaces) == "-" else { return false }
        var l = lines
        l.removeLast()
        let after = ns.substring(from: t)
        setText(l.joined(separator: "\n") + after, cursor: t - (o as NSString).length)
        return true
    }

    private func handleHashKey(ns: NSString, cursor t: Int) -> Bool {
        let (before, _, _, o) = currentLineInfo(ns: ns, cursor: t)
        guard o.isEmpty else { return false }
        let after = ns.substring(from: t)
        setText(before + "# " + after, cursor: t + 2)
        return true
    }

    private func handleTab(shift: Bool, ns: NSString, sel: NSRange) {
        let t = sel.location
        let end = sel.location + sel.length
        let before = ns.substring(to: t)
        let afterSelEnd = ns.substring(from: end)

        let backslashN = (before as NSString).range(of: "\n", options: .backwards).location
        let lineStart = backslashN == NSNotFound ? 0 : backslashN + 1
        let nextNl = (afterSelEnd as NSString).range(of: "\n").location
        let lineEnd = nextNl == NSNotFound ? ns.length : end + nextNl

        guard lineStart <= lineEnd, lineEnd <= ns.length else { return }
        let block = ns.substring(with: NSRange(location: lineStart, length: lineEnd - lineStart))
        let blockLines = block.components(separatedBy: "\n")

        if shift {
            let dedented = blockLines.map { $0.hasPrefix("  ") ? String($0.dropFirst(2)) : $0 }
            let newText = ns.substring(to: lineStart) + dedented.joined(separator: "\n") + ns.substring(from: lineEnd)
            let removedBeforeCursor = blockLines.filter { $0.hasPrefix("  ") }.count * 2
            setText(newText, cursor: max(lineStart, t - removedBeforeCursor))
        } else {
            let indented = blockLines.map { "  " + $0 }
            let newText = ns.substring(to: lineStart) + indented.joined(separator: "\n") + ns.substring(from: lineEnd)
            setText(newText, cursor: t + 2 * blockLines.count)
        }
    }
}
