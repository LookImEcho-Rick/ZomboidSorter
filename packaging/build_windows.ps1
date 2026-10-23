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
} finally {
    $env:PATH = $OriginalPath
    Pop-Location
}
