import Foundation
import Security

/// Minimal Keychain wrapper — the sync seed is effectively the
/// encryption key for the user's whole journal, so it belongs in the
/// Keychain rather than UserDefaults.
enum Keychain {
    static let service = "com.gojiroma.ihcimen.TodayH1.syncSeed"

    static func save(_ value: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
        ]
        SecItemDelete(query as CFDictionary)
        var attributes = query
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(attributes as CFDictionary, nil)
    }

    static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

final class SettingsStore {
    static let shared = SettingsStore()

    private let defaults = UserDefaults.standard
    private let apiBaseURLKey = "apiBaseURL"
    let defaultBaseURL = "https://ihcimen.vercel.app"

    var seed: String? {
        get { Keychain.load() }
        set {
            if let v = newValue, !v.isEmpty {
                Keychain.save(v)
            } else {
                Keychain.delete()
            }
        }
    }

    var apiBaseURL: String {
        get { defaults.string(forKey: apiBaseURLKey) ?? defaultBaseURL }
        set { defaults.set(newValue, forKey: apiBaseURLKey) }
    }

    var isConfigured: Bool {
        guard let s = seed, !s.isEmpty else { return false }
        return true
    }
}
