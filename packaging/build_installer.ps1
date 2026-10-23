param(
    [switch]$SkipAppBuild,
    [string]$IsccPath
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'Create .venv and install .[dev,windows] with packaging/constraints-windows.txt first.'
}

$Version = (& $PythonExe -c 'import tomllib,pathlib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])').Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { throw 'Could not read project version.' }
if (-not $SkipAppBuild) { & (Join-Path $PSScriptRoot 'build_windows.ps1') }
if (-not $IsccPath) {
    $CandidatePaths = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    $IsccPath = $CandidatePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $IsccPath) { throw 'Inno Setup 6 ISCC.exe was not found. Install Inno Setup or pass -IsccPath.' }

Push-Location $ProjectRoot
try {
    & $IsccPath "/DAppVersion=$Version" (Join-Path $PSScriptRoot 'installer.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    $Installer = Join-Path $ProjectRoot "dist\installer\ZomboidSorter-$Version-windows-setup.exe"
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw 'Installer output is missing.' }
    $Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    $Checksum = Join-Path $ProjectRoot "dist\installer\ZomboidSorter-$Version-windows-setup.exe.sha256"
    Set-Content -LiteralPath $Checksum -Value "$Hash  $(Split-Path $Installer -Leaf)" -Encoding ascii
    Write-Host "Installer: $Installer"
    Write-Host "SHA-256: $Hash"
} finally {
    Pop-Location
}
