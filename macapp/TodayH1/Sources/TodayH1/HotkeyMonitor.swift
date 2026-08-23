import Cocoa
import CoreGraphics

protocol HotkeyMonitorDelegate: AnyObject {
    func hotkeyMonitorDidTriggerDoubleCommand(_ monitor: HotkeyMonitor)
}

/// Detects a standalone double-tap of the Command key (not Command
/// held as a modifier for some other shortcut) anywhere in the system,
/// via a listen-only CGEventTap. Requires Accessibility permission.
final class HotkeyMonitor {
    weak var delegate: HotkeyMonitorDelegate?

    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var lastPureCommandDownAt: CFAbsoluteTime = 0
    private let doubleTapThreshold: CFAbsoluteTime = 0.35

    var isRunning: Bool { eventTap != nil }

    func start() {
        guard eventTap == nil else { return }
        let mask = (1 << CGEventType.flagsChanged.rawValue) | (1 << CGEventType.keyDown.rawValue)

        guard
            let tap = CGEvent.tapCreate(
                tap: .cgSessionEventTap,
                place: .headInsertEventTap,
                options: .listenOnly,
                eventsOfInterest: CGEventMask(mask),
                callback: { _, type, event, refcon in
                    guard let refcon = refcon else { return Unmanaged.passUnretained(event) }
                    let monitor = Unmanaged<HotkeyMonitor>.fromOpaque(refcon).takeUnretainedValue()
                    monitor.handle(type: type, event: event)
                    return Unmanaged.passUnretained(event)
                },
                userInfo: UnsafeMutableRawPointer(Unmanaged.passUnretained(self).toOpaque())
            )
        else {
            return
        }

        eventTap = tap
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        runLoopSource = source
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    func stop() {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        if let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetCurrent(), source, .commonModes)
        }
        eventTap = nil
        runLoopSource = nil
    }

    private func handle(type: CGEventType, event: CGEvent) {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: true) }
            return
        }

        if type == .keyDown {
            // A real key fired while Command is held — that's a
            // shortcut, not a standalone double-tap. Cancel the streak.
            if event.flags.contains(.maskCommand) {
                lastPureCommandDownAt = 0
            }
            return
        }

        guard type == .flagsChanged else { return }
        let flags = event.flags.intersection([.maskCommand, .maskShift, .maskAlternate, .maskControl])

        if flags == .maskCommand {
            let now = CFAbsoluteTimeGetCurrent()
            if lastPureCommandDownAt > 0, now - lastPureCommandDownAt < doubleTapThreshold {
                lastPureCommandDownAt = 0
                DispatchQueue.main.async { [weak self] in
                    guard let self = self else { return }
                    self.delegate?.hotkeyMonitorDidTriggerDoubleCommand(self)
                }
            } else {
                lastPureCommandDownAt = now
            }
        } else if !flags.isEmpty {
            // Some other modifier combo — Command was used for
            // something else, so this can't be a standalone double-tap.
            lastPureCommandDownAt = 0
        }
        // flags.isEmpty means Command (or another tracked modifier) was
        // just released — leave the streak intact for the second tap.
    }
}
