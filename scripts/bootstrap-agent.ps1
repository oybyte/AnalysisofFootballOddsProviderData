param(
    [switch]$SyncAgents,
    [string]$ApprovedBy,
    [switch]$ConfirmSync,
    [string]$WorkBuddySkillRoot
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & py -3.11 -m venv (Join-Path $ProjectRoot ".venv")
}
& $VenvPython -m pip install -e "${ProjectRoot}[dev]"
& $VenvPython -m odds_journal build-index

if ($WorkBuddySkillRoot) {
    & $VenvPython -m odds_journal agent configure --product workbuddy --skill-root $WorkBuddySkillRoot
}

if ($SyncAgents) {
    if (-not $ApprovedBy -or -not $ConfirmSync) {
        throw "同步必须同时提供 -ApprovedBy lcz -ConfirmSync"
    }
    & $VenvPython -m odds_journal agent sync --approved-by $ApprovedBy --confirm-sync
}

& $VenvPython -m odds_journal agent doctor
