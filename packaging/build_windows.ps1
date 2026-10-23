$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $ProjectRoot "src\zomboid_mod_manager\__main__.py"
$OriginalPath = $env:PATH

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Create the project virtual environment first: python -m venv .venv"
}

Push-Location $ProjectRoot
try {
    & $PythonExe -m pip install -e ".[windows]" -c (Join-Path $PSScriptRoot "constraints-windows.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install packaging dependencies into .venv." }

    # PyInstaller resolves transitive DLLs from PATH. Keep unrelated tools'
    # native libraries (for example, Poppler's ICU DLL) out of the bundle.
    $PythonBase = (& $PythonExe -c "import sys; print(sys.base_prefix)").Trim()
    $env:PATH = @(
        (Join-Path $env:SystemRoot "System32")
        $env:SystemRoot
        (Split-Path $PythonExe)
        $PythonBase
    ) -join [System.IO.Path]::PathSeparator

    & $PythonExe -m PyInstaller `
        --noconfirm `
        --windowed `
        --name ZomboidSorter `
        --icon (Join-Path $ProjectRoot "assets\zomboidsorter.ico") `
        --add-data "$(Join-Path $ProjectRoot 'assets\zomboidsorter-logo.png');assets" `
        --paths (Join-Path $ProjectRoot "src") `
        --distpath (Join-Path $ProjectRoot "dist") `
        --workpath (Join-Path $ProjectRoot "build") `
        --specpath (Join-Path $ProjectRoot "build") `
        $EntryPoint
    if ($LASTEXITCODE -ne 0) { throw "Windows packaging failed. See the deployment output above." }

    # Qt's WebEngine wheel ships parallel release/debug resources. The release
    # executable uses the regular files; carrying debug copies adds ~75 MB.
    $ResourceDir = Join-Path $ProjectRoot 'dist\ZomboidSorter\_internal\PySide6\resources'
    $ExpectedDebugFiles = @(
        'qtwebengine_devtools_resources.debug.pak',
        'qtwebengine_resources.debug.pak',
        'qtwebengine_resources_100p.debug.pak',
        'qtwebengine_resources_200p.debug.pak',
        'v8_context_snapshot.debug.bin'
    )
    foreach ($DebugName in $ExpectedDebugFiles) {
        $DebugFile = Join-Path $ResourceDir $DebugName
        $ReleaseFile = Join-Path $ResourceDir ($DebugName -replace '\.debug\.', '.')
        if (-not (Test-Path -LiteralPath $ReleaseFile -PathType Leaf)) {
            throw "Required Qt WebEngine release resource is missing: $ReleaseFile"
        }
        if (Test-Path -LiteralPath $DebugFile -PathType Leaf) {
            Remove-Item -LiteralPath $DebugFile
        }
    }

    $BundledLicenses = Join-Path $ProjectRoot 'dist\ZomboidSorter\licenses'
    New-Item -ItemType Directory -Path $BundledLicenses -Force | Out-Null
    $PythonLicense = Join-Path $PythonBase 'LICENSE.txt'
    if (-not (Test-Path -LiteralPath $PythonLicense -PathType Leaf)) {
        throw "Bundled CPython license was not found: $PythonLicense"
    }
    Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $BundledLicenses 'PYTHON.txt')
    $PyInstallerLicense = Get-ChildItem (Join-Path (Split-Path $PythonExe) '..\Lib\site-packages') -Directory -Filter 'pyinstaller-*.dist-info' |
        ForEach-Object { Join-Path $_.FullName 'licenses\COPYING.txt' } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $PyInstallerLicense) { throw 'PyInstaller license was not found.' }
    Copy-Item -LiteralPath $PyInstallerLicense -Destination (Join-Path $BundledLicenses 'PYINSTALLER.txt')
} finally {
    $env:PATH = $OriginalPath
    Pop-Location
}
