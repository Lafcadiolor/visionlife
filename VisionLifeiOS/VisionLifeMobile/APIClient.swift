import Foundation

struct VisionLifeAPIClient {
    let baseURL: URL

    init(baseURLString: String) {
        self.baseURL = URL(string: baseURLString) ?? URL(string: "http://127.0.0.1:8800")!
    }

    func fetchDashboard(day: String?) async throws -> DashboardSnapshot {
        var components = URLComponents(url: baseURL.appending(path: "/api/mobile/dashboard"), resolvingAgainstBaseURL: false)!
        if let day, !day.isEmpty {
            components.queryItems = [URLQueryItem(name: "day", value: day)]
        }
        var request = URLRequest(url: components.url!)
        request.httpMethod = "GET"
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(DashboardSnapshot.self, from: data)
    }

    func updateCell(day: String, rowID: String, status: String, note: String) async throws {
        let requestBody: [String: Any] = [
            "kind": "cell",
            "day": day,
            "row_id": rowID,
            "status": status,
            "note": note
        ]
        var request = URLRequest(url: baseURL.appending(path: "/api/state"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: requestBody, options: [])
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
    }

    func updateAssignment(filename: String, field: String, value: Any) async throws {
        let requestBody: [String: Any] = [
            "kind": "assignment",
            "filename": filename,
            "field": field,
            "value": value
        ]
        var request = URLRequest(url: baseURL.appending(path: "/api/state"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: requestBody, options: [])
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
    }

    func toggleAssignment(filename: String, field: String) async throws {
        let requestBody: [String: Any] = [
            "kind": "assignment_toggle",
            "filename": filename,
            "field": field
        ]
        var request = URLRequest(url: baseURL.appending(path: "/api/state"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: requestBody, options: [])
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
    }

    func upload(data: Data, filename: String, mimeType: String) async throws -> UploadResponse {
        var components = URLComponents(url: baseURL.appending(path: "/api/mobile/upload"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "filename", value: filename)]
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.setValue(mimeType, forHTTPHeaderField: "Content-Type")
        request.setValue(filename, forHTTPHeaderField: "X-Filename")
        request.httpBody = data
        let (responseData, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: responseData)
        return try JSONDecoder().decode(UploadResponse.self, from: responseData)
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200...299).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown server error"
            throw NSError(domain: "VisionLifeAPI", code: http.statusCode, userInfo: [
                NSLocalizedDescriptionKey: message
            ])
        }
    }
}
