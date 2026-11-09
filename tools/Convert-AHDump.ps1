<#
.SYNOPSIS
    Wandelt die SavedVariables-Datei AHDump.lua in eine CSV-Datei um.
.DESCRIPTION
    Sucht ohne Parameter automatisch die zuletzt geschriebene AHDump.lua im
    WTF-Ordner des Forever-Clients (relativ zum Addon-Ordner oder per -WowPath).
.EXAMPLE
    .\Convert-AHDump.ps1
.EXAMPLE
    .\Convert-AHDump.ps1 -WowPath "E:\World of Warcraft\_forever_" -Out "C:\temp\ah.csv"
#>
param(
    [string]$Path,
    [string]$WowPath,
    [string]$Out
)

if (-not $Path) {
    $searchRoots = @()
    if ($WowPath)  { $searchRoots += (Join-Path $WowPath "WTF\Account") }
    $searchRoots += (Join-Path $PSScriptRoot "..\..\..\WTF\Account")   # tools\ im Client
    $searchRoots += (Join-Path $PSScriptRoot "..\data")                # Repo-Ablage

    foreach ($root in $searchRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $candidate = Get-ChildItem -Path $root -Recurse -Filter "AHDump.lua" -ErrorAction SilentlyContinue |
                     Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($candidate) { $Path = $candidate.FullName; break }
    }
}

if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
    Write-Error "AHDump.lua nicht gefunden. Erst im Spiel /ahdump ausfuehren, danach /reload. Alternativ -Path angeben."
    exit 1
}

Write-Host "Lese: $Path"

$header = $null
$rows = New-Object System.Collections.Generic.List[string]
$inRows = $false

foreach ($line in [System.IO.File]::ReadLines($Path, [System.Text.Encoding]::UTF8)) {
    if (-not $inRows) {
        if (-not $header -and $line -match '\["header"\]\s*=\s*"(.*)"') { $header = $Matches[1] }
        if ($line -match '\["rows"\]\s*=\s*\{') { $inRows = $true }
        continue
    }
    if ($line -match '^\s*\},?\s*$') { $inRows = $false; continue }
    if ($line -match '^\s*"(.*)",\s*(--.*)?$') {
        $rows.Add($Matches[1].Replace('\"', '"').Replace('\', '\'))
    }
}

if ($rows.Count -eq 0) {
    Write-Error "Keine Zeilen gefunden - wurde nach /ahdump auch /reload ausgefuehrt?"
    exit 1
}

if (-not $header) {
    $header = "index,itemID,itemString,name,quality,count,minBid,buyout,bidAmount,owner,timeLeft,level,isCommodity"
}
if (-not $Out) {
    $Out = Join-Path (Split-Path -Parent $Path) ("ahdump_" + (Get-Date -Format "yyyy-MM-dd_HHmm") + ".csv")
}

$all = New-Object System.Collections.Generic.List[string]
$all.Add($header)
$all.AddRange($rows)
$all | Out-File -LiteralPath $Out -Encoding utf8

Write-Host "Geschrieben: $Out ($($rows.Count) Auktionen)" -ForegroundColor Green
