import Foundation

struct APIError: LocalizedError {
    var status: Int
    var message: String
    var errorDescription: String? { message }
}

actor APIClient {
    var baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(host: String = "127.0.0.1", port: Int = 8787) {
        self.baseURL = URL(string: "http://\(host):\(port)")!
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 330
        cfg.timeoutIntervalForResource = 330
        cfg.waitsForConnectivity = false
        self.session = URLSession(configuration: cfg)
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        self.decoder = d
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        self.encoder = e
    }

    func get<T: Decodable>(_ path: String) async throws -> T {
        try await send(path, method: "GET", body: Optional<Data>.none)
    }

    func post<T: Decodable, B: Encodable>(_ path: String, body: B? = nil) async throws -> T {
        let data = try body.map { try encoder.encode($0) }
        return try await send(path, method: "POST", body: data)
    }

    func post<T: Decodable>(_ path: String) async throws -> T {
        try await send(path, method: "POST", body: nil)
    }

    func put<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        try await send(path, method: "PUT", body: try encoder.encode(body))
    }

    func reachable() async -> Bool {
        do {
            let _: HealthResponse = try await get("/api/health")
            return true
        } catch {
            return false
        }
    }

    private func send<T: Decodable>(_ path: String, method: String, body: Data?) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
            throw APIError(status: 0, message: "Invalid path \(path)")
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if status == 0 {
            throw APIError(status: 0, message: "Control plane is not reachable at \(baseURL.absoluteString)")
        }
        if status >= 400 {
            throw APIError(status: status, message: Self.extractMessage(data, status: status))
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError(status: status, message: "Unexpected response: \(error.localizedDescription)")
        }
    }

    private static func extractMessage(_ data: Data, status: Int) -> String {
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = obj["detail"] as? String { return detail }
            if let err = obj["error"] as? [String: Any],
               let msg = err["message"] as? String { return msg }
            if let arr = obj["detail"] as? [[String: Any]] {
                return arr.compactMap { $0["msg"] as? String }.joined(separator: "; ")
            }
        }
        return "HTTP \(status)"
    }
}
