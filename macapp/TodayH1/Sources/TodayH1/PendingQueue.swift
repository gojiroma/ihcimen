import Foundation

struct PendingEntry: Codable {
    let text: String
    let capturedAt: Date
}

/// Captures that couldn't be pushed (offline, server error, repeated
/// conflicts) are kept here so they aren't lost — flushed on next
/// launch and before every new capture.
final class PendingQueue {
    private let fileURL: URL

    init() {
        let fm = FileManager.default
        let dir = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("TodayH1", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("pending.json")
    }

    func load() -> [PendingEntry] {
        guard let data = try? Data(contentsOf: fileURL) else { return [] }
        return (try? JSONDecoder().decode([PendingEntry].self, from: data)) ?? []
    }

    func save(_ entries: [PendingEntry]) {
        guard let data = try? JSONEncoder().encode(entries) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }

    func append(_ text: String) {
        var entries = load()
        entries.append(PendingEntry(text: text, capturedAt: Date()))
        save(entries)
    }
}
