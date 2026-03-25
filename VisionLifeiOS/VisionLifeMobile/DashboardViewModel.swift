import Foundation
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class DashboardViewModel: ObservableObject {
    @AppStorage("visionlife.serverURL") var serverURL: String = "http://127.0.0.1:8800"

    @Published var snapshot: DashboardSnapshot?
    @Published var isLoading = false
    @Published var errorMessage = ""
    @Published var selectedDay = DashboardViewModel.todayKey
    @Published var editorContext: CellEditorContext?
    @Published var artifactEditorContext: ArtifactEditorContext?
    @Published var calendarDraftContext: CalendarDraftContext?
    @Published var uploadLog: [String] = []

    private static let todayKey: String = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: Date())
    }()

    private var client: VisionLifeAPIClient {
        VisionLifeAPIClient(baseURLString: serverURL)
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot = try await client.fetchDashboard(day: selectedDay)
            self.snapshot = snapshot
            self.selectedDay = snapshot.selectedDay
            self.errorMessage = ""
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }

    func choose(slice: TimeSlicePayload) async {
        if let firstDay = slice.days.first {
            selectedDay = firstDay
            await refresh()
        }
    }

    func openEditor(row: TrackerRowPayload, cell: TrackerCellPayload) {
        guard cell.editable, let day = cell.days.first else { return }
        editorContext = CellEditorContext(day: day, rowID: row.id, rowLabel: row.label, cell: cell)
    }

    func saveCell(context: CellEditorContext, status: String, note: String) async {
        do {
            try await client.updateCell(day: context.day, rowID: context.rowID, status: status, note: note)
            editorContext = nil
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func openArtifactEditor(_ artifact: ArtifactPayload) {
        let options = (snapshot?.groups ?? [])
            .flatMap(\.rows)
            .map { TrackerRowOption(id: $0.id, label: $0.label) }
        artifactEditorContext = ArtifactEditorContext(artifact: artifact, rowOptions: options)
    }

    func openCalendarDraft(_ artifact: ArtifactPayload) {
        guard artifact.calendarOffer else { return }
        calendarDraftContext = CalendarDraftContext(artifact: artifact)
    }

    func approveArtifact(_ artifact: ArtifactPayload) async {
        await updateArtifactField(filename: artifact.filename, field: "approved", value: true)
    }

    func reassignArtifact(_ artifact: ArtifactPayload, rowID: String) async {
        await updateArtifactField(filename: artifact.filename, field: "row_id", value: rowID)
    }

    func labelArtifact(_ artifact: ArtifactPayload, label: String) async {
        await updateArtifactField(filename: artifact.filename, field: "label", value: label)
    }

    func toggleArtifact(_ artifact: ArtifactPayload, field: String) async {
        do {
            try await client.toggleAssignment(filename: artifact.filename, field: field)
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func uploadFile(data: Data, filename: String, mimeType: String) async {
        do {
            let response = try await client.upload(data: data, filename: filename, mimeType: mimeType)
            uploadLog.insert("Uploaded \(response.filename) (\(response.bytes) bytes)", at: 0)
        } catch {
            errorMessage = error.localizedDescription
            uploadLog.insert("Upload failed: \(filename)", at: 0)
        }
    }

    func uploadPickedPhoto(item: PhotosPickerItem) async {
        do {
            guard let data = try await item.loadTransferable(type: Data.self) else { return }
            let ext = item.supportedContentTypes.first?.preferredFilenameExtension ?? "jpg"
            let filename = "ios-upload-\(timestamp()).\(ext)"
            let mimeType = item.supportedContentTypes.first?.preferredMIMEType ?? "application/octet-stream"
            await uploadFile(data: data, filename: filename, mimeType: mimeType)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func uploadImportedFile(url: URL) async {
        do {
            let access = url.startAccessingSecurityScopedResource()
            defer {
                if access {
                    url.stopAccessingSecurityScopedResource()
                }
            }
            let data = try Data(contentsOf: url)
            let mimeType = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
            await uploadFile(data: data, filename: url.lastPathComponent, mimeType: mimeType)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return formatter.string(from: Date())
    }

    private func updateArtifactField(filename: String, field: String, value: Any) async {
        do {
            try await client.updateAssignment(filename: filename, field: field, value: value)
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
