[CmdletBinding()]
param(
    [Parameter()]
    [ValidateScript({ -not [string]::IsNullOrWhiteSpace($_) })]
    [string]$ContactName = "Attedance Recording",

    [Parameter()]
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$SendTime = "18:00",

    [Parameter()]
    [ValidateRange(0, 60)]
    [int]$GraceMinutes = 0
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

function ConvertTo-XmlText {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Value
    )

    return [Security.SecurityElement]::Escape($Value)
}

function ConvertTo-WindowsCommandLineArgument {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Value
    )

    # Task Scheduler stores Exec arguments as one Windows command-line string.
    # Quote every value using the CommandLineToArgvW/CRT backslash rules so
    # embedded quotes and trailing backslashes survive as one exact argument.
    $quoted = New-Object System.Text.StringBuilder
    [void]$quoted.Append([char]34)
    $backslashCount = 0

    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashCount++
            continue
        }

        if ($character -eq [char]34) {
            [void]$quoted.Append([char]92, (($backslashCount * 2) + 1))
            [void]$quoted.Append([char]34)
        }
        else {
            if ($backslashCount -gt 0) {
                [void]$quoted.Append([char]92, $backslashCount)
            }
            [void]$quoted.Append($character)
        }
        $backslashCount = 0
    }

    if ($backslashCount -gt 0) {
        [void]$quoted.Append([char]92, ($backslashCount * 2))
    }
    [void]$quoted.Append([char]34)
    return $quoted.ToString()
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

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $currentIdentity.User) {
    throw "The current Windows user SID could not be determined."
}
$currentUserSid = $currentIdentity.User.Value

$taskName = "Send WeChat Attendance Screenshot at 6 PM"
$timeInTaskName = "Send WeChat Attendance Time In at Laptop Open"
$quotedScriptPath = ConvertTo-WindowsCommandLineArgument $scriptPath
$quotedContact = ConvertTo-WindowsCommandLineArgument $ContactName
$arguments = ('{0} --scheduled --weekdays-only --contact {1} --send-time {2} --grace-minutes {3}' -f `
    $quotedScriptPath, $quotedContact, $SendTime, $GraceMinutes)
$timeInArguments = ('{0} --time-in --contact {1}' -f `
    $quotedScriptPath, $quotedContact)
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
    -UserId $currentUserSid `
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
    -Description "Send the Windows date/time screenshot to $ContactName at $SendTime on Philippine workdays, excluding nationwide regular and special non-working holidays." `
    -Force | Out-Null

$xmlUserSid = ConvertTo-XmlText $currentUserSid
$xmlPythonPath = ConvertTo-XmlText $pythonPath
$xmlTimeInArguments = ConvertTo-XmlText $timeInArguments
$xmlProjectPath = ConvertTo-XmlText $projectPath
$xmlTimeInDescription = ConvertTo-XmlText (
    "Send a Windows date/time screenshot to $ContactName once per Philippine " +
    "workday after this user logs on or unlocks the laptop."
)

# New-ScheduledTaskTrigger has no workstation-unlock option. Register this task
# from XML so a resumed laptop is covered as well as a fresh Windows logon. The
# delay gives Explorer, the taskbar, and WeChat time to become interactive.
$timeInTaskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$xmlTimeInDescription</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$xmlUserSid</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled>
      <UserId>$xmlUserSid</UserId>
      <Delay>PT30S</Delay>
      <StateChange>SessionUnlock</StateChange>
    </SessionStateChangeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$xmlUserSid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$xmlPythonPath</Command>
      <Arguments>$xmlTimeInArguments</Arguments>
      <WorkingDirectory>$xmlProjectPath</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

# Validate the interpolated XML before registering the time-in task.
$validatedTimeInTaskXml = [xml]$timeInTaskXml
Register-ScheduledTask `
    -TaskName $timeInTaskName `
    -Xml $validatedTimeInTaskXml.OuterXml `
    -Force | Out-Null

Enable-ScheduledTask -TaskName $taskName | Out-Null
Enable-ScheduledTask -TaskName $timeInTaskName | Out-Null

Write-Host ""
Write-Host "Done. '$taskName' will send to '$ContactName' on Philippine workdays at $SendTime."
Write-Host "'$timeInTaskName' will send once per workday after logon or laptop unlock."
Write-Host "Regular and special non-working holidays are skipped; special working holidays continue."
Write-Host "Keep the laptop awake, unlocked, and signed in to WeChat at that time."
Write-Host "Safe screenshot test:"
Write-Host "  & '$pythonPath' '$scriptPath' --preview"
Write-Host "Safe WeChat draft test (pastes but does not send):"
Write-Host "  & '$pythonPath' '$scriptPath' --send-now --draft-only --contact '$ContactName'"
