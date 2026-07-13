# API

**DAB Control Suite REST API**  
**Version:** 1.0 (Draft)

## Overview

The REST API is the only supported interface between the DAB Control Server and all clients.

Clients include:

- Web Dashboard
- Web Administration
- Windows Control Center
- Future Linux/macOS clients
- Future mobile applications

All responses use JSON.

---

# Response Format

Successful response

```json
{
  "ok": true,
  "data": {}
}
```

Error response

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Human readable message"
  }
}
```

---

# Public API

## GET /api/status

Returns current playback status.

Returns:

- Power state
- Current station
- Radiotext
- Signal quality
- Stream status

---

## GET /api/stations

Returns all dashboard-enabled stations.

---

## GET /api/history

Returns recently played titles.

---

## POST /api/play/{station}

Starts playback.

---

## POST /api/stop

Stops playback.

---

## GET /api/stream

Returns the audio stream URL.

---

# Administrative API

## GET /api/admin/stations

Returns every scanned station including:

- label
- frequency
- service id
- logo
- dashboard_enabled

---

## POST /api/admin/dashboard/toggle

Enables or disables dashboard visibility.

---

## POST /api/admin/scan/start

Starts a complete DAB scan.

---

## GET /api/admin/scan/status

Returns scan progress.

---

## POST /api/admin/logos/upload

Uploads a PNG station logo.

Requirements:

- PNG only
- Valid image
- Sanitised filename

---

## GET /api/admin/system/status

Returns:

- Server version
- CPU load
- Memory usage
- Disk usage
- Service status

---

## POST /api/admin/backup

Creates a backup.

---

## POST /api/admin/update

Starts a software update.

---

# Versioning

The API follows Semantic Versioning.

Breaking API changes only occur in a new major version.

---

# Authentication

Public endpoints may remain anonymous.

Administrative endpoints will require authentication before the first stable release.

---

Project Founder & Lead Developer

Michael Willner
