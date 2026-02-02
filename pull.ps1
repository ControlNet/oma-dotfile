param(
  [string]$RepoOwner = $env:REPO_OWNER,
  [string]$RepoName  = $env:REPO_NAME,
  [string]$RepoRev   = $env:REPO_REV,     # branch, tag, or commit hash
  [string]$ConfigDir = $env:CONFIG_DIR,   # optional override
  [switch]$NoBackup
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoOwner)) { $RepoOwner = "ControlNet" }
if ([string]::IsNullOrWhiteSpace($RepoName))  { $RepoName  = "omo-dotfile" }
if ([string]::IsNullOrWhiteSpace($RepoRev))   { $RepoRev   = "master" }

function Timestamp { (Get-Date).ToString("yyyyMMdd-HHmmss") }

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
}

function Unique-BackupPath([string]$BasePath) {
  if (-not (Test-Path $BasePath)) { return $BasePath }
  return "$BasePath-$PID"
}

function Download-File([string]$Url, [string]$OutFile) {
  $headers = @{ "Cache-Control" = "no-cache" }
  if ($PSVersionTable.PSVersion.Major -lt 6) {
    Invoke-WebRequest -Uri $Url -Headers $headers -UseBasicParsing -OutFile $OutFile
  } else {
    Invoke-WebRequest -Uri $Url -Headers $headers -OutFile $OutFile
  }
  if (-not (Test-Path $OutFile) -or ((Get-Item $OutFile).Length -le 0)) {
    throw "Download failed or empty: $Url"
  }
}

function Backup-And-Replace([string]$Src, [string]$Dst, [string]$Ts, [bool]$DoBackup) {
  Ensure-Dir (Split-Path -Parent $Dst)
  if ($DoBackup -and (Test-Path $Dst)) {
    $bak = Unique-BackupPath("$Dst.bak-$Ts")
    Copy-Item $Dst $bak -Force
  }
  Move-Item $Src $Dst -Force
}

function Rename-Json-IfExists([string]$JsonPath, [string]$Ts) {
  if (Test-Path $JsonPath) {
    $bak = Unique-BackupPath("$JsonPath.bak-$Ts")
    Move-Item $JsonPath $bak -Force
  }
}

# User-level config dir on Windows
if ([string]::IsNullOrWhiteSpace($ConfigDir)) {
  $ConfigDir = Join-Path $env:USERPROFILE ".config\opencode"
}
Ensure-Dir $ConfigDir

# Build URLs
$UrlOpenCode = "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$RepoRev/opencode.jsonc"
$UrlOmoc     = "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$RepoRev/oh-my-opencode.jsonc"
$UrlAgents   = "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$RepoRev/_AGENTS.md"

# Plugins (no backup, just replace)
$Plugins = @("gotify-notify.js")
$UrlPluginsBase = "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$RepoRev/plugins"

$ts = Timestamp   # <<< FIX: no parentheses
$tmpDir = Join-Path $env:TEMP ("opencode-pull-" + [Guid]::NewGuid().ToString("N"))
Ensure-Dir $tmpDir

try {
  $tmpOpen   = Join-Path $tmpDir "opencode.jsonc"
  $tmpOmoc   = Join-Path $tmpDir "oh-my-opencode.jsonc"
  $tmpAgents = Join-Path $tmpDir "_AGENTS.md"
  $tmpPluginsDir = Join-Path $tmpDir "plugins"
  Ensure-Dir $tmpPluginsDir

  Write-Host "[1/4] Downloading config files:"
  Write-Host "      - $UrlOpenCode"
  Write-Host "      - $UrlOmoc"
  Write-Host "      - $UrlAgents"

  Download-File $UrlOpenCode $tmpOpen
  Download-File $UrlOmoc     $tmpOmoc
  Download-File $UrlAgents   $tmpAgents

  Write-Host "[2/4] Downloading plugins:"
  foreach ($plugin in $Plugins) {
    $pluginUrl = "$UrlPluginsBase/$plugin"
    Write-Host "      - $pluginUrl"
    Download-File $pluginUrl (Join-Path $tmpPluginsDir $plugin)
  }

  Write-Host "[3/4] Installing to user-level dir: $ConfigDir"
  $doBackup = -not $NoBackup.IsPresent
  Backup-And-Replace $tmpOpen   (Join-Path $ConfigDir "opencode.jsonc") $ts $doBackup
  Backup-And-Replace $tmpOmoc   (Join-Path $ConfigDir "oh-my-opencode.jsonc") $ts $doBackup
  Backup-And-Replace $tmpAgents (Join-Path $ConfigDir "AGENTS.md") $ts $doBackup

  # Install plugins (no backup)
  $pluginsDir = Join-Path $ConfigDir "plugins"
  Ensure-Dir $pluginsDir
  foreach ($plugin in $Plugins) {
    Move-Item (Join-Path $tmpPluginsDir $plugin) (Join-Path $pluginsDir $plugin) -Force
  }

  Write-Host "[4/4] Renaming legacy .json (if exists) so only .jsonc remains active"
  Rename-Json-IfExists (Join-Path $ConfigDir "opencode.json") $ts
  Rename-Json-IfExists (Join-Path $ConfigDir "oh-my-opencode.json") $ts

  Write-Host "Done. Timestamp: $ts"
  if ($doBackup) { Write-Host "Backups: *.bak-$ts" }
}
finally {
  if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
}
