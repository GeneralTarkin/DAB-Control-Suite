# WINDOWS_CONTROL_CENTER_SPECIFICATION

**Status:** Draft v0.1

## Purpose

The DAB Control Center is the native desktop application for controlling and administering a DAB Control Server.

## Design Goals

- Native Windows application (.NET 8 / WinUI 3)
- Fast startup
- Modern interface
- Full server administration
- No browser required

## Navigation

- Radio
- Administration
- History
- Favorites
- Settings
- Updates
- About

## Radio View

Features:

- Server discovery
- Manual server entry
- Station list
- Station logos
- Radiotext
- Play / Stop
- Volume
- Signal quality
- Stream information

## Administration

Features:

- Start scan
- Station management
- Dashboard selection
- Logo upload
- Test playback
- Service status
- System logs
- Backup
- Restore
- Updates

## Settings

- Server address
- Authentication
- Theme
- Language
- Audio device

## Update Integration

The client checks GitHub Releases for updates and can update itself and trigger server updates through the REST API.

## Communication

The application communicates exclusively with the documented REST API.

No direct filesystem or SSH access is required.

## Planned Technologies

- .NET 8
- WinUI 3
- MVVM
- HttpClient
- Windows App SDK

## Future

- Linux desktop client
- macOS client

Project Founder & Lead Developer

Michael Willner
