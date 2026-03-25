# VisionLife Mobile

SwiftUI iOS client for the local VisionLife command desk.

What it does:
- displays the tracker dashboard through the local VisionLife mobile snapshot API
- lets you manually update tracker cell status and notes
- uploads photos, videos, and files to the Google Drive synced inbox by posting them to the local VisionLife server

Important runtime assumption:
- the Python VisionLife server is running on your Mac
- the iOS app connects to that server over HTTP
- the server writes uploads into the Google Drive synced inbox folder

Default simulator URL:
- `http://127.0.0.1:8800`

For a physical iPhone:
- run the server on your Mac
- find your Mac's local IP address
- enter `http://<your-mac-ip>:8800` in the app's Settings tab

Server endpoint contract:
- `GET /api/mobile/dashboard?day=YYYY-MM-DD`
- `POST /api/state`
- `POST /api/mobile/upload?filename=<name>`

This app is designed as a practical v1 shell, not a full replacement for the richer web dashboard yet.
