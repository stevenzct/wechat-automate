# WeChat Attendance Screenshot Automation

A Windows desktop automation that opens the Windows date/time flyout, captures
the bottom-right corner of the primary display, and sends the image to a chosen
WeChat or Weixin conversation. It is intended for attendance/time-out proof and
can be installed as a Monday-to-Friday Windows scheduled task.

> [!IMPORTANT]
> This project controls the Windows desktop with simulated mouse and keyboard
> input. The computer must be awake, unlocked, and signed in to WeChat when the
> automation runs.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Easiest setup for non-coders](#easiest-setup-for-non-coders)
- [Manual setup with PowerShell](#manual-setup-with-powershell)
- [Safe testing workflow](#safe-testing-workflow)
- [Install the weekday scheduled task](#install-the-weekday-scheduled-task)
- [Configuration](#configuration)
- [Command-line reference](#command-line-reference)
- [Manage the scheduled task](#manage-the-scheduled-task)
- [Logs and exit codes](#logs-and-exit-codes)
- [Safety, privacy, and limitations](#safety-privacy-and-limitations)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Development and verification](#development-and-verification)
- [Publishing on GitHub](#publishing-on-github)

## Features

- Captures a configurable bottom-right screen region with the Windows calendar
  open; the default crop is `500 × 660` pixels.
- Supports full-primary-screen captures when required.
- Sends immediately, creates a safe unsent draft, or runs only during the
  scheduled clock minute.
- Includes guided, double-clickable Windows helpers for installation, preview,
  and unsent draft testing.
- Installs a weekday task through Windows Task Scheduler.
- Finds WeChat by the actual `WeChat.exe` or `Weixin.exe` process rather than by
  trusting a window title.
- Verifies that WeChat remains in the foreground before every keyboard action.
- Refuses to send if the date/time panel does not appear to have opened.
- Uses both a process mutex and Task Scheduler overlap protection to reduce the
  chance of duplicate sends.
- Accounts for Windows display scaling when clicking the taskbar clock.
- Writes operational details and errors to a local UTF-8 log file.

## How it works

1. The script confirms that an interactive Windows desktop is available.
2. It closes any existing flyout, records the target screen region, and clicks
   the primary taskbar clock.
3. It captures the configured region, then compares it with the image taken
   before the click. If the screen did not change enough, it stops instead of
   sending an ordinary desktop screenshot.
4. In preview mode, it saves the image locally and finishes.
5. In a send mode, it finds or starts WeChat, restores its main chat window,
   and verifies that the foreground process is really WeChat/Weixin.
6. It opens WeChat search with `Ctrl+F`, pastes the configured contact name,
   selects the first result, and pastes the screenshot as bitmap data.
7. Draft mode stops here. Otherwise, the script sends with `Alt+S` so it works
   regardless of the user's Enter-key preference in WeChat.

Scheduled runs add two checks before capture: an optional weekday check and an
exact-minute check. By default, a task scheduled for `18:00` may start during
the `18:00` clock minute, but a start at `18:01` or later is logged and skipped.

## Requirements

- Windows 11 with the taskbar clock available on the primary display
- Python 3 and `pip`
- WeChat or Weixin desktop, installed and signed in
- An interactive user session at run time
- Permission to create a scheduled task for the current Windows user

Python packages are listed in [`requirements.txt`](requirements.txt):

- `PyAutoGUI` for mouse, keyboard, and screen capture automation
- `Pillow` for image comparison and encoding
- `pyperclip` for pasting contact names
- `pywin32` for Windows window and clipboard APIs

This project is Windows-only. It uses `ctypes`, Win32 APIs, and Windows Task
Scheduler, so it will not run unchanged on macOS or Linux.

## Easiest setup for non-coders

No programming or command typing is required for the normal setup. The included
`.bat` files open guided windows and ask for the required information.

### Before you begin

The user only needs to download this project:

**[Download the complete project ZIP](https://github.com/stevenzct/wechat-automate/archive/refs/heads/main.zip)**

Open the downloaded ZIP, select **Extract All**, and move the extracted folder
to a permanent location such as `Documents`. Do not run `INSTALL.bat` from
inside the ZIP.

`INSTALL.bat` automatically checks for Python and WeChat/Weixin. If either app
is missing, it lists what is needed and asks the user to type `YES`. It then
downloads and installs the missing apps through the official Windows Package
Manager. A Windows permission prompt may appear.

The user does not need to find separate Python or WeChat download pages.
However, the following are still required:

- A Windows 11 computer with an internet connection
- Windows Package Manager (`winget`), normally included with Windows 11
- An existing WeChat/Weixin account
- A phone available to scan or approve the WeChat desktop sign-in

If Windows Package Manager is missing, `INSTALL.bat` opens the Microsoft Store
page for **App Installer**. Install or update it, then run `INSTALL.bat` again.

The project ZIP already includes every automation file a non-coder needs:

- `INSTALL.bat`
- `TEST_PREVIEW.bat`
- `TEST_DRAFT.bat`
- `easy_setup.ps1`
- `setup_daily_task.ps1`
- `send_wechat_time.py`
- `requirements.txt`

Do **not** download Git, GitHub Desktop, PowerShell, Windows Task Scheduler, or
the Python packages individually. Git is unnecessary for normal use;
PowerShell and Task Scheduler are included with Windows; and `INSTALL.bat`
automatically installs PyAutoGUI, Pillow, pyperclip, and pywin32.

Complete this checklist before running the installer:

- [ ] The computer is running Windows 11 and connected to the internet.
- [ ] The user has a working WeChat/Weixin account and their phone nearby.
- [ ] The project ZIP has been fully extracted.
- [ ] The extracted project folder is in a permanent location.
- [ ] The user understands that WeChat sign-in must be completed manually.

If automatic installation reports that an app cannot be detected yet, restart
Windows once and run `INSTALL.bat` again.

### Step 1: Install the weekday schedule

Double-click [`INSTALL.bat`](INSTALL.bat). It performs the following steps:

1. Detect Python and WeChat/Weixin.
2. Ask permission to download and install any missing required apps.
3. Open WeChat and wait while the user signs in manually.
4. Ask for the contact and weekday time.
5. Install the required Python packages and create the scheduled task.

The guided installer asks for:

- The exact WeChat contact or group name
- The weekday send time, such as `18:00` for 6:00 PM

Review the displayed settings and type `YES` when asked to confirm. The helper
then installs the Python packages, checks the computer, and creates the
Monday-to-Friday scheduled task. Installation does not capture a screenshot or
send a WeChat message.

The choices are saved locally in `.wechat_easy_config.json` so the testing
helper can suggest the same contact. This file is excluded from Git and should
not be uploaded because it can contain a private contact or group name.

To change the contact or time later, double-click `INSTALL.bat` again. The
existing scheduled task will be updated.

### Step 2: Check the screenshot safely

Double-click [`TEST_PREVIEW.bat`](TEST_PREVIEW.bat), then stop using the mouse
and keyboard for a few seconds. The helper briefly opens the Windows calendar,
saves `timeout_screenshot_preview.png`, and opens the image for inspection.

This test does not open WeChat and cannot send a message. Check that the image
shows the intended calendar and does not include private notifications or other
unwanted information.

### Step 3: Check the WeChat conversation safely

Open and sign in to WeChat, then double-click
[`TEST_DRAFT.bat`](TEST_DRAFT.bat). Confirm the exact contact name and type
`YES` when prompted.

The helper captures the calendar, finds the conversation, and pastes the image
as a draft. It does **not** press Send. Verify that the correct conversation was
selected, then delete the pasted draft manually.

### Step 4: Leave the computer ready

At the scheduled weekday time:

- Keep the computer awake and unlocked.
- Stay signed in to the same Windows account that installed the task.
- Keep WeChat signed in.
- Avoid using the mouse or keyboard while the automation is running.

### What happens after successful installation

`INSTALL.bat` creates a permanent Windows scheduled task for the current user.
The user does not need to open this project or run `INSTALL.bat` every day.

- The task runs automatically Monday through Friday at the selected time.
- It remains installed after Windows restarts.
- A task set for `18:00` is accepted only while the clock still reads `18:00`.
- If the computer is asleep, locked, turned off, or starts the task at `18:01`
  or later, that day's message is skipped instead of being sent late.
- The same Windows user must be signed in, and WeChat must remain signed in.
- The project folder must not be moved, renamed, or deleted after installation
  because Task Scheduler stores its full location.
- Running `INSTALL.bat` again safely updates the existing task rather than
  creating a duplicate.

There is intentionally no double-clickable real-send test. This reduces the
risk of a non-technical user accidentally sending a screenshot to the wrong
conversation. Advanced users can perform a real manual send with the PowerShell
command documented below.

| Beginner file | What it does | Can it send? |
| --- | --- | --- |
| `INSTALL.bat` | Installs missing Python/WeChat apps, installs dependencies, validates the setup, and creates or updates the weekday task. | No message is sent during setup. |
| `TEST_PREVIEW.bat` | Captures and opens a local preview without opening WeChat. | No. |
| `TEST_DRAFT.bat` | Pastes the image into a selected WeChat conversation as an unsent draft. | No; it never presses Send. |

## Manual setup with PowerShell

Open PowerShell in the project directory, then create an isolated environment
and install the dependencies:

```powershell
py -3 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
```

Check that the script can find WeChat and read the primary display:

```powershell
python .\send_wechat_time.py --check `
  --contact "Exact WeChat Contact Name" `
  --send-time "18:00"
```

`--check` does not open the calendar, select a chat, paste an image, or send a
message. It reports the detected WeChat executable, display size, contact, and
scheduled time.

## Safe testing workflow

Follow these stages in order, especially after changing the contact name,
display layout, scaling, or WeChat version.

### 1. Preview the capture

```powershell
python .\send_wechat_time.py --preview
```

The screenshot is written to `timeout_screenshot_preview.png`. Inspect the file
and make sure that it contains the intended calendar and taskbar clock without
private notifications or unrelated desktop content.

To use a different output path:

```powershell
python .\send_wechat_time.py --preview `
  --output .\artifacts\calendar-preview.png
```

### 2. Create an unsent WeChat draft

```powershell
python .\send_wechat_time.py --send-now --draft-only `
  --contact "Exact WeChat Contact Name"
```

This opens the matching conversation and pastes the image without pressing
Send. Confirm that the correct chat was selected, then delete the draft
manually.

### 3. Perform a real manual send

```powershell
python .\send_wechat_time.py --send-now `
  --contact "Exact WeChat Contact Name"
```

Manual preview and send commands do not create or change the Windows scheduled
task.

### Adjust the captured area

If the calendar is clipped or the crop includes too much of the desktop, tune
the width and height in screenshot pixels:

```powershell
python .\send_wechat_time.py --preview `
  --capture-width 520 `
  --capture-height 700
```

To capture the entire primary display:

```powershell
python .\send_wechat_time.py --preview --full-screen
```

Full-screen mode may capture private or unrelated information. Always inspect a
preview before using it for a real send.

## Install the weekday scheduled task

The setup script finds Python, installs `requirements.txt`, runs the non-sending
check, and registers a task for the current Windows user:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\setup_daily_task.ps1 `
  -ContactName "Exact WeChat Contact Name" `
  -SendTime "18:00" `
  -GraceMinutes 0
```

The task runs Monday through Friday and uses an interactive, limited-privilege
user session. Re-running the setup command updates the existing task instead of
creating a duplicate.

The registered task name is:

```text
Send WeChat Attendance Screenshot at 6 PM
```

The name remains the same even if `-SendTime` is changed. The actual trigger and
the arguments stored in Task Scheduler use the time supplied during setup.

The setup script resolves Python in this order:

1. `.runtime\python\python.exe`, when present
2. `python.exe` available on `PATH`
3. Python 3 discovered through `py.exe`

If you want the scheduled task to use `.venv`, activate that environment before
running setup and make sure that no `.runtime\python\python.exe` is present.
Keep the chosen Python environment and this project folder at the same paths
after registration; Task Scheduler stores absolute paths.

## Configuration

### Setup parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `-ContactName` | `Attedance Recording` | Exact WeChat contact or group name to search for. The default spelling matches the current source code. |
| `-SendTime` | `18:00` | Weekday send time in 24-hour `HH:MM` format. |
| `-GraceMinutes` | `0` | Optional late-send window. `0` allows only the scheduled clock minute; advanced users may choose 1–60 minutes. |

### Environment variables

| Variable | Purpose |
| --- | --- |
| `WECHAT_PATH` | Full path to `WeChat.exe` or `Weixin.exe` when it is not in a detected installation directory. |
| `WECHAT_CONTACT` | Default contact for direct Python commands that omit `--contact`. |
| `WECHAT_SEND_TIME` | Default time for direct Python commands that omit `--send-time`. Must use `HH:MM`. |

Set a user-level custom WeChat path from PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
    "WECHAT_PATH",
    "C:\Path\To\WeChat.exe",
    "User"
)
```

Open a new PowerShell window after changing a user-level environment variable.
Then run setup again so its validation uses the new value.

For direct Python execution, explicit command-line values override environment
defaults. The setup script always stores its `-ContactName`, `-SendTime`, and
`-GraceMinutes` values as explicit task arguments, so those scheduled values
take precedence over `WECHAT_CONTACT` and `WECHAT_SEND_TIME`. The beginner
installer always uses `-GraceMinutes 0` to prevent later-minute catch-up sends.

## Command-line reference

Exactly one mode is required for each invocation.

### Modes

| Option | Behavior |
| --- | --- |
| `--check` | Validate WeChat discovery and display access without capturing or sending. |
| `--preview` | Capture the calendar and save a PNG without opening WeChat. |
| `--send-now` | Capture and deliver immediately. Combine with `--draft-only` for a safe unsent draft. |
| `--scheduled` | Continue only when the current time is within the configured schedule window. |

### Options

| Option | Default | Description |
| --- | --- | --- |
| `--contact NAME` | `WECHAT_CONTACT` or `Attedance Recording` | Exact contact/group name entered into WeChat search. |
| `--send-time HH:MM` | `WECHAT_SEND_TIME` or `18:00` | Time used by `--scheduled`. |
| `--grace-minutes N` | `0` | Optional non-negative late-send window. `0` permits only the scheduled clock minute. |
| `--weekdays-only` | Off | With `--scheduled`, skip Saturday and Sunday. |
| `--draft-only` | Off | Paste but do not send. Valid only with `--send-now` or `--scheduled`. |
| `--full-screen` | Off | Capture the whole primary display rather than the bottom-right crop. |
| `--capture-width N` | `500` | Positive width of the bottom-right crop in screenshot pixels. |
| `--capture-height N` | `660` | Positive height of the bottom-right crop in screenshot pixels. |
| `--output PATH` | `timeout_screenshot_preview.png` | Output path used by `--preview`. Parent directories are created automatically. |

Show the built-in help at any time:

```powershell
python .\send_wechat_time.py --help
```

Example of a scheduled-mode invocation equivalent to the default installed
task:

```powershell
python .\send_wechat_time.py --scheduled --weekdays-only `
  --contact "Attedance Recording" `
  --send-time "18:00" `
  --grace-minutes 0
```

Running that command before `18:00` or at `18:01` and later logs a skip and
exits successfully without capturing or sending.

## Manage the scheduled task

Use the exact task name shown below in PowerShell.

Inspect its state and configuration:

```powershell
Get-ScheduledTask -TaskName "Send WeChat Attendance Screenshot at 6 PM"
Get-ScheduledTaskInfo -TaskName "Send WeChat Attendance Screenshot at 6 PM"
```

Disable and re-enable it:

```powershell
Disable-ScheduledTask -TaskName "Send WeChat Attendance Screenshot at 6 PM"
Enable-ScheduledTask -TaskName "Send WeChat Attendance Screenshot at 6 PM"
```

Update the contact or time by running `setup_daily_task.ps1` again with the new
values.

Remove the task:

```powershell
Unregister-ScheduledTask `
  -TaskName "Send WeChat Attendance Screenshot at 6 PM" `
  -Confirm:$false
```

Starting the task manually with `Start-ScheduledTask` still uses
`--scheduled`; it will intentionally skip if the current time is outside the
allowed window. Use `--send-now --draft-only` for a safe end-to-end manual test.

## Logs and exit codes

Every run appends to `wechat_sender.log` in the project directory. View the
latest entries or follow the log live with:

```powershell
Get-Content .\wechat_sender.log -Tail 50
Get-Content .\wechat_sender.log -Wait
```

The log is not rotated automatically. Archive or remove it periodically if the
automation runs for a long time.

| Exit code | Meaning |
| --- | --- |
| `0` | Completed successfully, created a draft, or intentionally skipped a scheduled run. |
| `1` | The capture or WeChat workflow failed; inspect the log for the traceback. |
| `2` | Invalid CLI usage, including argument validation errors. |
| `3` | A manual run was refused because another instance already held the sender mutex. |

When a scheduled instance finds another copy running, it logs a warning and
returns `0` so Task Scheduler records an intentional skip rather than a crash.

## Safety, privacy, and limitations

- **Verify the recipient.** WeChat search selects the first result after the
  supplied name is pasted. The code verifies the WeChat process and foreground
  window, but it cannot prove that the selected conversation has the intended
  identity. Use a unique exact name and test with `--draft-only`.
- **Keep the desktop interactive.** UI automation cannot operate correctly
  while Windows is locked, asleep, signed out, displaying a secure desktop, or
  disconnected from the interactive session.
- **Avoid using the keyboard and mouse during a run.** User activity can change
  focus or interfere with fixed-coordinate taskbar interaction. Focus checks
  stop keyboard input when the expected WeChat window is no longer active.
- **Review captured content.** The default crop includes the bottom-right of the
  primary display and may include notifications or nearby desktop content.
  Full-screen mode captures everything visible on that display.
- **Expect clipboard replacement.** Contact search temporarily replaces text on
  the clipboard, and delivery then replaces it with the screenshot bitmap.
- **Use the primary display.** Capture dimensions and the taskbar clock click
  are calculated from the primary screen. Nonstandard taskbar positions,
  auto-hide behavior, multiple-monitor layouts, or future Windows UI changes may
  require adjustment.
- **Do not treat this as a service.** It depends on visible desktop UI and is
  less robust than an official messaging API. WeChat UI updates can change
  shortcuts, search behavior, or window layout.
- **No delivery receipt is checked.** A successful exit after `Alt+S` means the
  send shortcut was submitted while WeChat retained focus; it does not verify
  server delivery or recipient receipt.

PyAutoGUI's fail-safe remains enabled. Moving the pointer to a screen corner can
raise a fail-safe exception and stop the run if emergency interruption is
needed.

## Troubleshooting

### `WeChat was not found`

Open WeChat and confirm its executable name is `WeChat.exe` or `Weixin.exe`.
If it is installed in a custom location, set `WECHAT_PATH` to the full
executable path and open a new PowerShell session.

### `The WeChat window did not appear`

Start WeChat manually, sign in, and leave its main chat window available. The
automation ignores very small WeChat-owned windows so that it does not mistake
a login or transient window for the signed-in chat interface.

### `WeChat could not be brought to the foreground safely`

Unlock the computer, dismiss secure prompts and modal dialogs, and make sure
another application is not continually taking focus. Run the draft test again
without using the mouse or keyboard during the attempt.

### `The intended WeChat chat window lost foreground focus`

Another application or user action took focus during automation. No further
keyboard input is sent after this check fails. Inspect the open WeChat chat,
clear any partial draft, and retry.

### `The Windows date/time panel did not open`

Confirm that the Windows taskbar clock is in the usual bottom-right position on
the primary display and that the taskbar is visible. Auto-hide, alternative
shells, remote sessions, or a changed Windows layout can prevent the fixed clock
click from opening the flyout.

### The crop is too large, too small, or blurry

Run repeated `--preview` tests with `--capture-width` and `--capture-height`.
The program enables per-monitor DPI awareness before importing PyAutoGUI, but
custom scaling and multi-monitor configurations should still be verified on the
actual machine.

### The wrong conversation is selected

Use the exact, unique WeChat display name. Search collisions are not
disambiguated by the automation. Rename the local contact/group to something
unique if necessary, then validate with `--draft-only`.

### The task did not send after the computer woke up

The task is configured with `StartWhenAvailable`, but exact-time mode accepts a
scheduled run only during the configured clock minute. If Windows starts it in
a later minute, the run is safely skipped. Check Task Scheduler history and
`wechat_sender.log`. Keep the computer awake and unlocked before the scheduled
time because later catch-up sends are disabled.

### The task works manually but not in Task Scheduler

Confirm all of the following:

- The same Windows user that installed the task is signed in.
- The machine is awake and unlocked at the configured time.
- WeChat is signed in and its main window can be restored.
- The project folder and selected Python executable have not moved.
- Dependency installation succeeded for the Python executable stored in the
  scheduled task action.
- `WECHAT_PATH`, if needed, is defined as a user or system variable visible to
  the scheduled process.

## Project structure

```text
wechat-automate/
├── INSTALL.bat               # Double-clickable guided installer
├── TEST_PREVIEW.bat          # Double-clickable safe screenshot test
├── TEST_DRAFT.bat            # Double-clickable safe WeChat draft test
├── easy_setup.ps1            # Shared beginner workflow used by the .bat files
├── send_wechat_time.py       # Capture, validation, WeChat UI automation, CLI
├── setup_daily_task.ps1      # Dependency check and Task Scheduler installer
├── requirements.txt          # Python runtime dependencies
├── README.md                 # Project documentation
└── .gitignore                # Excludes local runtime data and generated output
```

Files produced locally at runtime include:

- `wechat_sender.log` — append-only operational log
- `timeout_screenshot_preview.png` — default preview output
- `__pycache__/` and `*.pyc` — Python bytecode cache
- `.runtime/` or `.venv/` — optional local Python environments
- `.wechat_last_sent` — legacy/local state, if present
- `.wechat_easy_config.json` — locally saved beginner contact and schedule

These local files are intentionally excluded from Git by the included
`.gitignore` because screenshots and logs may contain private information.

## Development and verification

This project interacts with real desktop UI, so preview and draft tests on a
Windows machine are the most meaningful integration tests. Before committing a
change, run:

```powershell
python -m py_compile .\send_wechat_time.py
python .\send_wechat_time.py --help
python .\send_wechat_time.py --check `
  --contact "Test Contact" `
  --send-time "18:00"
python .\send_wechat_time.py --preview
```

Use `--send-now --draft-only` only when a signed-in WeChat session is available
and you can verify the selected conversation. A real send should always be the
final manual test.

## Publishing on GitHub

Before making the repository public:

1. Review the source defaults and replace the contact name if it identifies a
   private organization or group.
2. Confirm with `git status` that logs, screenshots, local Python runtimes, and
   cache files are not staged.
3. Check any screenshots you intentionally add for names, messages,
   notifications, dates, or other personal information.
4. Add an appropriate `LICENSE` file if you want others to have explicit rights
   to use, modify, or redistribute the project. No license is selected by this
   repository documentation.
5. Document the Windows and WeChat versions used for your final test in the
   GitHub release notes, because desktop UI behavior can change over time.

The repository should contain the source scripts, dependency manifest,
beginner helper files, documentation, and `.gitignore`; it should not contain
the local `.runtime` directory or artifacts created by actual attendance runs.
