param(
    [Parameter(Mandatory = $true)]
    [string]$PreviousInstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedBuildId
)

$ErrorActionPreference = 'Stop'

if ($env:GITHUB_ACTIONS -ne 'true') {
    throw 'This updater smoke test is restricted to an isolated GitHub Actions runner.'
}
if (-not $env:RUNNER_TEMP) {
    throw 'The GitHub Actions runner temp path is required.'
}
if (-not (Test-Path -LiteralPath $PreviousInstallerPath -PathType Leaf)) {
    throw "Previous installer does not exist: $PreviousInstallerPath"
}
if ($ExpectedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Unexpected expected version: $ExpectedVersion"
}
if ($ExpectedBuildId -notmatch '^[0-9a-fA-F]{40}$') {
    throw 'Expected build ID must be a 40-character commit ID.'
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$PreviousInstallerPath = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
$RunnerTemp = (Resolve-Path -LiteralPath $env:RUNNER_TEMP).Path
$RunId = [guid]::NewGuid().ToString('N')
$RunRoot = Join-Path $RunnerTemp "ZomboidSorter-update-smoke-$RunId"
$RunRootFull = [System.IO.Path]::GetFullPath($RunRoot)
$RunnerTempPrefix = [System.IO.Path]::GetFullPath($RunnerTemp).TrimEnd('\') + '\'
if (-not $RunRootFull.StartsWith($RunnerTempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    (Split-Path -Leaf $RunRootFull) -notmatch '^ZomboidSorter-update-smoke-[0-9a-f]{32}$') {
    throw "Updater smoke-test directory escaped runner temp: $RunRootFull"
}

$InstallDirectory = Join-Path $RunRootFull 'portable app'
$DataDirectory = Join-Path $InstallDirectory 'data'
$ProfilesDirectory = Join-Path $DataDirectory 'profiles'
$AppDataRoot = Join-Path $RunRootFull 'local app data'
$TemporaryDirectory = Join-Path $RunRootFull 'temp'
$OwnedProcessIds = [System.Collections.Generic.HashSet[int]]::new()
$Completed = $false
$UpdateHandoffTime = $null

New-Item -ItemType Directory -Path $RunRootFull, $AppDataRoot, $TemporaryDirectory | Out-Null
$env:LOCALAPPDATA = $AppDataRoot
$env:APPDATA = Join-Path $RunRootFull 'roaming app data'
$env:TEMP = $TemporaryDirectory
$env:TMP = $TemporaryDirectory

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

function Invoke-SilentInstaller {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $Process = Start-Process -FilePath $Executable `
        -ArgumentList (ConvertTo-ProcessArguments -Values $Arguments) `
        -PassThru -Wait -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) {
        throw "Installer failed with exit code $($Process.ExitCode): $Executable"
    }
}

function Get-ProcessWindows {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $ProcessCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $ProcessId
    )
    $WindowCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Window
    )
    return [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.AndCondition]::new($ProcessCondition, $WindowCondition)
    )
}

function Find-WindowByName {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Pattern
    )
    foreach ($Window in (Get-ProcessWindows -ProcessId $ProcessId)) {
        try {
            if ($Window.Current.Name -match $Pattern) {
                return $Window
            }
        } catch [System.Windows.Automation.ElementNotAvailableException] {
            continue
        }
    }
    return $null
}

function Find-Button {
    param(
        [Parameter(Mandatory = $true)]
        [System.Windows.Automation.AutomationElement]$Window,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $Condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        $Name
    )
    $ButtonCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
    )
    return $Window.FindFirst(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.AndCondition]::new($Condition, $ButtonCondition)
    )
}

function Close-Window {
    param(
        [Parameter(Mandatory = $true)]
        [System.Windows.Automation.AutomationElement]$Window
    )
    try {
        $Pattern = $Window.GetCurrentPattern(
            [System.Windows.Automation.WindowPattern]::Pattern
        )
        ([System.Windows.Automation.WindowPattern]$Pattern).Close()
        return $true
    } catch [System.Windows.Automation.ElementNotAvailableException] {
        return $true
    } catch {
        Write-Verbose "Could not close UI Automation window: $($_.Exception.Message)"
        return $false
    }
}

function Invoke-Button {
    param(
        [Parameter(Mandatory = $true)]
        [System.Windows.Automation.AutomationElement]$Window,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $Button = Find-Button -Window $Window -Name $Name
    if ($null -eq $Button) {
        $Names = @()
        try {
            $Elements = $Window.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition
            )
            foreach ($Element in $Elements) {
                try {
                    if ($Element.Current.Name) { $Names += $Element.Current.Name }
                } catch [System.Windows.Automation.ElementNotAvailableException] {
                    continue
                }
            }
        } catch [System.Windows.Automation.ElementNotAvailableException] {}
        throw "Could not find '$Name' button. Accessible controls: $($Names -join ' | ')"
    }
    $Pattern = $Button.GetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern
    )
    ([System.Windows.Automation.InvokePattern]$Pattern).Invoke()
}

function Wait-ForProcessWindow {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [int]$TimeoutSeconds = 120
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "ZomboidSorter exited during startup with code $($Process.ExitCode)."
        }
        foreach ($Window in (Get-ProcessWindows -ProcessId $Process.Id)) {
            try {
                if ($Window.Current.Name -match $Pattern) { return $Window }
            } catch [System.Windows.Automation.ElementNotAvailableException] {
                continue
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for ZomboidSorter window matching '$Pattern'."
}

function Get-InstalledAppProcess {
    param([Parameter(Mandatory = $true)][int]$ExcludeProcessId)
    $ExpectedExecutable = [System.IO.Path]::GetFullPath(
        (Join-Path $InstallDirectory 'ZomboidSorter.exe')
    )
    $ExpectedExecutable = $ExpectedExecutable.TrimEnd('\')
    $Candidates = @{}
    try {
        foreach ($Candidate in (Get-CimInstance Win32_Process `
                -Filter "Name = 'ZomboidSorter.exe'" -ErrorAction Stop)) {
            $Candidates[[int]$Candidate.ProcessId] = [string]$Candidate.ExecutablePath
        }
    } catch {
        Write-Verbose "CIM process lookup failed: $($_.Exception.Message)"
    }
    foreach ($Process in (Get-Process -Name 'ZomboidSorter' -ErrorAction SilentlyContinue)) {
        if (-not $Candidates.ContainsKey($Process.Id)) {
            $Candidates[$Process.Id] = ''
        }
    }
    foreach ($CandidateId in @($Candidates.Keys)) {
        if ([int]$CandidateId -eq $ExcludeProcessId) {
            continue
        }
        $CandidatePath = [string]$Candidates[$CandidateId]
        $Process = Get-Process -Id ([int]$CandidateId) -ErrorAction SilentlyContinue
        if ($null -eq $Process) { continue }
        if (-not $CandidatePath) {
            try { $CandidatePath = [string]$Process.MainModule.FileName } catch {}
        }
        if ($CandidatePath) {
            try {
                if ($CandidatePath.StartsWith('\\?\', [StringComparison]::Ordinal) -or
                    $CandidatePath.StartsWith('\??\', [StringComparison]::Ordinal)) {
                    $CandidatePath = $CandidatePath.Substring(4)
                }
                $CandidatePath = [System.IO.Path]::GetFullPath($CandidatePath).TrimEnd('\')
            } catch {
                continue
            }
            if ($CandidatePath -ieq $ExpectedExecutable -or
                $CandidatePath -match ([regex]::Escape($RunId) + '\\ZomboidSorter\.exe$')) {
                return $Process
            }
            continue
        }
        # A fresh hosted runner has no other app instance. If Windows denies
        # access to the image path, accept only a process started at handoff.
        if ($null -ne $UpdateHandoffTime) {
            try {
                $Process.Refresh()
                if ($Process.StartTime.ToUniversalTime() -ge $UpdateHandoffTime.AddSeconds(-2)) {
                    return $Process
                }
            } catch {}
        }
    }
    return $null
}

function Save-SmokeDiagnostics {
    $Lines = [System.Collections.Generic.List[string]]::new()
    $Lines.Add("Failure time (UTC): $([DateTime]::UtcNow.ToString('o'))")
    $Lines.Add("Install directory: $InstallDirectory")
    $Lines.Add("Expected build ID: $ExpectedBuildId")
    $BuildIdPath = Join-Path $InstallDirectory 'BUILD_ID'
    if (Test-Path -LiteralPath $BuildIdPath -PathType Leaf) {
        $Lines.Add("Installed build ID: $([System.IO.File]::ReadAllText($BuildIdPath).Trim())")
    } else {
        $Lines.Add('Installed build ID: missing')
    }

    $ReceiptPath = Join-Path $AppDataRoot 'ZomboidSorter\update-result.json'
    if (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) {
        $Lines.Add("Update receipt: $([System.IO.File]::ReadAllText($ReceiptPath))")
    } else {
        $Lines.Add('Update receipt: missing or already consumed')
    }
    $HelperLogPath = Join-Path $TemporaryDirectory 'ZomboidSorter-update-error.txt'
    if (Test-Path -LiteralPath $HelperLogPath -PathType Leaf) {
        $Lines.Add("Updater helper log: $([System.IO.File]::ReadAllText($HelperLogPath))")
    } else {
        $Lines.Add('Updater helper log: missing')
    }

    $Lines.Add('ZomboidSorter process candidates:')
    try {
        foreach ($Candidate in (Get-CimInstance Win32_Process `
                -Filter "Name = 'ZomboidSorter.exe'" -ErrorAction Stop)) {
            $Lines.Add("  PID=$($Candidate.ProcessId) image=$($Candidate.ExecutablePath) command=$($Candidate.CommandLine)")
        }
    } catch {
        $Lines.Add("  CIM process query failed: $($_.Exception.Message)")
    }
    foreach ($Process in (Get-Process -Name 'ZomboidSorter' -ErrorAction SilentlyContinue)) {
        $Title = ''
        try { $Title = $Process.MainWindowTitle } catch {}
        $Lines.Add("  PID=$($Process.Id) start=$($Process.StartTime.ToString('o')) title=$Title")
        foreach ($Window in (Get-ProcessWindows -ProcessId $Process.Id)) {
            try { $Lines.Add("    UIA window: $($Window.Current.Name)") } catch {}
        }
    }
    $DiagnosticPath = Join-Path $RunRootFull 'smoke-diagnostics.txt'
    [System.IO.File]::WriteAllLines($DiagnosticPath, $Lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Updater smoke diagnostics: $DiagnosticPath"
    Get-Content -LiteralPath $DiagnosticPath
}

try {
    New-Item -ItemType Directory -Path $InstallDirectory | Out-Null
    Invoke-SilentInstaller -Executable $PreviousInstallerPath -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
        '/TYPE=portable', "/DIR=$InstallDirectory"
    )
    $AppExecutable = Join-Path $InstallDirectory 'ZomboidSorter.exe'
    $BuildIdPath = Join-Path $InstallDirectory 'BUILD_ID'
    if (-not (Test-Path -LiteralPath $AppExecutable -PathType Leaf) -or
        -not (Test-Path -LiteralPath $BuildIdPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $InstallDirectory 'portable.flag') -PathType Leaf)) {
        throw 'The previous portable installer did not produce a valid app installation.'
    }
    $PreviousBuildId = [System.IO.File]::ReadAllText($BuildIdPath).Trim().ToLowerInvariant()
    if ($PreviousBuildId -eq $ExpectedBuildId.ToLowerInvariant()) {
        throw 'The previous stable installer unexpectedly matches the rolling build ID.'
    }

    New-Item -ItemType Directory -Path $ProfilesDirectory -Force | Out-Null
    $ProfilePath = Join-Path $ProfilesDirectory 'Update Smoke.json'
    $ProfileBytes = [System.Text.Encoding]::UTF8.GetBytes(
        "{`"schemaVersion`":3,`"name`":`"Update Smoke`",`"modIds`":[],`"workshopIds`":[],`"mapIds`":[]}`n"
    )
    [System.IO.File]::WriteAllBytes($ProfilePath, $ProfileBytes)
    $SettingsPath = Join-Path $DataDirectory 'settings.ini'
    $SettingsText = "[smoke]`npreserve=rolling-update-sentinel-$RunId`n"
    [System.IO.File]::WriteAllText(
        $SettingsPath,
        $SettingsText,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host "Starting previous stable app $PreviousBuildId from $InstallDirectory."
    $OldProcess = Start-Process -FilePath $AppExecutable `
        -WorkingDirectory $InstallDirectory -PassThru
    [void]$OwnedProcessIds.Add($OldProcess.Id)
    $OldWindow = Wait-ForProcessWindow -Process $OldProcess -Pattern 'ZomboidSorter'
    Invoke-Button -Window $OldWindow -Name 'Check for Updates'

    Write-Host 'Waiting for the old app to download the rolling installer and hand it to the updater.'
    $OldExitDeadline = [DateTime]::UtcNow.AddMinutes(15)
    while ([DateTime]::UtcNow -lt $OldExitDeadline) {
        $OldProcess.Refresh()
        if ($OldProcess.HasExited) { break }
        foreach ($FailureTitle in @(
            '^Update Check Failed$',
            '^Update Download Failed$',
            '^Could Not Start Installer$'
        )) {
            $FailureDialog = Find-WindowByName -ProcessId $OldProcess.Id -Pattern $FailureTitle
            if ($null -ne $FailureDialog) {
                throw "The previous app update flow stopped at '$($FailureDialog.Current.Name)'."
            }
        }
        Start-Sleep -Milliseconds 500
    }
    $OldProcess.Refresh()
    if (-not $OldProcess.HasExited) {
        throw 'The old app did not exit after starting its update.'
    }
    if ($OldProcess.ExitCode -ne 0) {
        throw "The old app exited with code $($OldProcess.ExitCode) during update handoff."
    }
    $UpdateHandoffTime = [DateTime]::UtcNow
    Write-Host "Previous app exited at $($UpdateHandoffTime.ToString('o')); waiting for the updated process."

    $Deadline = [DateTime]::UtcNow.AddMinutes(8)
    $NewProcess = $null
    $UpdateDialog = $null
    while ([DateTime]::UtcNow -lt $Deadline) {
        $NewProcess = Get-InstalledAppProcess -ExcludeProcessId $OldProcess.Id
        if ($null -ne $NewProcess) {
            [void]$OwnedProcessIds.Add($NewProcess.Id)
            $UpdateDialog = Find-WindowByName -ProcessId $NewProcess.Id -Pattern '^Update Complete$'
            $FailureDialog = Find-WindowByName -ProcessId $NewProcess.Id -Pattern '^Update Needs Attention$'
            if ($null -ne $FailureDialog) {
                throw 'The relaunched app reported that the update could not be verified.'
            }
            if ($null -ne $UpdateDialog) { break }
        }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $NewProcess -or $null -eq $UpdateDialog) {
        throw 'The updater did not relaunch the app with a successful update receipt.'
    }

    $InstalledBuildId = [System.IO.File]::ReadAllText($BuildIdPath).Trim().ToLowerInvariant()
    if ($InstalledBuildId -ne $ExpectedBuildId.ToLowerInvariant()) {
        throw "Installed build ID $InstalledBuildId does not match expected $ExpectedBuildId."
    }
    $MainWindow = Wait-ForProcessWindow -Process $NewProcess `
        -Pattern "ZomboidSorter v$([regex]::Escape($ExpectedVersion))" -TimeoutSeconds 45
    Invoke-Button -Window $UpdateDialog -Name 'OK'
    $DialogCloseDeadline = [DateTime]::UtcNow.AddSeconds(8)
    while ([DateTime]::UtcNow -lt $DialogCloseDeadline) {
        $VisibleUpdateDialog = Find-WindowByName -ProcessId $NewProcess.Id `
            -Pattern '^Update Complete$'
        if ($null -eq $VisibleUpdateDialog) { break }
        [void](Close-Window -Window $VisibleUpdateDialog)
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne (Find-WindowByName -ProcessId $NewProcess.Id -Pattern '^Update Complete$')) {
        throw 'The update success dialog did not close after confirmation.'
    }

    if (-not (Test-Path -LiteralPath $ProfilePath -PathType Leaf) -or
        [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($ProfilePath)) -cne
        [Convert]::ToBase64String($ProfileBytes)) {
        throw 'The updater did not preserve the seeded portable Mod Pack.'
    }
    $ActualSettings = [System.IO.File]::ReadAllText($SettingsPath)
    if ($ActualSettings -notmatch [regex]::Escape("preserve=rolling-update-sentinel-$RunId")) {
        throw 'The updater did not preserve the portable settings sentinel.'
    }
    $ReceiptPath = Join-Path $AppDataRoot 'ZomboidSorter\update-result.json'
    if (Test-Path -LiteralPath $ReceiptPath) {
        throw 'The new app did not consume its successful update receipt.'
    }

    $NewProcess.Refresh()
    if (-not $NewProcess.CloseMainWindow()) {
        [void](Close-Window -Window $MainWindow)
    }
    if (-not $NewProcess.WaitForExit(30000)) {
        throw 'The updated app did not close cleanly after the success dialog was dismissed.'
    }
    if ($NewProcess.ExitCode -ne 0) {
        throw "The updated app exited with code $($NewProcess.ExitCode)."
    }

    $Uninstaller = Join-Path $InstallDirectory 'unins000.exe'
    Invoke-SilentInstaller -Executable $Uninstaller -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    )
    if (Test-Path -LiteralPath $AppExecutable) {
        throw 'Updater smoke uninstall left the app executable behind.'
    }
    if (-not (Test-Path -LiteralPath $ProfilePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) {
        throw 'Uninstall removed the portable data that the update had preserved.'
    }

    $Completed = $true
    Write-Host "Rolling updater smoke test passed: v$ExpectedVersion ($ExpectedBuildId), old app button handoff, verified relaunch, and portable data preservation."
} catch {
    Write-Host "Rolling updater smoke test failed: $($_.Exception.Message)"
    try { Save-SmokeDiagnostics } catch {
        Write-Host "Could not save updater smoke diagnostics: $($_.Exception.Message)"
    }
    throw
} finally {
    foreach ($ProcessId in $OwnedProcessIds) {
        $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $Process -and -not $Process.HasExited) {
            $Process.Kill()
            [void]$Process.WaitForExit(5000)
        }
    }
    if ($Completed) {
        $ResolvedRunRoot = [System.IO.Path]::GetFullPath($RunRootFull)
        $ResolvedRunnerTempPrefix = [System.IO.Path]::GetFullPath($RunnerTemp).TrimEnd('\') + '\'
        if ($ResolvedRunRoot.StartsWith($ResolvedRunnerTempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $ResolvedRunRoot).StartsWith('ZomboidSorter-update-smoke-', [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ResolvedRunRoot -Recurse -Force
        }
    } else {
        Write-Host "Updater smoke-test data and logs retained for diagnosis: $RunRootFull"
    }
}
