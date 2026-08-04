[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Install", "Preview", "Draft", "Disable")]
    [string]$Action
)

$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$senderPath = Join-Path $projectPath "send_wechat_time.py"
$setupPath = Join-Path $projectPath "setup_daily_task.ps1"
$previewPath = Join-Path $projectPath "timeout_screenshot_preview.png"
$configPath = Join-Path $projectPath ".wechat_easy_config.json"
$taskName = "Send WeChat Attendance Screenshot at 6 PM"

function Show-Header {
    param([string]$Title)

    Clear-Host
    Write-Host "===============================================" -ForegroundColor Cyan
    Write-Host " WeChat Attendance Screenshot" -ForegroundColor Cyan
    Write-Host " $Title" -ForegroundColor Cyan
    Write-Host "===============================================" -ForegroundColor Cyan
    Write-Host ""
}

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

function Refresh-ProcessPath {
    $pathValues = @(
        $env:Path
        [Environment]::GetEnvironmentVariable("Path", "User")
        [Environment]::GetEnvironmentVariable("Path", "Machine")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:Path = $pathValues -join ";"
}

function Resolve-WingetPath {
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($wingetCommand) {
        return $wingetCommand.Source
    }

    if ($env:LOCALAPPDATA) {
        $appAlias = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\winget.exe"
        try {
            if (Test-Path -LiteralPath $appAlias) {
                return $appAlias
            }
        }
        catch {
            # Continue to the packaged App Installer lookup.
        }
    }

    try {
        $appInstaller = Get-AppxPackage -Name Microsoft.DesktopAppInstaller |
            Sort-Object Version -Descending |
            Select-Object -First 1
        if ($appInstaller.InstallLocation) {
            $packagedWinget = Join-Path $appInstaller.InstallLocation "winget.exe"
            if (Test-Path -LiteralPath $packagedWinget) {
                return $packagedWinget
            }
        }
    }
    catch {
        # The caller provides a beginner-friendly recovery message.
    }

    return $null
}

function Get-WeChatExecutablePath {
    $candidates = @()
    if ($env:WECHAT_PATH) {
        $candidates += $env:WECHAT_PATH
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "Tencent\Weixin\Weixin.exe")
        $candidates += (Join-Path $env:ProgramFiles "Tencent\WeChat\WeChat.exe")
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "Tencent\WeChat\WeChat.exe")
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Tencent\Weixin\Weixin.exe")
        $candidates += (Join-Path $env:LOCALAPPDATA "Tencent\WeChat\WeChat.exe")
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Install-WingetPackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WingetPath,

        [Parameter(Mandatory = $true)]
        [string]$PackageId,

        [Parameter(Mandatory = $true)]
        [string]$DisplayName
    )

    Write-Host ""
    Write-Host "Downloading and installing $DisplayName..." -ForegroundColor Cyan
    $wingetArguments = @(
        "install"
        "--id", $PackageId
        "--exact"
        "--source", "winget"
        "--accept-source-agreements"
        "--accept-package-agreements"
        "--silent"
        "--disable-interactivity"
    )
    $installOutput = & $WingetPath @wingetArguments 2>&1
    $installExitCode = $LASTEXITCODE
    $installOutput | ForEach-Object { Write-Host $_ }
    if ($installExitCode -ne 0) {
        throw "$DisplayName could not be installed automatically (winget exit code $installExitCode)."
    }
}

function Ensure-RequiredApplications {
    $pythonPath = Resolve-PythonPath
    $wechatPath = Get-WeChatExecutablePath
    $missingApplications = @()
    if (-not $pythonPath) {
        $missingApplications += "Python 3"
    }
    if (-not $wechatPath) {
        $missingApplications += "WeChat/Weixin desktop"
    }

    if ($missingApplications.Count -eq 0) {
        Write-Host "Python and WeChat/Weixin are already installed." -ForegroundColor Green
        return $true
    }

    Write-Host "The installer found missing required app(s):" -ForegroundColor Yellow
    $missingApplications | ForEach-Object { Write-Host "  - $_" }
    Write-Host ""
    Write-Host "INSTALL.bat can download them from the official Windows Package Manager."
    Write-Host "A Windows permission prompt may appear during installation."
    Write-Host ""
    $confirmation = Read-Host "Type YES to download and install the missing app(s)"
    if ($confirmation -cne "YES") {
        Write-Host "Installation cancelled. Nothing was downloaded." -ForegroundColor Yellow
        return $false
    }

    $wingetPath = Resolve-WingetPath
    if (-not $wingetPath) {
        try {
            Start-Process "ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1"
        }
        catch {
            # The instructions below remain useful if the Store cannot open.
        }
        throw "Windows Package Manager is missing. The Microsoft Store was opened to App Installer. Install or update App Installer, then run INSTALL.bat again."
    }

    if (-not $pythonPath) {
        Install-WingetPackage `
            -WingetPath $wingetPath `
            -PackageId "Python.Python.3.13" `
            -DisplayName "Python 3.13"
        Refresh-ProcessPath
        $pythonPath = Resolve-PythonPath
        if (-not $pythonPath) {
            throw "Python was installed but could not be detected yet. Restart Windows, then run INSTALL.bat again."
        }
    }

    if (-not $wechatPath) {
        Install-WingetPackage `
            -WingetPath $wingetPath `
            -PackageId "Tencent.WeChat.Universal" `
            -DisplayName "WeChat for Windows"
        $wechatPath = Get-WeChatExecutablePath
        if (-not $wechatPath) {
            throw "WeChat was installed but its executable could not be detected. Restart Windows, then run INSTALL.bat again."
        }
    }

    Write-Host ""
    Write-Host "All required applications are installed." -ForegroundColor Green
    return $true
}

function Wait-ForWeChatSignin {
    $wechatPath = Get-WeChatExecutablePath
    if (-not $wechatPath) {
        throw "WeChat/Weixin could not be found after the prerequisite check."
    }

    $wechatProcess = Get-Process -Name WeChat, Weixin -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $wechatProcess) {
        try {
            Start-Process -FilePath $wechatPath
        }
        catch {
            throw "WeChat is installed but could not be opened. Open it manually, then run INSTALL.bat again."
        }
    }

    Write-Host ""
    Write-Host "WeChat must be signed in before setup can continue." -ForegroundColor Cyan
    Write-Host "If WeChat asks, scan the QR code or approve the login on your phone."
    Write-Host "INSTALL.bat will never ask for your WeChat password."
    [void](Read-Host "When the main WeChat chat window is open, press Enter here")
}

function Get-RequiredPythonPath {
    $pythonPath = Resolve-PythonPath
    if (-not $pythonPath) {
        throw "Python 3 was not found. Double-click INSTALL.bat first; it can install Python automatically."
    }
    return $pythonPath
}

function Get-SavedConfig {
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    }
    catch {
        Write-Host "The saved beginner settings could not be read; defaults will be used." -ForegroundColor Yellow
        return $null
    }
}

function Read-ContactName {
    param([string]$DefaultValue)

    while ($true) {
        Write-Host "Enter the exact WeChat contact or group name." -ForegroundColor White
        Write-Host "The spelling must match WeChat exactly." -ForegroundColor DarkGray
        $value = Read-Host "Contact name [$DefaultValue]"
        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = $DefaultValue
        }
        $value = $value.Trim()
        if ($value) {
            return $value
        }
        Write-Host "The contact name cannot be blank." -ForegroundColor Yellow
    }
}

function Read-SendTime {
    param([string]$DefaultValue)

    while ($true) {
        $value = Read-Host "Weekday send time in 24-hour HH:MM format [$DefaultValue]"
        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = $DefaultValue
        }
        if ($value -match "^(?:[01]\d|2[0-3]):[0-5]\d$") {
            return $value
        }
        Write-Host "Enter a valid time such as 18:00 for 6:00 PM." -ForegroundColor Yellow
    }
}

function Install-Automation {
    Show-Header "Beginner installation"

    Write-Host "This will install the required Python packages and create a"
    Write-Host "Monday-to-Friday Windows scheduled task for your account."
    Write-Host "Regular and special non-working Philippine holidays are skipped."
    Write-Host "Special working holidays continue as normal workdays."
    Write-Host "Late task starts after the scheduled clock minute will be skipped."
    Write-Host "It will not send a WeChat message during installation."
    Write-Host ""

    if (-not (Ensure-RequiredApplications)) {
        return
    }
    Wait-ForWeChatSignin
    Write-Host ""

    $savedConfig = Get-SavedConfig
    $defaultContact = "Attedance Recording"
    $defaultTime = "18:00"

    if ($savedConfig) {
        if (-not [string]::IsNullOrWhiteSpace([string]$savedConfig.contact)) {
            $defaultContact = [string]$savedConfig.contact
        }
        if ([string]$savedConfig.send_time -match "^(?:[01]\d|2[0-3]):[0-5]\d$") {
            $defaultTime = [string]$savedConfig.send_time
        }
    }

    $contact = Read-ContactName -DefaultValue $defaultContact
    Write-Host ""
    $sendTime = Read-SendTime -DefaultValue $defaultTime
    $graceMinutes = 0

    Write-Host ""
    Write-Host "Please confirm:" -ForegroundColor Cyan
    Write-Host "  WeChat contact: $contact"
    Write-Host "  Weekdays at:    $sendTime"
    Write-Host "  PH holidays:    skip regular and special non-working only"
    Write-Host "  Late starts:    skipped after the $sendTime clock minute"
    Write-Host ""
    $confirmation = Read-Host "Type YES to install"
    if ($confirmation -cne "YES") {
        Write-Host "Installation cancelled. Nothing was changed." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    & $setupPath `
        -ContactName $contact `
        -SendTime $sendTime `
        -GraceMinutes $graceMinutes

    $savedSettings = [ordered]@{
        contact = $contact
        send_time = $sendTime
        grace_minutes = $graceMinutes
    }
    $savedSettings |
        ConvertTo-Json |
        Set-Content -LiteralPath $configPath -Encoding UTF8

    Write-Host ""
    Write-Host "Installation completed." -ForegroundColor Green
    Write-Host "Holiday protection is active and refreshes future official calendars."
    Write-Host "Next, double-click TEST_PREVIEW.bat to inspect the screenshot."
    Write-Host "After that, double-click TEST_DRAFT.bat to verify the WeChat chat."
}

function Show-Preview {
    Show-Header "Safe screenshot preview"

    Write-Host "This opens the Windows calendar briefly and saves a screenshot."
    Write-Host "It does not open WeChat and cannot send a message."
    Write-Host ""
    Write-Host "Do not move the mouse or use the keyboard until the image opens." -ForegroundColor Yellow
    Write-Host "Starting in 3 seconds..."
    Start-Sleep -Seconds 3

    $pythonPath = Get-RequiredPythonPath
    & $pythonPath $senderPath --preview --output $previewPath
    if ($LASTEXITCODE -ne 0) {
        throw "The screenshot preview failed. Review wechat_sender.log for details."
    }

    Write-Host ""
    Write-Host "Preview created successfully:" -ForegroundColor Green
    Write-Host "  $previewPath"
    Write-Host "Check the image for the correct calendar area and private content."

    try {
        Start-Process -FilePath $previewPath
    }
    catch {
        Write-Host "Windows could not open the image automatically. Open it from the project folder." -ForegroundColor Yellow
    }
}

function Create-Draft {
    Show-Header "Safe WeChat draft test"

    Write-Host "This test opens WeChat, selects a conversation, and pastes the image."
    Write-Host "It DOES NOT press Send." -ForegroundColor Green
    Write-Host "You must inspect and delete the draft manually afterward."
    Write-Host ""

    $savedConfig = Get-SavedConfig
    $defaultContact = "Attedance Recording"
    if ($savedConfig -and
        -not [string]::IsNullOrWhiteSpace([string]$savedConfig.contact)) {
        $defaultContact = [string]$savedConfig.contact
    }

    $contact = Read-ContactName -DefaultValue $defaultContact
    Write-Host ""
    Write-Host "Before continuing:" -ForegroundColor Cyan
    Write-Host "  1. Open WeChat and sign in."
    Write-Host "  2. Close pop-ups or dialogs."
    Write-Host "  3. Stop using the mouse and keyboard during the test."
    Write-Host "  4. Confirm the pasted image is in the correct chat afterward."
    Write-Host ""
    $confirmation = Read-Host "Type YES to create the unsent draft"
    if ($confirmation -cne "YES") {
        Write-Host "Draft test cancelled. Nothing was pasted or sent." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "Starting in 3 seconds..."
    Start-Sleep -Seconds 3

    $pythonPath = Get-RequiredPythonPath
    & $pythonPath $senderPath --send-now --draft-only --contact $contact
    if ($LASTEXITCODE -ne 0) {
        throw "The draft test failed. Review wechat_sender.log and clear any partial draft in WeChat."
    }

    Write-Host ""
    Write-Host "The image was pasted but NOT sent." -ForegroundColor Green
    Write-Host "Check the conversation now, then delete the draft manually."
}

function Disable-Automation {
    Show-Header "Disable automatic sending"

    $scheduledTask = Get-ScheduledTask `
        -TaskName $taskName `
        -ErrorAction SilentlyContinue
    if (-not $scheduledTask) {
        Write-Host "No installed WeChat attendance task was found." -ForegroundColor Yellow
        Write-Host "Nothing needs to be disabled."
        return
    }

    if ($scheduledTask.State -eq "Disabled") {
        Write-Host "Automatic sending is already disabled." -ForegroundColor Green
        Write-Host "Run INSTALL.bat if you want to enable it again."
        return
    }

    Write-Host "This stops all future automatic weekday sends." -ForegroundColor Yellow
    Write-Host "It does not delete the project, logs, previews, or saved settings."
    Write-Host "You can enable it again later by running INSTALL.bat."
    Write-Host ""
    $confirmation = Read-Host "Type YES to disable automatic sending"
    if ($confirmation -cne "YES") {
        Write-Host "Disable cancelled. The scheduled task is still active." -ForegroundColor Yellow
        return
    }

    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Host ""
    Write-Host "Automatic sending is now disabled." -ForegroundColor Green
    Write-Host "No future scheduled messages will run unless INSTALL.bat is used again."
}

try {
    switch ($Action) {
        "Install" { Install-Automation }
        "Preview" { Show-Preview }
        "Draft" { Create-Draft }
        "Disable" { Disable-Automation }
    }
}
catch {
    Write-Host ""
    Write-Host "The action did not complete." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "See README.md and wechat_sender.log for troubleshooting help."
    exit 1
}

exit 0
