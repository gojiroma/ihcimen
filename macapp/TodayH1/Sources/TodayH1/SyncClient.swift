import Foundation
import CryptoKit

struct PullResponse: Decodable {
    let found: Bool
    let ciphertext: String?
    let iv: String?
    let updated_at: String?
}

struct PushResponse: Decodable {
    let applied: Bool
    let updated_at: String
}

/// Same shape as the JSON object index.html's encryptBlob wraps for the
/// "entries" channel: { version, updatedAt, entries, h1Shortcuts }.
struct EntriesBlob: Codable {
    var version: Int
    var updatedAt: String
    var entries: [String: String]
    var h1Shortcuts: String
}

enum SyncError: Error, LocalizedError {
    case invalidBaseURL
    case network(String)
    case pushRejected

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL: return "API URLが不正です"
        case .network(let m): return "通信エラー: \(m)"
        case .pushRejected: return "サーバー側に新しい変更があるため保存できませんでした"
        }
    }
}

extension Date {
    /// Matches JS's `new Date().toISOString()` exactly (millisecond
    /// precision, trailing "Z"), since the server's last-write-wins
    /// comparison and the web app's own writes both use that format.
    var jsISOString: String {
        let df = DateFormatter()
        df.calendar = Calendar(identifier: .gregorian)
        df.locale = Locale(identifier: "en_US_POSIX")
        df.timeZone = TimeZone(identifier: "UTC")
        df.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"
        return df.string(from: self)
    }
}

enum FlexibleISO8601 {
    private static let withFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let withoutFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    /// The server (Python) emits ISO8601 with a "+00:00" offset and
    /// microsecond precision that's omitted when exactly zero — try
    /// both so we never fail to parse a valid response.
    static func date(from s: String) -> Date? {
        withFractional.date(from: s) ?? withoutFractional.date(from: s)
    }
}

final class SyncClient {
    let baseURL: URL
    let syncId: String
    let aesKey: SymmetricKey

    init(baseURLString: String, seedString: String) throws {
        guard let url = URL(string: baseURLString) else { throw SyncError.invalidBaseURL }
        self.baseURL = url
        let seedBytes = try SyncCrypto.seedBytes(from: seedString)
        self.syncId = SyncCrypto.deriveSyncId(seed: seedBytes)
        self.aesKey = SyncCrypto.deriveAesKey(seed: seedBytes)
    }

    static func todayDateKey(now: Date = Date()) -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone.current
        let c = cal.dateComponents([.year, .month, .day], from: now)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }

    private func pull() async throws -> (blob: EntriesBlob, serverUpdatedAt: Date?) {
        var comps = URLComponents(
            url: baseURL.appendingPathComponent("api/pull"),
            resolvingAgainstBaseURL: false
        )!
        comps.queryItems = [URLQueryItem(name: "sync_id", value: syncId)]
        var req = URLRequest(url: comps.url!)
        req.timeoutInterval = 10

        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            throw SyncError.network("pull failed")
        }
        let body = try JSONDecoder().decode(PullResponse.self, from: data)
        guard body.found, let ct = body.ciphertext, let iv = body.iv, let updatedAtStr = body.updated_at else {
            return (EntriesBlob(version: 1, updatedAt: Date().jsISOString, entries: [:], h1Shortcuts: "[]"), nil)
        }
        let plaintext = try SyncCrypto.decrypt(ciphertextB64: ct, ivB64: iv, key: aesKey)
        let blob = try JSONDecoder().decode(EntriesBlob.self, from: plaintext)
        return (blob, FlexibleISO8601.date(from: updatedAtStr))
    }

    private func push(blob: EntriesBlob) async throws -> Bool {
        let plaintext = try JSONEncoder().encode(blob)
        let (ciphertext, iv) = try SyncCrypto.encrypt(plaintext: plaintext, key: aesKey)

        var req = URLRequest(url: baseURL.appendingPathComponent("api/push"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 10
        let payload: [String: Any] = [
            "sync_id": syncId,
            "ciphertext": ciphertext,
            "iv": iv,
            "updated_at": blob.updatedAt,
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            throw SyncError.network("push failed")
        }
        let body = try JSONDecoder().decode(PushResponse.self, from: data)
        return body.applied
    }

    /// Prepends `blockText` to today's entry, exactly like index.html's
    /// insertHistoryBlockIntoCurrent, then pushes the whole (still
    /// end-to-end-encrypted) blob back. If the server rejects the push
    /// because something else changed the data first (e.g. an edit made
    /// in the browser), re-pull the fresh state and retry — this app is
    /// just one more "device" writing to the same sync blob, so it
    /// follows the same last-write-wins protocol the web app uses
    /// between multiple browsers.
    func prependToday(blockText: String, maxAttempts: Int = 3) async throws {
        var lastError: Error = SyncError.pushRejected
        for _ in 0..<maxAttempts {
            do {
                var (blob, serverUpdatedAt) = try await pull()
                let todayKey = Self.todayDateKey()
                let current = blob.entries[todayKey] ?? "# "
                let trimmed = current.trimmingCharacters(in: .whitespacesAndNewlines)
                let base = (trimmed.isEmpty || trimmed == "#") ? "" : current
                let next = base.isEmpty ? blockText : "\(blockText)\n\(base)"
                blob.entries[todayKey] = next
                blob.version = 1

                let now = Date()
                let bumped = serverUpdatedAt.map { max(now, $0.addingTimeInterval(1)) } ?? now
                blob.updatedAt = bumped.jsISOString

                if try await push(blob: blob) {
                    return
                }
                lastError = SyncError.pushRejected
            } catch {
                lastError = error
            }
        }
        throw lastError
    }
}
