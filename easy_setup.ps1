[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Install", "Preview", "Draft")]
    [string]$Action
)

$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$senderPath = Join-Path $projectPath "send_wechat_time.py"
$setupPath = Join-Path $projectPath "setup_daily_task.ps1"
$previewPath = Join-Path $projectPath "timeout_screenshot_preview.png"
$configPath = Join-Path $projectPath ".wechat_easy_config.json"

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

function Get-RequiredPythonPath {
    $pythonPath = Resolve-PythonPath
    if (-not $pythonPath) {
        throw "Python 3 was not found. Install Python from python.org, select 'Add Python to PATH', and then double-click INSTALL.bat."
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

function Read-GraceMinutes {
    param([int]$DefaultValue)

    while ($true) {
        $value = Read-Host "Allowed delay in minutes (1 to 60) [$DefaultValue]"
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $DefaultValue
        }

        $parsedValue = 0
        if ([int]::TryParse($value, [ref]$parsedValue) -and
            $parsedValue -ge 1 -and $parsedValue -le 60) {
            return $parsedValue
        }
        Write-Host "Enter a whole number from 1 to 60." -ForegroundColor Yellow
    }
}

function Install-Automation {
    Show-Header "Beginner installation"

    Write-Host "This will install the required Python packages and create a"
    Write-Host "Monday-to-Friday Windows scheduled task for your account."
    Write-Host "It will not send a WeChat message during installation."
    Write-Host ""

    $savedConfig = Get-SavedConfig
    $defaultContact = "Attedance Recording"
    $defaultTime = "18:00"
    $defaultGrace = 5

    if ($savedConfig) {
        if (-not [string]::IsNullOrWhiteSpace([string]$savedConfig.contact)) {
            $defaultContact = [string]$savedConfig.contact
        }
        if ([string]$savedConfig.send_time -match "^(?:[01]\d|2[0-3]):[0-5]\d$") {
            $defaultTime = [string]$savedConfig.send_time
        }
        $savedGrace = 0
        if ([int]::TryParse([string]$savedConfig.grace_minutes, [ref]$savedGrace) -and
            $savedGrace -ge 1 -and $savedGrace -le 60) {
            $defaultGrace = $savedGrace
        }
    }

    $contact = Read-ContactName -DefaultValue $defaultContact
    Write-Host ""
    $sendTime = Read-SendTime -DefaultValue $defaultTime
    $graceMinutes = Read-GraceMinutes -DefaultValue $defaultGrace

    Write-Host ""
    Write-Host "Please confirm:" -ForegroundColor Cyan
    Write-Host "  WeChat contact: $contact"
    Write-Host "  Weekdays at:    $sendTime"
    Write-Host "  Allowed delay:  $graceMinutes minute(s)"
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

try {
    switch ($Action) {
        "Install" { Install-Automation }
        "Preview" { Show-Preview }
        "Draft" { Create-Draft }
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
