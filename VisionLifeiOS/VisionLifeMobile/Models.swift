import Foundation

struct DashboardSnapshot: Codable {
    let identity: DashboardIdentityPayload
    let selectedDay: String
    let slices: [TimeSlicePayload]
    let groups: [TrackerGroupPayload]
    let tasks: [String]
    let dayArtifacts: [ArtifactPayload]
    let todoTypes: [String]
    let timePresets: [String]
}

struct DashboardIdentityPayload: Codable {
    let inscription: String
    let affirmation: String
    let rotatingPhrase: String
    let backgroundCaption: String
    let backgroundImageUrl: String
}

struct TimeSlicePayload: Codable, Identifiable, Hashable {
    let key: String
    let label: String
    let mode: String
    let kind: String
    let days: [String]
    let widthUnits: Double

    var id: String { key }
}

struct TrackerGroupPayload: Codable, Identifiable {
    let id: String
    let label: String
    let color: String
    let rows: [TrackerRowPayload]
}

struct TrackerRowPayload: Codable, Identifiable {
    let id: String
    let label: String
    let mode: String
    let capacityHours: Double
    let cells: [TrackerCellPayload]
    let artifacts: [ArtifactPayload]
    let todos: [TodoPayload]
}

struct TrackerCellPayload: Codable, Identifiable {
    let key: String
    let status: String
    let statusColor: String
    let note: String
    let summary: String
    let artifactCount: Int
    let todoCount: Int
    let thumbnailUrl: String
    let days: [String]
    let editable: Bool

    var id: String { key }
}

struct ArtifactPayload: Codable, Identifiable {
    let filename: String
    let title: String
    let category: String
    let visualSummary: String
    let personalInsight: String
    let imageUrl: String
    let trackerRow: String
    let trackerRows: [String]
    let linkedDates: [String]
    let futureDates: [String]
    let calendarOffer: Bool
    let calendarTitle: String
    let calendarStart: String
    let calendarEnd: String
    let calendarLocation: String
    let calendarDetails: String
    let actionItems: [String]
    let assignment: AssignmentPayload

    var id: String { filename }
}

struct AssignmentPayload: Codable {
    let rowId: String
    let approved: Bool
    let highlighted: Bool
    let archived: Bool
    let saveForLater: Bool
    let label: String
}

struct TodoPayload: Codable, Identifiable {
    let id: String
    let sourceDay: String
    let text: String
    let type: String
    let estimate: String
    let suggestedRowId: String
    let suggestedDay: String
    let approved: Bool
    let done: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case sourceDay = "source_day"
        case text
        case type
        case estimate
        case suggestedRowId = "suggested_row_id"
        case suggestedDay = "suggested_day"
        case approved
        case done
    }
}

struct UploadResponse: Codable, Identifiable {
    let filename: String
    let path: String
    let bytes: Int

    var id: String { filename + path }
}

struct CellEditorContext: Identifiable {
    let day: String
    let rowID: String
    let rowLabel: String
    let cell: TrackerCellPayload

    var id: String { "\(day)|\(rowID)" }
}

struct ArtifactEditorContext: Identifiable {
    let artifact: ArtifactPayload
    let rowOptions: [TrackerRowOption]

    var id: String { artifact.id }
}

struct TrackerRowOption: Identifiable, Hashable {
    let id: String
    let label: String
}

struct CalendarDraftContext: Identifiable {
    let artifact: ArtifactPayload

    var id: String { artifact.id }
}
