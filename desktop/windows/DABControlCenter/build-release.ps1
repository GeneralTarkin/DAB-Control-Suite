$ErrorActionPreference = "Stop"

dotnet restore
dotnet publish `
  -c Release `
  -r win-x64 `
  --self-contained true `
  -p:PublishSingleFile=true

Write-Host ""
Write-Host "Build finished."
Write-Host "Output: bin\Release\net8.0-windows\win-x64\publish\"
