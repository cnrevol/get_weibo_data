param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$CrawlerArgs
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
  python -m venv $Venv
}

& $Python -m pip install -q -r (Join-Path $Root "requirements.txt")
& $Python -m weibo_cdp_crawler.cli @CrawlerArgs
