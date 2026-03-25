import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import EventKit

struct ContentView: View {
    @EnvironmentObject private var viewModel: DashboardViewModel

    var body: some View {
        TabView {
            DashboardScreen()
                .tabItem {
                    Label("Dashboard", systemImage: "square.grid.2x2")
                }

            UploadScreen()
                .tabItem {
                    Label("Upload", systemImage: "square.and.arrow.up")
                }

            SettingsScreen()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
        }
        .task {
            if viewModel.snapshot == nil {
                await viewModel.refresh()
            }
        }
        .sheet(item: $viewModel.editorContext) { context in
            CellEditorSheet(context: context)
        }
        .sheet(item: $viewModel.artifactEditorContext) { context in
            ArtifactEditorSheet(context: context)
        }
        .sheet(item: $viewModel.calendarDraftContext) { context in
            CalendarDraftSheet(context: context)
        }
    }
}

private struct DashboardScreen: View {
    @EnvironmentObject private var viewModel: DashboardViewModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let identity = viewModel.snapshot?.identity {
                        header(identity: identity)
                    }

                    if !viewModel.errorMessage.isEmpty {
                        Text(viewModel.errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    if let snapshot = viewModel.snapshot {
                        sliceRail(snapshot: snapshot)
                        trackerGrid(snapshot: snapshot)
                        dayArtifacts(snapshot: snapshot)
                    } else if viewModel.isLoading {
                        ProgressView("Loading dashboard…")
                            .frame(maxWidth: .infinity, alignment: .center)
                    }
                }
                .padding(20)
            }
            .background(Color(red: 0.93, green: 0.90, blue: 0.84))
            .navigationTitle("VisionLife")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Refresh") {
                        Task { await viewModel.refresh() }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func header(identity: DashboardIdentityPayload) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(identity.inscription)
                .font(.caption)
                .textCase(.uppercase)
                .foregroundStyle(.secondary)
            Text(identity.affirmation)
                .font(.system(size: 34, weight: .semibold, design: .serif))
            Text(identity.rotatingPhrase)
                .font(.headline)
                .foregroundStyle(.green)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    @ViewBuilder
    private func sliceRail(snapshot: DashboardSnapshot) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(snapshot.slices) { slice in
                    Button {
                        Task { await viewModel.choose(slice: slice) }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(slice.label)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(slice.days.first ?? slice.key)
                                .font(.footnote.weight(.semibold))
                                .lineLimit(1)
                        }
                        .padding(12)
                        .frame(width: width(for: slice), alignment: .leading)
                        .background(slice.key == snapshot.selectedDay ? Color.black.opacity(0.85) : Color.white.opacity(0.8))
                        .foregroundStyle(slice.key == snapshot.selectedDay ? Color.white : Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func width(for slice: TimeSlicePayload) -> CGFloat {
        switch slice.mode {
        case "focus": return 180
        case "near": return 110
        case "compressed": return 76
        case "week-band": return 54
        default: return 100
        }
    }

    @ViewBuilder
    private func trackerGrid(snapshot: DashboardSnapshot) -> some View {
        ScrollView(.horizontal, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(snapshot.groups) { group in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(group.label)
                            .font(.headline)
                            .foregroundStyle(Color(hex: group.color))
                        ForEach(group.rows) { row in
                            HStack(alignment: .top, spacing: 10) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(row.label)
                                        .font(.subheadline.weight(.semibold))
                                    if row.mode == "todo" {
                                        Text("Expandable planning lane")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .frame(width: 170, alignment: .leading)

                                ForEach(row.cells) { cell in
                                    Button {
                                        viewModel.openEditor(row: row, cell: cell)
                                    } label: {
                                        TrackerCellView(cell: cell)
                                            .frame(width: width(for: snapshot.slices.first(where: { $0.key == cell.key }) ?? snapshot.slices[0]))
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(!cell.editable)
                                }
                            }
                        }
                    }
                    .padding()
                    .background(Color.white.opacity(0.74), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                }
            }
        }
    }

    @ViewBuilder
    private func dayArtifacts(snapshot: DashboardSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Artifacts")
                .font(.headline)
            if snapshot.dayArtifacts.isEmpty {
                Text("No artifacts attached to this day yet.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(snapshot.dayArtifacts) { artifact in
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .top, spacing: 12) {
                            if let url = URL(string: viewModel.serverURL + artifact.imageUrl), !artifact.imageUrl.isEmpty {
                                AsyncImage(url: url) { image in
                                    image.resizable().scaledToFill()
                                } placeholder: {
                                    Color.gray.opacity(0.15)
                                }
                                .frame(width: 88, height: 88)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                Text(artifact.title)
                                    .font(.subheadline.weight(.semibold))
                                Text(artifact.visualSummary.isEmpty ? artifact.personalInsight : artifact.visualSummary)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(3)
                                Text("Rows: " + (artifact.trackerRows.isEmpty ? artifact.assignment.rowId : artifact.trackerRows.joined(separator: ", ")))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                if !artifact.assignment.label.isEmpty {
                                    Text("Label: \(artifact.assignment.label)")
                                        .font(.caption)
                                }
                                if !artifact.actionItems.isEmpty {
                                    Text("Action: \(artifact.actionItems.joined(separator: ", "))")
                                        .font(.caption)
                                }
                            }
                        }
                        HStack(spacing: 8) {
                            Button("Approve") {
                                Task { await viewModel.approveArtifact(artifact) }
                            }
                            .buttonStyle(.borderedProminent)

                            if artifact.calendarOffer {
                                Button("Calendar") {
                                    viewModel.openCalendarDraft(artifact)
                                }
                                .buttonStyle(.bordered)
                            }

                            Button("Edit") {
                                viewModel.openArtifactEditor(artifact)
                            }
                            .buttonStyle(.bordered)

                            Button(artifact.assignment.highlighted ? "Unhighlight" : "Highlight") {
                                Task { await viewModel.toggleArtifact(artifact, field: "highlighted") }
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                    .padding()
                    .background(Color.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
            }
        }
    }
}

@MainActor
private final class CalendarDraftStore: ObservableObject {
    @Published var saveMessage = ""

    private let eventStore = EKEventStore()

    func save(title: String, start: Date, end: Date, location: String, notes: String) async {
        do {
            try await requestAccess()
            let event = EKEvent(eventStore: eventStore)
            event.title = title
            event.startDate = start
            event.endDate = end
            event.location = location
            event.notes = notes
            event.calendar = eventStore.defaultCalendarForNewEvents
            try eventStore.save(event, span: .thisEvent)
            saveMessage = "Saved to Calendar"
        } catch {
            saveMessage = error.localizedDescription
        }
    }

    private func requestAccess() async throws {
        if #available(iOS 17.0, *) {
            let granted = try await eventStore.requestFullAccessToEvents()
            if !granted {
                throw NSError(domain: "VisionLifeCalendar", code: 1, userInfo: [
                    NSLocalizedDescriptionKey: "Calendar access was denied."
                ])
            }
        } else {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                eventStore.requestAccess(to: .event) { granted, error in
                    if let error {
                        continuation.resume(throwing: error)
                    } else if granted {
                        continuation.resume()
                    } else {
                        continuation.resume(throwing: NSError(domain: "VisionLifeCalendar", code: 1, userInfo: [
                            NSLocalizedDescriptionKey: "Calendar access was denied."
                        ]))
                    }
                }
            }
        }
    }
}

private struct CalendarDraftSheet: View {
    @Environment(\.dismiss) private var dismiss

    let context: CalendarDraftContext

    @StateObject private var store = CalendarDraftStore()
    @State private var title: String
    @State private var start: Date
    @State private var end: Date
    @State private var location: String
    @State private var notes: String

    init(context: CalendarDraftContext) {
        self.context = context
        let artifact = context.artifact
        _title = State(initialValue: artifact.calendarTitle.isEmpty ? artifact.title : artifact.calendarTitle)
        _start = State(initialValue: Self.parseDate(artifact.calendarStart) ?? Date())
        _end = State(initialValue: Self.parseDate(artifact.calendarEnd) ?? (Self.parseDate(artifact.calendarStart)?.addingTimeInterval(3600) ?? Date().addingTimeInterval(3600)))
        _location = State(initialValue: artifact.calendarLocation)
        _notes = State(initialValue: artifact.calendarDetails)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Event") {
                    TextField("Title", text: $title)
                    DatePicker("Start", selection: $start)
                    DatePicker("End", selection: $end)
                    TextField("Location", text: $location)
                }

                Section("Notes") {
                    TextEditor(text: $notes)
                        .frame(minHeight: 140)
                }

                if !store.saveMessage.isEmpty {
                    Section {
                        Text(store.saveMessage)
                            .foregroundStyle(store.saveMessage == "Saved to Calendar" ? .green : .red)
                    }
                }
            }
            .navigationTitle("Calendar Event")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") {
                        Task {
                            await store.save(title: title, start: start, end: end, location: location, notes: notes)
                        }
                    }
                }
            }
        }
    }

    private static func parseDate(_ value: String) -> Date? {
        guard !value.isEmpty else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = formatter.date(from: value) {
            return parsed
        }
        formatter.formatOptions = [.withInternetDateTime]
        if let parsed = formatter.date(from: value) {
            return parsed
        }
        let fallback = DateFormatter()
        fallback.locale = Locale(identifier: "en_US_POSIX")
        fallback.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return fallback.date(from: value)
    }
}

private struct ArtifactEditorSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var viewModel: DashboardViewModel

    let context: ArtifactEditorContext

    @State private var selectedRowID: String
    @State private var label: String

    init(context: ArtifactEditorContext) {
        self.context = context
        _selectedRowID = State(initialValue: context.artifact.assignment.rowId)
        _label = State(initialValue: context.artifact.assignment.label)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Artifact") {
                    Text(context.artifact.title)
                        .font(.headline)
                    Text(context.artifact.category)
                        .foregroundStyle(.secondary)
                    if !context.artifact.imageUrl.isEmpty,
                       let url = URL(string: viewModel.serverURL + context.artifact.imageUrl) {
                        AsyncImage(url: url) { image in
                            image.resizable().scaledToFill()
                        } placeholder: {
                            Color.gray.opacity(0.15)
                        }
                        .frame(height: 180)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                }

                Section("Reassign") {
                    Picker("Tracker row", selection: $selectedRowID) {
                        ForEach(context.rowOptions) { option in
                            Text(option.label).tag(option.id)
                        }
                    }
                    Button("Save row") {
                        Task {
                            await viewModel.reassignArtifact(context.artifact, rowID: selectedRowID)
                        }
                    }
                }

                Section("Label") {
                    TextField("Short label", text: $label)
                    Button("Save label") {
                        Task {
                            await viewModel.labelArtifact(context.artifact, label: label)
                        }
                    }
                }

                Section("Actions") {
                    Button(context.artifact.assignment.highlighted ? "Unhighlight" : "Highlight") {
                        Task { await viewModel.toggleArtifact(context.artifact, field: "highlighted") }
                    }
                    Button(context.artifact.assignment.saveForLater ? "Remove Save For Later" : "Save For Later") {
                        Task { await viewModel.toggleArtifact(context.artifact, field: "save_for_later") }
                    }
                    Button(context.artifact.assignment.archived ? "Unarchive" : "Archive") {
                        Task { await viewModel.toggleArtifact(context.artifact, field: "archived") }
                    }
                    Button("Approve") {
                        Task { await viewModel.approveArtifact(context.artifact) }
                    }
                }
            }
            .navigationTitle("Artifact")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

private struct TrackerCellView: View {
    let cell: TrackerCellPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let url = URL(string: cell.thumbnailUrl), !cell.thumbnailUrl.isEmpty {
                AsyncImage(url: url) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    Color.clear
                }
                .frame(height: 44)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            Text(cell.summary.isEmpty ? " " : cell.summary)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
            if !cell.note.isEmpty {
                Text(cell.note)
                    .font(.caption2)
                    .lineLimit(2)
            }
            HStack(spacing: 6) {
                if cell.artifactCount > 0 {
                    Label("\(cell.artifactCount)", systemImage: "photo")
                        .font(.caption2)
                }
                if cell.todoCount > 0 {
                    Label("\(cell.todoCount)", systemImage: "checklist")
                        .font(.caption2)
                }
            }
            .foregroundStyle(.secondary)
        }
        .padding(8)
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .background(Color(hex: cell.statusColor), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(.black.opacity(cell.editable ? 0.1 : 0.04), lineWidth: 1)
        )
    }
}

private struct CellEditorSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var viewModel: DashboardViewModel

    let context: CellEditorContext
    @State private var status: String
    @State private var note: String

    init(context: CellEditorContext) {
        self.context = context
        _status = State(initialValue: context.cell.status)
        _note = State(initialValue: context.cell.note)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Status") {
                    Picker("Status", selection: $status) {
                        Text("Unset").tag("")
                        Text("Done").tag("done")
                        Text("Excused").tag("excused")
                        Text("Oops").tag("oops")
                        Text("Missed").tag("missed")
                    }
                    .pickerStyle(.segmented)
                }

                Section("Cell note") {
                    TextEditor(text: $note)
                        .frame(minHeight: 140)
                }
            }
            .navigationTitle(context.rowLabel)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") {
                        Task {
                            await viewModel.saveCell(context: context, status: status, note: note)
                            dismiss()
                        }
                    }
                }
            }
        }
    }
}

private struct UploadScreen: View {
    @EnvironmentObject private var viewModel: DashboardViewModel
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var showingFileImporter = false

    var body: some View {
        NavigationStack {
            List {
                Section("Google Drive inbox") {
                    Text("Files uploaded here are posted to the local VisionLife server, which saves them into the synced Google Drive inbox on your Mac.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)

                    PhotosPicker(selection: $photoItems, maxSelectionCount: 10, matching: .any(of: [.images, .videos])) {
                        Label("Pick Photos or Videos", systemImage: "photo.on.rectangle.angled")
                    }

                    Button {
                        showingFileImporter = true
                    } label: {
                        Label("Import Files", systemImage: "folder.badge.plus")
                    }
                }

                Section("Recent uploads") {
                    if viewModel.uploadLog.isEmpty {
                        Text("Nothing uploaded yet.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(viewModel.uploadLog, id: \.self) { entry in
                            Text(entry)
                        }
                    }
                }
            }
            .navigationTitle("Upload")
        }
        .onChange(of: photoItems) { _, items in
            Task {
                for item in items {
                    await viewModel.uploadPickedPhoto(item: item)
                }
                photoItems = []
            }
        }
        .fileImporter(
            isPresented: $showingFileImporter,
            allowedContentTypes: [.image, .movie, .pdf, .data],
            allowsMultipleSelection: true
        ) { result in
            switch result {
            case .success(let urls):
                Task {
                    for url in urls {
                        await viewModel.uploadImportedFile(url: url)
                    }
                }
            case .failure(let error):
                viewModel.errorMessage = error.localizedDescription
            }
        }
    }
}

private struct SettingsScreen: View {
    @EnvironmentObject private var viewModel: DashboardViewModel

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("Server URL", text: $viewModel.serverURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Use `http://127.0.0.1:8800 in the simulator. On a physical iPhone, replace that with your Mac's local network address and the same port.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button("Refresh Dashboard") {
                        Task { await viewModel.refresh() }
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}

private extension Color {
    init(hex: String) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch cleaned.count {
        case 8:
            (a, r, g, b) = (int >> 24, int >> 16 & 0xff, int >> 8 & 0xff, int & 0xff)
        default:
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xff, int & 0xff)
        }

        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}
