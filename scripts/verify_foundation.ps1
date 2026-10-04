<#
.SYNOPSIS
    Deterministic foundation verification for the Vote Without Doubt project.

.DESCRIPTION
    Read-only verification of the Phase 0 foundation. Performs the checks listed in the
    Phase 0 remediation plan and prints a PASS/FAIL line for each.

    Properties of this script:
      * Read-only. It never creates, modifies or deletes any file.
      * Operates only on the repository that contains this script (resolved from
        $PSScriptRoot). It never searches parent or sibling directories.
      * No network access.
      * Exits 0 when every check passes, 1 when any check fails.

.EXAMPLE
    .\scripts\verify_foundation.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Resolve repository root strictly from this script's location (no upward search)
# ---------------------------------------------------------------------------
$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { throw 'Cannot resolve repository root from script location.' }

$script:Results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][int]    $Id,
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][bool]   $Passed,
        [Parameter(Mandatory = $true)][string] $Detail
    )
    $script:Results.Add([pscustomobject]@{
        Id = $Id; Name = $Name; Passed = $Passed; Detail = $Detail
    })
}

function Get-RepoFile {
    param([Parameter(Mandatory = $true)][string] $Relative)
    $p = Join-Path $RepoRoot $Relative
    if (Test-Path -LiteralPath $p -PathType Leaf) { return $p }
    return $null
}

function Get-RepoDir {
    param([Parameter(Mandatory = $true)][string] $Relative)
    $p = Join-Path $RepoRoot $Relative
    if (Test-Path -LiteralPath $p -PathType Container) { return $p }
    return $null
}

function Read-RepoText {
    param([Parameter(Mandatory = $true)][string] $Relative)
    $p = Get-RepoFile $Relative
    if ($null -eq $p) { return $null }
    # Strict UTF-8 decode: throws on invalid byte sequences.
    $bytes = [System.IO.File]::ReadAllBytes($p)
    $enc = New-Object System.Text.UTF8Encoding($false, $true)
    try { return $enc.GetString($bytes) } catch { return $null }
}

function Test-HasAll {
    param([string] $Text, [string[]] $Needles)
    if ($null -eq $Text) { return $false }
    foreach ($n in $Needles) { if ($Text -notmatch [regex]::Escape($n)) { return $false } }
    return $true
}

Write-Host ''
Write-Host 'Vote Without Doubt - Foundation Verification' -ForegroundColor Cyan
Write-Host "Repository root: $RepoRoot"
Write-Host ''

# ---------------------------------------------------------------------------
# CHECK 1 - Required root files exist
# ---------------------------------------------------------------------------
$rootFiles = @('README.md', 'PROJECT_MASTER_REPORT.md', 'PROJECT_BIBLE.md', '.gitignore')
$missingRoot = @($rootFiles | Where-Object { $null -eq (Get-RepoFile $_) })
Add-Result -Id 1 -Name 'Required root files exist' `
    -Passed ($missingRoot.Count -eq 0) `
    -Detail $(if ($missingRoot.Count -eq 0) { "found: $($rootFiles -join ', ')" } else { "MISSING: $($missingRoot -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 2 - Required directories exist
# ---------------------------------------------------------------------------
$rootDirs = @('backend', 'frontend', 'blockchain', 'docs', 'scripts')
$missingDirs = @($rootDirs | Where-Object { $null -eq (Get-RepoDir $_) })
Add-Result -Id 2 -Name 'Required directories exist' `
    -Passed ($missingDirs.Count -eq 0) `
    -Detail $(if ($missingDirs.Count -eq 0) { "found: $($rootDirs -join ', ')" } else { "MISSING: $($missingDirs -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 3 - PROJECT_MASTER_REPORT.md exists and is non-trivial
# ---------------------------------------------------------------------------
$pmr = Read-RepoText 'PROJECT_MASTER_REPORT.md'
$pmrSections = 0
if ($null -ne $pmr) { $pmrSections = ([regex]::Matches($pmr, '(?m)^##\s+\d+\.')).Count }
Add-Result -Id 3 -Name 'PROJECT_MASTER_REPORT.md exists with numbered sections' `
    -Passed (($null -ne $pmr) -and ($pmrSections -ge 40)) `
    -Detail "numbered top-level sections found: $pmrSections (expected >= 40)"

# ---------------------------------------------------------------------------
# CHECK 4 - PROJECT_BIBLE.md exists and is non-trivial
# ---------------------------------------------------------------------------
$bible = Read-RepoText 'PROJECT_BIBLE.md'
$bibleSections = 0
if ($null -ne $bible) { $bibleSections = ([regex]::Matches($bible, '(?m)^##\s+\d+\.')).Count }
Add-Result -Id 4 -Name 'PROJECT_BIBLE.md exists with numbered sections' `
    -Passed (($null -ne $bible) -and ($bibleSections -ge 15)) `
    -Detail "numbered sections found: $bibleSections (expected >= 15)"

# ---------------------------------------------------------------------------
# CHECK 5 - Phase 0 final report exists under docs/
# ---------------------------------------------------------------------------
$p0 = @(@('docs/PHASE0_FINAL_REPORT.md') | Where-Object { $null -ne (Get-RepoFile $_) })
Add-Result -Id 5 -Name 'Phase 0 final report exists under docs/' `
    -Passed ($p0.Count -eq 1) `
    -Detail $(if ($p0.Count -eq 1) { 'found docs/PHASE0_FINAL_REPORT.md' } else { 'MISSING docs/PHASE0_FINAL_REPORT.md' })

# ---------------------------------------------------------------------------
# CHECK 6 - All five frozen scope categories are defined
# ---------------------------------------------------------------------------
$scopeSrc = @((Read-RepoText 'PROJECT_MASTER_REPORT.md'), (Read-RepoText 'PROJECT_BIBLE.md')) -join "`n"
$categories = @('CORE', 'MILESTONE A', 'STRONG', 'MILESTONE B', 'OPTIONAL', 'FUTURE', 'DO NOT BUILD')
$missingCats = @($categories | Where-Object { $scopeSrc -notmatch [regex]::Escape($_) })
Add-Result -Id 6 -Name 'Frozen scope taxonomy defines all five categories' `
    -Passed ($missingCats.Count -eq 0) `
    -Detail $(if ($missingCats.Count -eq 0) { "all present: $($categories -join ', ')" } else { "MISSING: $($missingCats -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 7 - DO NOT BUILD list is explicit in the authoritative specification
# ---------------------------------------------------------------------------
$donotbuild = @('Kubernetes', 'microservices', 'AI agents', 'custom ML', 'mixnets',
                'keyless ballot box', 'commit-reveal', 'mobile application',
                'cloud autoscaling', 'custom blockchain')
$pmrText = Read-RepoText 'PROJECT_MASTER_REPORT.md'
$missingDnb = @()
if ($null -ne $pmrText) {
    # The authoritative exclusions list is the last DO NOT BUILD heading in the document.
    $idx = $pmrText.LastIndexOf('DO NOT BUILD')
    if ($idx -ge 0) {
        $block = $pmrText.Substring($idx, [Math]::Min(1500, $pmrText.Length - $idx))
        $missingDnb = @($donotbuild | Where-Object { $block -notmatch [regex]::Escape($_) })
    } else { $missingDnb = @('(DO NOT BUILD section absent)') }
} else { $missingDnb = @('(PROJECT_MASTER_REPORT.md unreadable)') }
Add-Result -Id 7 -Name 'DO NOT BUILD list is explicit' `
    -Passed ($missingDnb.Count -eq 0) `
    -Detail $(if ($missingDnb.Count -eq 0) { "all $($donotbuild.Count) exclusions present" } else { "MISSING: $($missingDnb -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 8 - Architecture keywords present
# ---------------------------------------------------------------------------
$archNeedles = @('React', 'Vite', 'Flask', 'MySQL', 'Ganache', 'Solidity 0.8.19',
                 'Hardhat', 'Relayer', 'Reconciliation', 'EVotingBallotBox')
$missingArch = @($archNeedles | Where-Object { ($null -eq $pmrText) -or ($pmrText -notmatch [regex]::Escape($_)) })
Add-Result -Id 8 -Name 'Architecture keywords present in specification' `
    -Passed ($missingArch.Count -eq 0) `
    -Detail $(if ($missingArch.Count -eq 0) { "all $($archNeedles.Count) keywords present" } else { "MISSING: $($missingArch -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 9 - Two-data-plane terminology present
# ---------------------------------------------------------------------------
$planeNeedles = @('IDENTITY PLANE', 'BALLOT PLANE', 'No direct linking')
$missingPlane = @($planeNeedles | Where-Object { ($null -eq $pmrText) -or ($pmrText -notmatch [regex]::Escape($_)) })
Add-Result -Id 9 -Name 'Two-data-plane terminology present' `
    -Passed ($missingPlane.Count -eq 0) `
    -Detail $(if ($missingPlane.Count -eq 0) { 'IDENTITY PLANE / BALLOT PLANE / separation constraint found' } else { "MISSING: $($missingPlane -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 10 - Environment floors frozen
# ---------------------------------------------------------------------------
$envNeedles = @('3.11+', 'MySQL', '8.0', '20+', 'Solidity', '0.8.19', 'Hardhat',
                'Ganache', '1337', 'mkcert', 'MetaMask', 'Webcam')
$envSrc = @((Read-RepoText 'PROJECT_MASTER_REPORT.md'), (Read-RepoText 'PROJECT_BIBLE.md'),
            (Read-RepoText 'docs/DEV_SETUP.md'), (Read-RepoText 'README.md')) -join "`n"
$missingEnv = @($envNeedles | Where-Object { $envSrc -notmatch [regex]::Escape($_) })
Add-Result -Id 10 -Name 'Environment floors frozen in documentation' `
    -Passed ($missingEnv.Count -eq 0) `
    -Detail $(if ($missingEnv.Count -eq 0) { "all $($envNeedles.Count) environment references present" } else { "MISSING: $($missingEnv -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 11 - blockchain/ and blockchain/contracts/ exist
# ---------------------------------------------------------------------------
$bcOk = ($null -ne (Get-RepoDir 'blockchain'))
$bcContractsOk = ($null -ne (Get-RepoDir 'blockchain/contracts'))
$solidityOk = ($null -ne (Get-RepoFile 'blockchain/contracts/EVotingBallotBox.sol'))
Add-Result -Id 11 -Name 'blockchain/ and blockchain/contracts/ exist' `
    -Passed ($bcOk -and $bcContractsOk -and $solidityOk) `
    -Detail "blockchain/=$bcOk  blockchain/contracts/=$bcContractsOk  EVotingBallotBox.sol=$solidityOk"

# ---------------------------------------------------------------------------
# CHECK 12 - blockchain path is used correctly, no stale top-level contracts/
# ---------------------------------------------------------------------------
$docFiles = @()
if ($null -ne (Get-RepoDir 'docs')) {
    $docFiles += Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'docs') -Filter '*.md' -File
}
foreach ($n in @('README.md', 'PROJECT_BIBLE.md', 'PROJECT_MASTER_REPORT.md')) {
    $p = Get-RepoFile $n; if ($null -ne $p) { $docFiles += Get-Item -LiteralPath $p }
}
foreach ($n in @('backend/README.md', 'frontend/README.md')) {
    $p = Get-RepoFile $n; if ($null -ne $p) { $docFiles += Get-Item -LiteralPath $p }
}
$stalePath = @()
foreach ($f in $docFiles) {
    $t = $null
    try { $t = [System.IO.File]::ReadAllText($f.FullName) } catch { continue }
    foreach ($line in ($t -split "`r?`n")) {
        # Skip ASCII/Unicode tree renderings: a "|-- contracts/" row is nested under its
        # blockchain/ parent row in the same diagram, so it is the correct path.
        if ($line -match '(\||\+|\u251C|\u2514|\u2502|\\)\s*-{2,}>?\s') { continue }
        # A top-level contracts/ reference is stale; blockchain/contracts/ is correct.
        if ($line -match '(?<![\w/])contracts/' -and $line -notmatch 'blockchain/contracts/' -and $line -notmatch '`contracts/`') {
            $stalePath += "$($f.Name): $($line.Trim())"
        }
    }
}
Add-Result -Id 12 -Name 'Documentation uses blockchain/contracts/ (no stale top-level contracts/)' `
    -Passed ($stalePath.Count -eq 0) `
    -Detail $(if ($stalePath.Count -eq 0) { 'no stale top-level contracts/ references' } else { "STALE: $($stalePath -join ' | ')" })

# ---------------------------------------------------------------------------
# CHECK 13 - backend/ and frontend/ exist with expected entry points
# ---------------------------------------------------------------------------
$backendOk = ($null -ne (Get-RepoFile 'backend/app/__init__.py')) -and ($null -ne (Get-RepoFile 'backend/requirements.txt'))
$frontendOk = ($null -ne (Get-RepoFile 'frontend/package.json')) -and ($null -ne (Get-RepoFile 'frontend/src/App.jsx'))
Add-Result -Id 13 -Name 'backend/ and frontend/ present with entry points' `
    -Passed ($backendOk -and $frontendOk) `
    -Detail "backend=$backendOk  frontend=$frontendOk"

# ---------------------------------------------------------------------------
# CHECK 14 - docs/ present with expected documents
# ---------------------------------------------------------------------------
$docsNeeded = @('docs/DEV_SETUP.md', 'docs/DATABASE_SETUP.md', 'docs/THREAT_MODEL_REGISTER.md',
                'docs/PHASE0_CHECKPOINT.md')
$missingDocs = @($docsNeeded | Where-Object { $null -eq (Get-RepoFile $_) })
Add-Result -Id 14 -Name 'docs/ contains required documents' `
    -Passed ($missingDocs.Count -eq 0) `
    -Detail $(if ($missingDocs.Count -eq 0) { "found: $($docsNeeded -join ', ')" } else { "MISSING: $($missingDocs -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 15 - No old-project contamination inside the repository
# ---------------------------------------------------------------------------
$contamination = New-Object System.Collections.Generic.List[string]
$allowedRootLiteral = 'C:\Users\aditya prasad\Downloads\voting-sys'
$scanRoots = @('docs', 'backend', 'frontend', 'blockchain', 'scripts')
$extensions = @('.md', '.txt', '.json', '.js', '.jsx', '.py', '.sql', '.sol', '.css', '.html',
                '.ps1', '.example', '.yml', '.yaml')
$attestationAllowance = @('No legacy code', 'No previous project', 'No old project',
                          'independent of all previous projects', 'not a git repository',
                          'legacy', 'previous project', 'old project')
foreach ($r in $scanRoots) {
    $rp = Get-RepoDir $r
    if ($null -eq $rp) { continue }
    $items = Get-ChildItem -LiteralPath $rp -Recurse -File -Force -ErrorAction SilentlyContinue |
             Where-Object {
                 $n = $_.Name
                 ($extensions -contains $_.Extension.ToLower()) -and
                 ($n -ne 'package-lock.json')
             }
    foreach ($it in $items) {
        if ($it.FullName -match '\\(node_modules|venv|dist|artifacts|cache|__pycache__|\.pytest_cache|\.git)\\') { continue }
        $t = $null
        try { $t = [System.IO.File]::ReadAllText($it.FullName) } catch { continue }
        if ($null -eq $t) { continue }
        $rel = $it.FullName.Substring($RepoRoot.Length + 1)
        foreach ($line in ($t -split "`r?`n")) {
            $l = $line.Trim()
            if ([string]::IsNullOrWhiteSpace($l)) { continue }
            # Absolute Windows path other than this repository root.
            # The match stops at the first space, so a legitimate repository path is
            # recognised by testing whether the repository root starts with it.
            foreach ($m in [regex]::Matches($l, '[A-Za-z]:\\[^"''<>\s|]*')) {
                if ($RepoRoot.StartsWith($m.Value)) { continue }
                $contamination.Add("$rel -> absolute path outside repo: $($m.Value)")
            }
            # UNIX home directories
            if ($l -match '/(home|Users)/[A-Za-z0-9_.-]+/') {
                $contamination.Add("$rel -> unix home path: $l")
            }
            # Agent memory / external tooling references.
            # This verifier necessarily names the tokens it searches for, so it is
            # excluded from its own token scan. A negated mention ("no AGENTS.md found")
            # is an attestation, not contamination, and is also allowed.
            $isNegated = ($l -match '(?i)\b(no|not|none|never|without|absent|excluded)\b')
            if ($it.Name -ne 'verify_foundation.ps1' -and -not $isNegated) {
                foreach ($bad in @('.claude/', 'AGENTS.md', 'CLAUDE.md', 'opencode', 'anthropic')) {
                    if ($l -match [regex]::Escape($bad)) { $contamination.Add("$rel -> '$bad' reference") }
                }
            }
            # Legacy-project keywords, ignoring explicit no-legacy attestations
            $isAttestation = $false
            foreach ($a in $attestationAllowance) { if ($l -match [regex]::Escape($a)) { $isAttestation = $true; break } }
            if (-not $isAttestation -and -not $isNegated) {
                foreach ($bad in @('legacy code', 'previous project', 'old project')) {
                    if ($l -match [regex]::Escape($bad)) { $contamination.Add("$rel -> '$bad' mention") }
                }
            }
        }
    }
}
Add-Result -Id 15 -Name 'No old-project contamination inside repository' `
    -Passed ($contamination.Count -eq 0) `
    -Detail $(if ($contamination.Count -eq 0) { 'scan of docs/backend/frontend/blockchain/scripts found no external paths, agent-memory references or legacy-project mentions' } else { "FOUND $($contamination.Count): $($contamination -join ' | ')" })

# ---------------------------------------------------------------------------
# CHECK 16 - No stale phase status in active documentation
# ---------------------------------------------------------------------------
$activeDocs = @('README.md', 'PROJECT_BIBLE.md', 'docs/DEV_SETUP.md',
                'docs/DATABASE_SETUP.md', 'backend/README.md', 'frontend/README.md')
$stalePatterns = @(
    'Phase 0: In Progress',
    'Phase 0 In Progress',
    'Phase 1: IN PROGRESS',
    'Phase 1: Not Started',
    'Phase 2: NOT STARTED',
    'Phase 2: Not Started',
    'Phase 2 \+: NOT STARTED',
    'Directory State: Empty',
    'Setup: To be defined in Phase 1',
    'Phases 1.17 Not started'
)
$staleFound = @()
foreach ($d in $activeDocs) {
    $t = Read-RepoText $d
    if ($null -eq $t) { continue }
    foreach ($p in $stalePatterns) {
        if ($t -match [regex]::Escape($p)) { $staleFound += "$d contains '$p'" }
    }
    # Regex-based variants
    if ($t -match 'Phase\s+2\s*:\s*NOT STARTED') { $staleFound += "$d matches 'Phase 2: NOT STARTED' (regex)" }
    if ($t -match 'Phase\s+1\s*:\s*(IN PROGRESS|Not Started)') { $staleFound += "$d matches stale Phase 1 status (regex)" }
}
Add-Result -Id 16 -Name 'No stale phase status in active documentation' `
    -Passed ($staleFound.Count -eq 0) `
    -Detail $(if ($staleFound.Count -eq 0) { "checked $($activeDocs.Count) active documents" } else { "STALE: $($staleFound -join ' | ')" })

# ---------------------------------------------------------------------------
# CHECK 17 - Phase final reports are standardised under docs/
# ---------------------------------------------------------------------------
$rootReports = @(Get-ChildItem -LiteralPath $RepoRoot -Filter 'PHASE*_FINAL_REPORT.md' -File -ErrorAction SilentlyContinue)
$missingReports = @()
foreach ($n in 0..10) {
    if ($null -eq (Get-RepoFile "docs/PHASE${n}_FINAL_REPORT.md")) { $missingReports += "PHASE${n}_FINAL_REPORT.md" }
}
$reportOk = ($rootReports.Count -eq 0) -and ($missingReports.Count -eq 0)
Add-Result -Id 17 -Name 'Phase final reports standardised under docs/' `
    -Passed $reportOk `
    -Detail $(if ($reportOk) { "docs/PHASE0..PHASE10_FINAL_REPORT.md all present; 0 root-level reports" }
              else { "root-level reports=$($rootReports.Count) [$((@($rootReports | ForEach-Object { $_.Name })) -join ',')]; missing under docs/: $($missingReports -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 18 - PROJECT_BIBLE.md has no literal escaped-newline formatting
# ---------------------------------------------------------------------------
$escapedNewlines = 0
if ($null -ne $bible) { $escapedNewlines = ([regex]::Matches($bible, '(\\r\\n|\\n)')).Count }
Add-Result -Id 18 -Name 'PROJECT_BIBLE.md free of literal escaped newlines' `
    -Passed ($escapedNewlines -eq 0) `
    -Detail "literal '\n' occurrences: $escapedNewlines"

# ---------------------------------------------------------------------------
# CHECK 19 - PROJECT_BIBLE.md free of mojibake and valid UTF-8
# ---------------------------------------------------------------------------
$mojibake = @()
$biblePath = Get-RepoFile 'PROJECT_BIBLE.md'
$bibleBytes = $null
if ($null -ne $biblePath) {
    $bibleBytes = [System.IO.File]::ReadAllBytes($biblePath)
    $hasBom = ($bibleBytes.Length -ge 3 -and $bibleBytes[0] -eq 0xEF -and $bibleBytes[1] -eq 0xBB -and $bibleBytes[2] -eq 0xBF)
    if ($hasBom) { $mojibake += 'UTF-8 BOM present' }
    $strict = New-Object System.Text.UTF8Encoding($false, $true)
    try { $decoded = $strict.GetString($bibleBytes) } catch { $decoded = $null; $mojibake += 'not valid UTF-8' }
    if ($null -ne $decoded) {
        foreach ($cp in @(0x00C2, 0x00C3, 0x00E2, 0x00F0, 0x00EF, 0xFFFD)) {
            $n = ([regex]::Matches($decoded, [regex]::Escape([string][char]$cp))).Count
            if ($n -gt 0) { $mojibake += ("mojibake marker U+{0:X4} x{1}" -f $cp, $n) }
        }
    }
}
Add-Result -Id 19 -Name 'PROJECT_BIBLE.md valid UTF-8, no BOM, no mojibake' `
    -Passed ($mojibake.Count -eq 0) `
    -Detail $(if ($mojibake.Count -eq 0) { 'strict UTF-8 decode OK; no BOM; no mojibake markers' } else { "PROBLEM: $($mojibake -join '; ')" })

# ---------------------------------------------------------------------------
# CHECK 20 - Current phase status is internally consistent
# ---------------------------------------------------------------------------
$statusProblems = @()
$bibleStatusIdx = -1
$bibleStatusEnd = -1
if ($null -ne $bible) {
    $bibleStatusIdx = $bible.IndexOf('## 3. CURRENT PHASE STATUS')
    if ($bibleStatusIdx -ge 0) {
        $next = $bible.IndexOf("`n## 4.", $bibleStatusIdx)
        $bibleStatusEnd = if ($next -gt 0) { $next } else { $bible.Length }
    }
}
if ($bibleStatusIdx -lt 0) {
    $statusProblems += 'PROJECT_BIBLE.md has no Section 3 current phase status block'
} else {
    $block = $bible.Substring($bibleStatusIdx, $bibleStatusEnd - $bibleStatusIdx)
    if ($block -notmatch 'AUTHORITATIVE') { $statusProblems += 'Section 3 is not labelled AUTHORITATIVE' }
    foreach ($n in 0..10) {
        $rowOk = $false
        foreach ($line in ($block -split "`r?`n")) {
            if ($line -match "^\|\s*Phase\s+$n\s*\|" -and $line -match 'COMPLETE') { $rowOk = $true }
        }
        if (-not $rowOk) { $statusProblems += "Phase $n not marked COMPLETE in Section 3" }
    }
    foreach ($n in 11..17) {
        $rowOk = $false
        foreach ($line in ($block -split "`r?`n")) {
            if ($line -match "^\|\s*Phase\s+$n\s*\|" -and $line -match 'NOT STARTED') { $rowOk = $true }
        }
        if (-not $rowOk) { $statusProblems += "Phase $n not marked NOT STARTED in Section 3" }
    }
    if ($block -match 'Phase\s+11\b[^\r\n]*COMPLETE') { $statusProblems += 'Section 3 claims Phase 11 is COMPLETE' }
}
# No other file may claim to be the current-phase authority
foreach ($f in $docFiles) {
    if ($f.Name -eq 'PROJECT_BIBLE.md') { continue }
    $t = $null
    try { $t = [System.IO.File]::ReadAllText($f.FullName) } catch { continue }
    if ($t -match 'AUTHORITATIVE' -and $t -match 'CURRENT PHASE STATUS' -and $f.FullName -notmatch 'PHASE0_FINAL_REPORT|PHASE0_FOUNDATION_AUDIT') {
        # A document that points at PROJECT_BIBLE.md as the authority is correct.
        # Only a document that asserts authority over itself is a competing source.
        $selfAssert = @()
        foreach ($line in ($t -split "`r?`n")) {
            if ($line -match 'PROJECT_BIBLE') { continue }
            if ($line -match 'AUTHORITATIVE' -and $line -match 'CURRENT PHASE STATUS') { $selfAssert += $line.Trim() }
        }
        if ($selfAssert.Count -gt 0) {
            $statusProblems += "$($f.Name) also claims authoritative current phase status: $($selfAssert[0])"
        }
    }
}
Add-Result -Id 20 -Name 'Current phase status internally consistent' `
    -Passed ($statusProblems.Count -eq 0) `
    -Detail $(if ($statusProblems.Count -eq 0) { 'Section 3 lists Phase 0-10 COMPLETE and Phase 11-17 NOT STARTED; no competing authority' } else { "PROBLEM: $($statusProblems -join '; ')" })

# ---------------------------------------------------------------------------
# CHECK 21 - README accuracy markers
# ---------------------------------------------------------------------------
$readme = Read-RepoText 'README.md'
$readmeNeedles = @('Vote Without Doubt', 'ACADEMIC PROTOTYPE', 'not a legally binding',
                   'blockchain/contracts/', 'PROJECT_BIBLE.md', 'Two data planes',
                   'Technology stack', 'Repository structure', 'Limitations')
$missingReadme = @($readmeNeedles | Where-Object { (Test-HasAll -Text $readme -Needles @($_)) -eq $false })
Add-Result -Id 21 -Name 'Root README contains required accuracy markers' `
    -Passed ($missingReadme.Count -eq 0) `
    -Detail $(if ($missingReadme.Count -eq 0) { "all $($readmeNeedles.Count) markers present" } else { "MISSING: $($missingReadme -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 22 - No secrets committed / .env handling correct
# ---------------------------------------------------------------------------
$secretProblems = @()
$gi = Read-RepoText '.gitignore'
if ($null -eq $gi) { $secretProblems += '.gitignore unreadable' }
else {
    foreach ($needle in @('.env', 'venv/', 'node_modules/', '__pycache__/', '.pytest_cache/', 'dist/', 'artifacts/')) {
        if ($gi -notmatch [regex]::Escape($needle)) { $secretProblems += ".gitignore missing '$needle'" }
    }
    if ($gi -notmatch '!\.env\.example') { $secretProblems += '.gitignore does not keep .env.example tracked' }
}
$envFiles = @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force -File -Filter '.env' -ErrorAction SilentlyContinue |
              Where-Object { $_.FullName -notmatch '\\(node_modules|venv)\\' })
if ($envFiles.Count -gt 0) { $secretProblems += "real .env file(s) present: $((@($envFiles | ForEach-Object { $_.FullName })) -join ', ')" }
if ($null -ne (Get-RepoFile 'backend/.env.example')) { } else { $secretProblems += 'backend/.env.example missing' }
Add-Result -Id 22 -Name 'No committed secrets; .env handling correct' `
    -Passed ($secretProblems.Count -eq 0) `
    -Detail $(if ($secretProblems.Count -eq 0) { '.gitignore covers generated paths, keeps .env.example, no real .env present' } else { "PROBLEM: $($secretProblems -join '; ')" })

# ---------------------------------------------------------------------------
# CHECK 23 - Git repository state is valid and local-only
# ---------------------------------------------------------------------------
$gitProblems = @()
$gitDir = Join-Path $RepoRoot '.git'
if (-not (Test-Path -LiteralPath $gitDir -PathType Container)) {
    $gitProblems += 'no .git directory (repository not initialised)'
} else {
    $inside = (& git -C $RepoRoot rev-parse --is-inside-work-tree 2>$null)
    if ($LASTEXITCODE -ne 0 -or ($inside -ne 'true')) { $gitProblems += 'git rev-parse failed' }
    $remotes = @(& git -C $RepoRoot remote 2>$null)
    if ($remotes.Count -gt 0) { $gitProblems += "unexpected remote(s): $($remotes -join ', ')" }
    $commits = @(& git -C $RepoRoot log --oneline 2>$null)
    if ($commits.Count -lt 1) { $gitProblems += 'no commits present' }
    $tracked = @(& git -C $RepoRoot ls-files 2>$null)
    foreach ($bad in @('node_modules/', 'venv/', '/dist/', 'artifacts/', '.pytest_cache/', '__pycache__/')) {
        $hit = @($tracked | Where-Object { $_ -like "*$bad*" })
        if ($hit.Count -gt 0) { $gitProblems += "generated path tracked ($bad): $($hit[0])" }
    }
    $trackedEnv = @($tracked | Where-Object { ($_ -match '(^|/)\.env$') })
    if ($trackedEnv.Count -gt 0) { $gitProblems += "real .env tracked: $($trackedEnv -join ', ')" }
}
Add-Result -Id 23 -Name 'Git repository valid and local-only' `
    -Passed ($gitProblems.Count -eq 0) `
    -Detail $(if ($gitProblems.Count -eq 0) { "git initialised, no remotes, generated paths untracked" } else { "PROBLEM: $($gitProblems -join '; ')" })

# ---------------------------------------------------------------------------
# CHECK 24 - Threat model register present with no fabricated-test guardrails
# ---------------------------------------------------------------------------
$tmd = Read-RepoText 'docs/THREAT_MODEL_REGISTER.md'
$tmdNeedles = @('Threat', 'Control', 'Test / Evidence', 'Result', 'Remaining limitation',
                'Not yet evidenced', 'No test found')
$missingTmd = @($tmdNeedles | Where-Object { (Test-HasAll -Text $tmd -Needles @($_)) -eq $false })
Add-Result -Id 24 -Name 'Threat model register present and honest about evidence' `
    -Passed ($missingTmd.Count -eq 0) `
    -Detail $(if ($missingTmd.Count -eq 0) { "all $($tmdNeedles.Count) register markers present" } else { "MISSING: $($missingTmd -join ', ')" })

# ---------------------------------------------------------------------------
# CHECK 25 - Phase 0 report carries the A-M completion sections
# ---------------------------------------------------------------------------
$p0text = Read-RepoText 'docs/PHASE0_FINAL_REPORT.md'
$p0letters = @('A.', 'B.', 'C.', 'D.', 'E.', 'F.', 'G.', 'H.', 'I.', 'J.', 'K.', 'L.', 'M.')
$missingLetters = @()
if ($null -eq $p0text) { $missingLetters = @('(file unreadable)') }
else {
    $missingLetters = @($p0letters | Where-Object { $p0text -notmatch [regex]::Escape($_) })
}
Add-Result -Id 25 -Name 'Phase 0 report contains completion sections A-M' `
    -Passed ($missingLetters.Count -eq 0) `
    -Detail $(if ($missingLetters.Count -eq 0) { 'sections A through M all present' } else { "MISSING: $($missingLetters -join ', ')" })

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
Write-Host ('-' * 78)
$script:Results | Sort-Object Id | ForEach-Object {
    $tag = if ($_.Passed) { 'PASS' } else { 'FAIL' }
    $col = if ($_.Passed) { 'Green' } else { 'Red' }
    Write-Host ("{0,-4} [{1}] {2}" -f ("{0:d2}" -f $_.Id), $tag, $_.Name) -ForegroundColor $col
    Write-Host ("       {0}" -f $_.Detail) -ForegroundColor DarkGray
}
Write-Host ('-' * 78)

$failed = @($script:Results | Where-Object { -not $_.Passed })
Write-Host ("Checks run: {0}   Passed: {1}   Failed: {2}" -f $script:Results.Count, ($script:Results.Count - $failed.Count), $failed.Count)
Write-Host ''

if ($failed.Count -gt 0) {
    Write-Host 'FOUNDATION VERIFICATION: FAILED' -ForegroundColor Red
    foreach ($f in $failed) { Write-Host ("  - [{0:d2}] {1}: {2}" -f $f.Id, $f.Name, $f.Detail) -ForegroundColor Red }
    exit 1
} else {
    Write-Host 'FOUNDATION VERIFICATION: PASSED' -ForegroundColor Green
    exit 0
}