import Foundation
import CryptoKit

enum CryptoError: Error, LocalizedError {
    case invalidBase64
    case invalidSeedLength

    var errorDescription: String? {
        switch self {
        case .invalidBase64: return "データの形式が不正です"
        case .invalidSeedLength: return "シードの形式が不正です(16バイトのbase64url文字列である必要があります)"
        }
    }
}

/// Base64 helpers. The web app uses two different encodings:
/// standard base64 (with padding) for ciphertext/iv, and base64url
/// (no padding) for the sync seed itself — see index.html's
/// bytesToBase64 vs bytesToBase64Url.
enum B64 {
    static func decodeStandard(_ s: String) -> Data? {
        Data(base64Encoded: s)
    }

    static func encodeStandard(_ d: Data) -> String {
        d.base64EncodedString()
    }

    static func decodeURLSafe(_ s: String) -> Data? {
        var str = s.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padding = (4 - str.count % 4) % 4
        str += String(repeating: "=", count: padding)
        return Data(base64Encoded: str)
    }
}

/// Mirrors the exact key derivation and AES-GCM scheme used by
/// index.html's sync code (deriveSyncId / deriveAesKey / encryptBlob /
/// decryptBlob), so this app can read and write the same encrypted blob
/// as the web app's "entries" sync channel.
enum SyncCrypto {
    static let infoEntries = "ihcimen-sync-id-entries-v1".data(using: .utf8)!
    static let aesInfo = "ihcimen-aes-key-v1".data(using: .utf8)!
    static let hkdfSalt = "ihcimen-fixed-salt-v1".data(using: .utf8)!

    static func seedBytes(from seed: String) throws -> Data {
        guard let d = B64.decodeURLSafe(seed), d.count == 16 else {
            throw CryptoError.invalidSeedLength
        }
        return d
    }

    static func deriveSyncId(seed: Data) -> String {
        var combined = seed
        combined.append(infoEntries)
        let digest = SHA256.hash(data: combined)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    static func deriveAesKey(seed: Data) -> SymmetricKey {
        let ikm = SymmetricKey(data: seed)
        return HKDF<SHA256>.deriveKey(
            inputKeyMaterial: ikm,
            salt: hkdfSalt,
            info: aesInfo,
            outputByteCount: 32
        )
    }

    /// AES-GCM encrypt. WebCrypto returns ciphertext with the 16-byte
    /// auth tag appended; CryptoKit keeps them separate, so we
    /// concatenate them here to match the wire format the server/web
    /// app expect.
    static func encrypt(plaintext: Data, key: SymmetricKey) throws -> (ciphertext: String, iv: String) {
        let nonce = AES.GCM.Nonce()
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce)
        let combined = sealed.ciphertext + sealed.tag
        return (B64.encodeStandard(combined), B64.encodeStandard(Data(nonce)))
    }

    static func decrypt(ciphertextB64: String, ivB64: String, key: SymmetricKey) throws -> Data {
        guard let cipherAndTag = B64.decodeStandard(ciphertextB64),
            let ivData = B64.decodeStandard(ivB64)
        else {
            throw CryptoError.invalidBase64
        }
        guard cipherAndTag.count > 16 else { throw CryptoError.invalidBase64 }
        let tag = cipherAndTag.suffix(16)
        let body = cipherAndTag.prefix(cipherAndTag.count - 16)
        let nonce = try AES.GCM.Nonce(data: ivData)
        let sealed = try AES.GCM.SealedBox(nonce: nonce, ciphertext: body, tag: tag)
        return try AES.GCM.open(sealed, using: key)
    }
}
