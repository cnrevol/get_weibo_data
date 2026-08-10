param(
  [int]$Port = 9222,
  [string]$ProfileDir = "$PSScriptRoot\..\chrome-profile"
)

$ErrorActionPreference = "Stop"

$chromeCandidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $chrome) {
  throw "Chrome executable was not found. Install Chrome or pass a custom command manually."
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

Write-Host "Starting Chrome CDP on port $Port"
Write-Host "Profile: $ProfileDir"

Start-Process -FilePath $chrome -ArgumentList @(
  "--remote-debugging-port=$Port",
  "--user-data-dir=$ProfileDir",
  "--no-first-run",
  "--no-default-browser-check",
  "https://weibo.com/"
)
