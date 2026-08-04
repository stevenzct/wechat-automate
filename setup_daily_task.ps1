[CmdletBinding()]
param(
    [Parameter()]
    [ValidateScript({ -not [string]::IsNullOrWhiteSpace($_) })]
    [string]$ContactName = "Attedance Recording",

    [Parameter()]
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$SendTime = "18:00",

    [Parameter()]
    [ValidateRange(1, 60)]
    [int]$GraceMinutes = 5
)

$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectPath "send_wechat_time.py"
$requirementsPath = Join-Path $projectPath "requirements.txt"

function Resolve-PythonPath {
    $portablePython = Join-Path $projectPath ".runtime\python\python.exe"
    if (Test-Path -LiteralPath $portablePython) {
        $detectedPython = & $portablePython -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $detectedPython) {
            return ([string]$detectedPython).Trim()
        }
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $detectedPython = & $pythonCommand.Source -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $detectedPython) {
            $resolvedPath = ([string]$detectedPython).Trim()
            if (Test-Path -LiteralPath $resolvedPath) {
                return $resolvedPath
            }
        }
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $detectedPython = & $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $detectedPython) {
            $resolvedPath = ([string]$detectedPython).Trim()
            if (Test-Path -LiteralPath $resolvedPath) {
                return $resolvedPath
            }
        }
    }

    return $null
}

$pythonPath = Resolve-PythonPath
if (-not $pythonPath) {
    throw "Python 3 was not found. Install it from python.org with 'Add Python to PATH' selected, then run this setup again."
}

Write-Host "Installing Python packages..."
& $pythonPath -m pip install --disable-pip-version-check -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Package installation failed."
}

Write-Host "Checking the automation..."
& $pythonPath $scriptPath --check --contact $ContactName --send-time $SendTime
if ($LASTEXITCODE -ne 0) {
    throw "The automation check failed. Review the error above before scheduling it."
}

$taskName = "Send WeChat Attendance Screenshot at 6 PM"
$escapedContact = $ContactName.Replace('"', '\"')
$arguments = ('"{0}" --scheduled --weekdays-only --contact "{1}" --send-time {2} --grace-minutes {3}' -f `
    $scriptPath, $escapedContact, $SendTime, $GraceMinutes)
$scheduleTime = [datetime]::ParseExact(
    $SendTime,
    "HH:mm",
    [Globalization.CultureInfo]::InvariantCulture
)

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument $arguments `
    -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $scheduleTime
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes ($GraceMinutes + 5))

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Open the Windows date/time flyout and send the screenshot to $ContactName at $SendTime, Monday through Friday." `
    -Force | Out-Null

Write-Host ""
Write-Host "Done. '$taskName' will send to '$ContactName' Monday-Friday at $SendTime."
Write-Host "Keep the laptop awake, unlocked, and signed in to WeChat at that time."
Write-Host "Safe screenshot test:"
Write-Host "  & '$pythonPath' '$scriptPath' --preview"
Write-Host "Safe WeChat draft test (pastes but does not send):"
Write-Host "  & '$pythonPath' '$scriptPath' --send-now --draft-only --contact '$ContactName'"
