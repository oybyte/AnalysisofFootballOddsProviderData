param(
    [switch]$InstallSkills
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SkillSource = Join-Path $ProjectRoot "integrations\skills\football-odds-journal"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & py -3.11 -m venv (Join-Path $ProjectRoot ".venv")
}
& $VenvPython -m pip install -e "${ProjectRoot}[dev]"
& $VenvPython -m odds_journal build-index

if ($InstallSkills) {
    $CodexRoot = Join-Path $env:USERPROFILE ".codex\skills"
    $WorkBuddyPreferred = Join-Path $env:USERPROFILE ".workbuddy\skills"
    $WorkBuddyFallback = Join-Path $env:USERPROFILE ".codebuddy\skills"
    $WorkBuddyRoot = if (Test-Path -LiteralPath $WorkBuddyPreferred) {
        $WorkBuddyPreferred
    } else {
        $WorkBuddyFallback
    }
    foreach ($Root in @($CodexRoot, $WorkBuddyRoot)) {
        $Target = Join-Path $Root "football-odds-journal"
        New-Item -ItemType Directory -Path $Target -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $SkillSource "SKILL.md") -Destination $Target -Force
        if (Test-Path -LiteralPath (Join-Path $SkillSource "agents")) {
            $AgentTarget = Join-Path $Target "agents"
            New-Item -ItemType Directory -Path $AgentTarget -Force | Out-Null
            Copy-Item -Path (Join-Path $SkillSource "agents\*") -Destination $AgentTarget -Recurse -Force
        }
    }

    $Dist = Join-Path $ProjectRoot "dist"
    New-Item -ItemType Directory -Path $Dist -Force | Out-Null
    $ZipPath = Join-Path $Dist "football-odds-journal.zip"
    $SkillPath = Join-Path $Dist "football-odds-journal.skill"
    Compress-Archive -Path (Join-Path $SkillSource "*") -DestinationPath $ZipPath -Force
    Move-Item -LiteralPath $ZipPath -Destination $SkillPath -Force
    Write-Output "telosWork Skill 安装包：$SkillPath"
}

& $VenvPython -m odds_journal agent doctor
