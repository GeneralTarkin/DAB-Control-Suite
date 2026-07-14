# DAB Control Center – Prototype 0.1

First Windows desktop prototype for the DAB Control Suite.

## Current functionality

- Dark dashboard inspired by the existing DAB web frontend
- Gold accent color
- Connection to a DAB Control Server
- Polling of `/api/status` every five seconds
- Display of station, radiotext, ensemble, frequency, RSSI, SNR and FIC quality
- Stream status indicator

## Build

Requirements:

- Windows 10 or Windows 11
- .NET 8 SDK

Open a terminal in this directory:

```powershell
dotnet restore
dotnet build
dotnet run
```

To create a self-contained Windows executable:

```powershell
dotnet publish -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true
```

The generated executable will be located below:

```text
bin\Release\net8.0-windows\win-x64\publish\
```

## Default server

```text
http://dabserver:8088
```

The address can be changed directly in the application.
