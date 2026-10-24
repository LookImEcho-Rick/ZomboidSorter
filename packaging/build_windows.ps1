param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $ProjectRoot "src\zomboid_mod_manager\__main__.py"
$OriginalPath = $env:PATH
$GitExecutable = Get-Command git -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty Source

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Create the project virtual environment first: python -m venv .venv"
}

Push-Location $ProjectRoot
try {
    if (-not $SkipDependencyInstall) {
        & $PythonExe -m pip install -e ".[windows]" -c (Join-Path $PSScriptRoot "constraints-windows.txt")
        if ($LASTEXITCODE -ne 0) { throw "Could not install packaging dependencies into .venv." }
    }

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
        --clean `
        --noconfirm `
        --windowed `
        --name ZomboidSorter `
        --icon (Join-Path $ProjectRoot "assets\zomboidsorter.ico") `
        --add-data "$(Join-Path $ProjectRoot 'assets\zomboidsorter-logo.png');assets" `
        --paths (Join-Path $ProjectRoot "src") `
        --additional-hooks-dir (Join-Path $PSScriptRoot 'hooks') `
        --distpath (Join-Path $ProjectRoot "dist") `
        --workpath (Join-Path $ProjectRoot "build") `
        --specpath (Join-Path $ProjectRoot "build") `
        $EntryPoint
    if ($LASTEXITCODE -ne 0) { throw "Windows packaging failed. See the deployment output above." }

    $BuildId = $env:GITHUB_SHA
    if ($BuildId -notmatch '^[0-9a-fA-F]{40}$') {
        if ($GitExecutable) {
            $BuildId = (& $GitExecutable -C $ProjectRoot rev-parse HEAD 2>$null).Trim()
        }
        if (-not $GitExecutable -or $LASTEXITCODE -ne 0 -or $BuildId -notmatch '^[0-9a-fA-F]{40}$') {
            $BuildId = 'local'
        }
    }
    Set-Content -LiteralPath (Join-Path $ProjectRoot 'dist\ZomboidSorter\BUILD_ID') `
        -Value $BuildId.ToLowerInvariant() -Encoding ascii -NoNewline

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

    $InstallerPayload = Join-Path $ProjectRoot 'build\installer_payload'
    $InstallerLicenses = Join-Path $InstallerPayload 'licenses'
    if (Test-Path -LiteralPath $InstallerLicenses -PathType Container) {
        Remove-Item -LiteralPath $InstallerLicenses -Recurse -Force
    }
    New-Item -ItemType Directory -Path $InstallerLicenses -Force | Out-Null
    $PythonLicense = Join-Path $PythonBase 'LICENSE.txt'
    if (-not (Test-Path -LiteralPath $PythonLicense -PathType Leaf)) {
        throw "Bundled CPython license was not found: $PythonLicense"
    }
    Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $InstallerLicenses 'PYTHON.txt')
    $PyInstallerLicense = Get-ChildItem (Join-Path (Split-Path $PythonExe) '..\Lib\site-packages') -Directory -Filter 'pyinstaller-*.dist-info' |
        ForEach-Object { Join-Path $_.FullName 'licenses\COPYING.txt' } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $PyInstallerLicense) { throw 'PyInstaller license was not found.' }
    Copy-Item -LiteralPath $PyInstallerLicense -Destination (Join-Path $InstallerLicenses 'PYINSTALLER.txt')

    $RuntimeVersions = & $PythonExe -c "import importlib.metadata as m, ssl; names=('PySide6','PySide6_Essentials','PySide6_Addons','PySide6_WebEngine','PySide6_Pdf','shiboken6','PyInstaller'); print('\n'.join(f'{n} {m.version(n)}' for n in names)); print(ssl.OPENSSL_VERSION)"
    if ($LASTEXITCODE -ne 0) { throw 'Could not read bundled Qt/PyInstaller package versions.' }
    $PythonVersion = (& $PythonExe -c "import sys; print('.'.join(map(str,sys.version_info[:3])))").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $PythonVersion) { throw 'Could not read the bundled Python version.' }
    @(
        "CPython $PythonVersion"
        $RuntimeVersions
        'See THIRD_PARTY_NOTICES.md and the adjacent license texts for license details.'
    ) | Set-Content -LiteralPath (Join-Path $InstallerLicenses 'BUILD_COMPONENTS.txt') -Encoding utf8

    & $PythonExe (Join-Path $PSScriptRoot 'generate_qt_notices.py') `
        (Join-Path $ProjectRoot 'dist\ZomboidSorter') `
        $InstallerLicenses
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate bundle-scoped Qt/WebEngine notices.' }

    # The expanded HTML notices belong to the installer payload, not the app bundle.
    $AppLicenseDir = Join-Path $ProjectRoot 'dist\ZomboidSorter\licenses'
    if (Test-Path -LiteralPath $AppLicenseDir -PathType Container) {
        Remove-Item -LiteralPath $AppLicenseDir -Recurse -Force
    }
} finally {
    $env:PATH = $OriginalPath
    Pop-Location
}
