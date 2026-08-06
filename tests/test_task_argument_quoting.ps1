[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$setupScriptPath = Join-Path $PSScriptRoot "..\setup_daily_task.ps1"
$tokens = $null
$parseErrors = $null
$setupAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $setupScriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    throw "setup_daily_task.ps1 could not be parsed: $($parseErrors[0].Message)"
}

# Load only the pure quoting helper from setup_daily_task.ps1. Dot-sourcing the
# complete installer would install packages and register tasks, which this test
# must never do.
$quotingFunctionAst = $setupAst.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "ConvertTo-WindowsCommandLineArgument"
    },
    $true
)
if (-not $quotingFunctionAst) {
    throw "ConvertTo-WindowsCommandLineArgument was not found."
}
Invoke-Expression $quotingFunctionAst.Extent.Text

if (-not ("TaskArgumentNativeMethods" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class TaskArgumentNativeMethods
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CommandLineToArgvW(
        string commandLine,
        out int argumentCount);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LocalFree(IntPtr memory);
}
"@
}

function ConvertFrom-WindowsCommandLine {
    param(
        [Parameter(Mandatory)]
        [string]$CommandLine
    )

    $argumentCount = 0
    $argumentVector = [TaskArgumentNativeMethods]::CommandLineToArgvW(
        $CommandLine,
        [ref]$argumentCount
    )
    if ($argumentVector -eq [IntPtr]::Zero) {
        throw "CommandLineToArgvW failed with Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())."
    }

    try {
        for ($index = 0; $index -lt $argumentCount; $index++) {
            $argumentPointer = [Runtime.InteropServices.Marshal]::ReadIntPtr(
                $argumentVector,
                $index * [IntPtr]::Size
            )
            [Runtime.InteropServices.Marshal]::PtrToStringUni($argumentPointer)
        }
    }
    finally {
        [void][TaskArgumentNativeMethods]::LocalFree($argumentVector)
    }
}

$samples = @(
    @{ Name = "empty"; Value = "" }
    @{ Name = "plain"; Value = "Attendance" }
    @{ Name = "spaces"; Value = "Attendance Recording" }
    @{ Name = "leading and trailing spaces"; Value = " Attendance Recording " }
    @{ Name = "embedded quote"; Value = 'Attendance "Recording"' }
    @{ Name = "backslash before quote"; Value = 'Attendance\"Recording' }
    @{ Name = "trailing backslash"; Value = 'Attendance\' }
    @{ Name = "multiple trailing backslashes"; Value = 'Attendance\\' }
)

foreach ($sample in $samples) {
    $quotedValue = ConvertTo-WindowsCommandLineArgument $sample.Value
    $parsedArguments = @(
        ConvertFrom-WindowsCommandLine ("python.exe {0}" -f $quotedValue)
    )
    if ($parsedArguments.Count -ne 2) {
        throw "$($sample.Name): expected two arguments but parsed $($parsedArguments.Count)."
    }
    if ($parsedArguments[1] -cne $sample.Value) {
        throw "$($sample.Name): expected '$($sample.Value)' but parsed '$($parsedArguments[1])'."
    }
}

Write-Host "Task action argument quoting: $($samples.Count) cases passed."
