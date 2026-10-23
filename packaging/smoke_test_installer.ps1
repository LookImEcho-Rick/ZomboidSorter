param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [string]$PreviousInstallerPath
)

$ErrorActionPreference = 'Stop'

if ($env:GITHUB_ACTIONS -ne 'true') {
    throw 'This installer smoke test is restricted to an isolated GitHub Actions runner.'
}
if (-not $env:RUNNER_TEMP -or -not $env:APPDATA) {
    throw 'The GitHub Actions runner temp and AppData paths are required.'
}

if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer file does not exist: $InstallerPath"
}
$InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
if ((Split-Path -Leaf $InstallerPath) -notmatch '^ZomboidSorter-\d+\.\d+\.\d+-windows-setup\.exe$') {
    throw "Unexpected installer filename: $InstallerPath"
}
if ($PreviousInstallerPath) {
    if (-not (Test-Path -LiteralPath $PreviousInstallerPath -PathType Leaf)) {
        throw "Previous installer file does not exist: $PreviousInstallerPath"
    }
    $PreviousInstallerPath = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
    if ((Split-Path -Leaf $PreviousInstallerPath) -notmatch '^ZomboidSorter-\d+\.\d+\.\d+-windows-setup\.exe$') {
        throw "Unexpected previous installer filename: $PreviousInstallerPath"
    }
}

if (-not (Test-Path -LiteralPath $env:RUNNER_TEMP -PathType Container)) {
    throw 'GitHub Actions runner temp folder does not exist.'
}
$RunnerTemp = (Resolve-Path -LiteralPath $env:RUNNER_TEMP).Path
$RunId = [guid]::NewGuid().ToString('N')
$RunRoot = Join-Path $RunnerTemp "ZomboidSorter-installer-smoke-$RunId"
$RunRootFull = [System.IO.Path]::GetFullPath($RunRoot)
$RunnerTempPrefix = [System.IO.Path]::GetFullPath($RunnerTemp).TrimEnd('\') + '\'
if (-not $RunRootFull.StartsWith($RunnerTempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Smoke-test directory escaped the runner temp folder: $RunRootFull"
}
New-Item -ItemType Directory -Path $RunRootFull | Out-Null

$LogsRoot = Join-Path $RunRootFull 'logs'
$StandardInstall = Join-Path $RunRootFull 'standard'
$PortableInstall = Join-Path $RunRootFull 'portable'
New-Item -ItemType Directory -Path $LogsRoot, $StandardInstall, $PortableInstall | Out-Null

$StandardProfiles = Join-Path $env:APPDATA 'ProjectZomboidModManager\profiles'
$StandardProfileExisted = Test-Path -LiteralPath $StandardProfiles -PathType Container
New-Item -ItemType Directory -Path $StandardProfiles -Force | Out-Null
$StandardProfile = Join-Path $StandardProfiles "CodexSmoke-$RunId.json"
$StandardProfileBytes = [System.Text.Encoding]::UTF8.GetBytes("smoke-profile-$RunId`n")
[System.IO.File]::WriteAllBytes($StandardProfile, $StandardProfileBytes)

$SettingsKey = 'HKCU:\Software\ZomboidSorter\ProjectZomboidModManager'
$SettingsKeyExisted = Test-Path -LiteralPath $SettingsKey
if (-not $SettingsKeyExisted) {
    New-Item -Path $SettingsKey -Force | Out-Null
}
$SettingsValueName = "InstallerSmoke_$RunId"
$SettingsValue = "preserve-$RunId"
New-ItemProperty -Path $SettingsKey -Name $SettingsValueName -Value $SettingsValue -PropertyType String -Force | Out-Null

$PortableData = Join-Path $PortableInstall 'data'
$PortableProfiles = Join-Path $PortableData 'profiles'
New-Item -ItemType Directory -Path $PortableProfiles -Force | Out-Null
$PortableProfile = Join-Path $PortableProfiles "CodexSmoke-$RunId.json"
$PortableProfileBytes = [System.Text.Encoding]::UTF8.GetBytes("portable-profile-$RunId`n")
[System.IO.File]::WriteAllBytes($PortableProfile, $PortableProfileBytes)
$PortableSettings = Join-Path $PortableData 'settings.ini'
$PortableSettingsBytes = [System.Text.Encoding]::UTF8.GetBytes("[smoke]`nvalue=preserve-$RunId`n")
[System.IO.File]::WriteAllBytes($PortableSettings, $PortableSettingsBytes)

function Assert-BytesEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Expected
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Expected preserved data file is missing: $Path"
    }
    $Actual = [System.IO.File]::ReadAllBytes($Path)
    if ([Convert]::ToBase64String($Actual) -cne [Convert]::ToBase64String($Expected)) {
        throw "Installer changed a preserved data file: $Path"
    }
}

function Assert-StandardData {
    Assert-BytesEqual -Path $StandardProfile -Expected $StandardProfileBytes
    $ActualValue = (Get-ItemProperty -LiteralPath $SettingsKey -Name $SettingsValueName).$SettingsValueName
    if ($ActualValue -cne $SettingsValue) {
        throw 'Installer changed the preserved standard-mode registry value.'
    }
}

function Assert-PortableData {
    Assert-BytesEqual -Path $PortableProfile -Expected $PortableProfileBytes
    Assert-BytesEqual -Path $PortableSettings -Expected $PortableSettingsBytes
}

function ConvertTo-ProcessArguments {
    param([Parameter(Mandatory = $true)][string[]]$Values)
    return (($Values | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + $_.Replace('"', '\"') + '"'
        } else {
            $_
        }
    }) -join ' ')
}

function Invoke-InnoSetup {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][bool]$ExpectSuccess
    )
    $AllArguments = @($Arguments) + @("/LOG=$LogPath")
    $Process = Start-Process -FilePath $Executable `
        -ArgumentList (ConvertTo-ProcessArguments -Values $AllArguments) `
        -PassThru -Wait
    if ($ExpectSuccess -and $Process.ExitCode -ne 0) {
        throw "Installer process failed with exit code $($Process.ExitCode). Log: $LogPath"
    }
    if (-not $ExpectSuccess -and $Process.ExitCode -eq 0) {
        throw "Silent cross-mode install unexpectedly succeeded. Log: $LogPath"
    }
    return $Process.ExitCode
}

function Install-Mode {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$InstallDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('standard', 'portable')][string]$Mode,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $LogPath = Join-Path $LogsRoot "$Label-install.log"
    Invoke-InnoSetup -Executable $Executable -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/TYPE=$Mode", "/DIR=$InstallDirectory"
    ) -LogPath $LogPath -ExpectSuccess $true | Out-Null
}

function Uninstall-Mode {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDirectory,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Uninstaller = Join-Path $InstallDirectory 'unins000.exe'
    if (-not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) {
        throw "Installed uninstaller is missing: $Uninstaller"
    }
    $LogPath = Join-Path $LogsRoot "$Label-uninstall.log"
    Invoke-InnoSetup -Executable $Uninstaller -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    ) -LogPath $LogPath -ExpectSuccess $true | Out-Null
}

function Test-PackagedApplicationLaunch {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDirectory,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Executable = Join-Path $InstallDirectory 'ZomboidSorter.exe'
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Packaged application is missing before launch check: $Executable"
    }
    $Executable = (Resolve-Path -LiteralPath $Executable).Path
    $InstallRoot = [System.IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\') + '\'
    if (-not $Executable.StartsWith($InstallRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Packaged application escaped the isolated install directory: $Executable"
    }

    Write-Host "Launching the packaged application in $Label mode."
    $Process = Start-Process -FilePath $Executable `
        -WorkingDirectory $InstallDirectory -PassThru
    try {
        $Deadline = [DateTime]::UtcNow.AddSeconds(45)
        $WindowTitle = ''
        while ([DateTime]::UtcNow -lt $Deadline) {
            $Process.Refresh()
            if ($Process.HasExited) {
                throw "Packaged application exited during startup with code $($Process.ExitCode) ($Label mode)."
            }
            if ($Process.MainWindowHandle -ne [IntPtr]::Zero) {
                $WindowTitle = $Process.MainWindowTitle
                if ($WindowTitle -match 'ZomboidSorter') { break }
            }
            Start-Sleep -Milliseconds 250
        }
        if ($WindowTitle -notmatch 'ZomboidSorter') {
            throw "Packaged application did not show its main window within 45 seconds ($Label mode)."
        }
        if (-not $Process.CloseMainWindow()) {
            throw "Could not request a clean close for the packaged application ($Label mode)."
        }
        if (-not $Process.WaitForExit(15000)) {
            throw "Packaged application did not close within 15 seconds ($Label mode)."
        }
        $Process.Refresh()
        if ($Process.ExitCode -ne 0) {
            throw "Packaged application exited with code $($Process.ExitCode) after closing ($Label mode)."
        }
        Write-Host "Packaged application launched and closed cleanly in $Label mode."
    } finally {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            $Process.Kill()
            [void]$Process.WaitForExit(5000)
        }
    }
}

$Completed = $false
try {
    $VersionInstallers = @()
    if ($PreviousInstallerPath) {
        $VersionInstallers += [PSCustomObject]@{ Path = $PreviousInstallerPath; Label = 'previous' }
    }
    $VersionInstallers += [PSCustomObject]@{ Path = $InstallerPath; Label = 'current' }
    if (-not $PreviousInstallerPath) {
        $VersionInstallers += [PSCustomObject]@{ Path = $InstallerPath; Label = 'reinstall' }
    }

    foreach ($InstallVersion in $VersionInstallers) {
        Install-Mode -Executable $InstallVersion.Path -InstallDirectory $StandardInstall `
            -Mode 'standard' -Label "standard-$($InstallVersion.Label)"
        if (-not (Test-Path -LiteralPath (Join-Path $StandardInstall 'ZomboidSorter.exe') -PathType Leaf)) {
            throw "Standard-mode install did not produce ZomboidSorter.exe ($($InstallVersion.Label))."
        }
        if (Test-Path -LiteralPath (Join-Path $StandardInstall 'portable.flag')) {
            throw 'Standard-mode install unexpectedly created portable.flag.'
        }
        Assert-StandardData
        if ($InstallVersion.Label -eq 'current') {
            Test-PackagedApplicationLaunch -InstallDirectory $StandardInstall -Label 'standard'
        }
    }

    $StandardCrossModeLog = Join-Path $LogsRoot 'standard-to-portable.log'
    Invoke-InnoSetup -Executable $InstallerPath -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TYPE=portable', "/DIR=$StandardInstall"
    ) -LogPath $StandardCrossModeLog -ExpectSuccess $false | Out-Null
    if (Test-Path -LiteralPath (Join-Path $StandardInstall 'portable.flag')) {
        throw 'A refused standard-to-portable switch changed the installation mode.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $StandardInstall 'ZomboidSorter.exe') -PathType Leaf)) {
        throw 'A refused standard-to-portable switch removed the existing application.'
    }
    Assert-StandardData
    Uninstall-Mode -InstallDirectory $StandardInstall -Label 'standard'
    if (Test-Path -LiteralPath (Join-Path $StandardInstall 'ZomboidSorter.exe')) {
        throw 'Standard-mode uninstall left the application executable behind.'
    }
    Assert-StandardData

    foreach ($InstallVersion in $VersionInstallers) {
        Install-Mode -Executable $InstallVersion.Path -InstallDirectory $PortableInstall `
            -Mode 'portable' -Label "portable-$($InstallVersion.Label)"
        if (-not (Test-Path -LiteralPath (Join-Path $PortableInstall 'ZomboidSorter.exe') -PathType Leaf)) {
            throw "Portable-mode install did not produce ZomboidSorter.exe ($($InstallVersion.Label))."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $PortableInstall 'portable.flag') -PathType Leaf)) {
            throw 'Portable-mode install did not create portable.flag.'
        }
        Assert-PortableData
        if ($InstallVersion.Label -eq 'current') {
            Test-PackagedApplicationLaunch -InstallDirectory $PortableInstall -Label 'portable'
        }
    }

    $PortableCrossModeLog = Join-Path $LogsRoot 'portable-to-standard.log'
    Invoke-InnoSetup -Executable $InstallerPath -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TYPE=standard', "/DIR=$PortableInstall"
    ) -LogPath $PortableCrossModeLog -ExpectSuccess $false | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $PortableInstall 'portable.flag') -PathType Leaf)) {
        throw 'A refused portable-to-standard switch changed the installation mode.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $PortableInstall 'ZomboidSorter.exe') -PathType Leaf)) {
        throw 'A refused portable-to-standard switch removed the existing application.'
    }
    Assert-PortableData
    Uninstall-Mode -InstallDirectory $PortableInstall -Label 'portable'
    if (Test-Path -LiteralPath (Join-Path $PortableInstall 'ZomboidSorter.exe')) {
        throw 'Portable-mode uninstall left the application executable behind.'
    }
    Assert-PortableData

    $Completed = $true
    Write-Host 'Installer smoke test passed: standard and portable install, packaged app launch/close in both modes, same-mode upgrade/reinstall, silent cross-mode refusal, uninstall, and app-data preservation.'
} finally {
    Remove-Item -LiteralPath $StandardProfile -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -LiteralPath $SettingsKey -Name $SettingsValueName -ErrorAction SilentlyContinue
    if (-not $SettingsKeyExisted -and (Test-Path -LiteralPath $SettingsKey)) {
        $Key = Get-Item -LiteralPath $SettingsKey
        if ($Key.ValueCount -eq 0 -and $Key.SubKeyCount -eq 0) {
            Remove-Item -LiteralPath $SettingsKey -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $StandardProfileExisted -and (Test-Path -LiteralPath $StandardProfiles) -and
        -not (Get-ChildItem -LiteralPath $StandardProfiles -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $StandardProfiles -Force -ErrorAction SilentlyContinue
    }
    if ($Completed) {
        $ResolvedRunRoot = [System.IO.Path]::GetFullPath($RunRootFull)
        $ResolvedRunnerTempPrefix = [System.IO.Path]::GetFullPath($RunnerTemp).TrimEnd('\') + '\'
        if ($ResolvedRunRoot.StartsWith($ResolvedRunnerTempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $ResolvedRunRoot).StartsWith('ZomboidSorter-installer-smoke-', [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ResolvedRunRoot -Recurse -Force
        }
    } else {
        Write-Host "Installer smoke-test files and logs retained for diagnosis: $RunRootFull"
    }
}
