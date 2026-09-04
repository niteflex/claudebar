#Requires -Version 5.1
# claudebar installer for Windows PowerShell.
#   irm https://raw.githubusercontent.com/niteflex/claudebar/main/install.ps1 | iex

$ErrorActionPreference = 'Stop'

$Repo        = 'https://raw.githubusercontent.com/niteflex/claudebar/main'
$InstallDir  = Join-Path $HOME '.claude\claudebar'
$SettingsPath = Join-Path $HOME '.claude\settings.json'

# Windows PowerShell 5.1's -Encoding UTF8 writes a BOM, which breaks JSON parsers.
# Go through .NET so both settings.json and the profile stay BOM-free.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-TextNoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

Write-Host 'Installing claudebar...'

# 0. Locate Python. On Windows `python3` is frequently absent, so prefer whichever resolves.
$PythonCmd = $null
foreach ($candidate in 'python3', 'python') {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $PythonCmd = $candidate; break }
}
if (-not $PythonCmd) {
    Write-Host 'ERROR: no Python interpreter found on PATH.' -ForegroundColor Red
    Write-Host 'Install Python 3.9 or newer from https://www.python.org/downloads/ and'
    # return, not exit: this script is normally run via `irm ... | iex`, where
    # exit would close the user's PowerShell session.
    return
}
Write-Host "  * using $PythonCmd"

# 1. Download status.py
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
$StatusPy = Join-Path $InstallDir 'status.py'
Invoke-WebRequest -Uri "$Repo/status.py" -OutFile $StatusPy -UseBasicParsing
Write-Host "  * status.py -> $InstallDir\"

# 2. Patch settings.json (read-merge-write, so other keys survive)
$SettingsDir = Split-Path $SettingsPath -Parent
New-Item -ItemType Directory -Path $SettingsDir -Force | Out-Null
if (-not (Test-Path $SettingsPath)) { Write-TextNoBom $SettingsPath '{}' }

# Forward slashes on purpose: Git Bash (which Claude Code uses to run statusLine
# commands on Windows when available) mangles unquoted backslashes.
$StatusCommand = "$PythonCmd `$HOME/.claude/claudebar/status.py --statusline"

$settings = Get-Content -Path $SettingsPath -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($settings)) { $settings = '{}' }
$json = $settings | ConvertFrom-Json
if ($null -eq $json) { $json = [PSCustomObject]@{} }

$statusLine = [PSCustomObject]@{ type = 'command'; command = $StatusCommand }
if ($json.PSObject.Properties.Name -contains 'statusLine') {
    $json.statusLine = $statusLine
} else {
    $json | Add-Member -MemberType NoteProperty -Name 'statusLine' -Value $statusLine
}
Write-TextNoBom $SettingsPath (($json | ConvertTo-Json -Depth 20) + "`n")
Write-Host "  * statusLine added to $SettingsPath"

# 3. Patch the PowerShell profile (idempotent, guarded by a # claudebar marker)
# Note: --bar, not --zsh. The --zsh output carries zsh's %{...%} zero-width
# escapes, which PowerShell would print literally; --bar emits plain ANSI.
# PowerShell has no true right-prompt, so the bar goes on the line above.
$ProfileTemplate = @'

# claudebar: Claude Code usage monitor
# unique per-shell ID - inherited by any child process (including claude)
$env:CC_SESSION_ID = "$PID"
function prompt {
    $bar = ""
    try {
        $bar = & __PYTHON__ "$HOME/.claude/claudebar/status.py" --bar 2>$null
    } catch { }
    if ($bar) { Write-Host $bar }
    return "PS " + $(Get-Location) + "> "
}
'@
$ProfileBlock = $ProfileTemplate -replace '__PYTHON__', $PythonCmd

if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    Write-Host "  * created PowerShell profile at $PROFILE"
}

$profileText = Get-Content -Path $PROFILE -Raw -Encoding UTF8
if ($null -eq $profileText) { $profileText = '' }

if ($profileText -match '#\s*claudebar') {
    Write-Host '  * PowerShell profile already patched - skipping'
} elseif ($profileText -match '(?m)^\s*function\s+prompt\b') {
    Write-Host ''
    Write-Host 'WARNING: your PowerShell profile already defines a custom prompt function' -ForegroundColor Yellow
    Write-Host '(oh-my-posh, starship, or your own). PowerShell only honors the LAST' -ForegroundColor Yellow
    Write-Host 'definition, so appending ours would silently disable one of them.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host "Nothing was written to $PROFILE. To wire claudebar in by hand, add this"
    Write-Host 'near the top of your profile:'
    Write-Host ''
    Write-Host '    $env:CC_SESSION_ID = "$PID"'
    Write-Host ''
    Write-Host 'and inside your existing prompt function, before it returns:'
    Write-Host ''
    Write-Host "    `$bar = & $PythonCmd `"`$HOME/.claude/claudebar/status.py`" --bar 2>`$null"
    Write-Host '    if ($bar) { Write-Host $bar }'
    Write-Host ''
} else {
    Write-TextNoBom $PROFILE ($profileText + $ProfileBlock + "`n")
    Write-Host "  * prompt hook added to $PROFILE"
}

Write-Host ''
Write-Host 'Done. Reload your shell:'
Write-Host '  . $PROFILE'
Write-Host ''
Write-Host 'Then start a new Claude Code session - the status bar will appear on the first response.'
