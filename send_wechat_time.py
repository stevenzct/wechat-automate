"""Capture the Windows date/time flyout and send it to a WeChat contact."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from datetime import date, datetime, time as clock_time, timedelta
from io import BytesIO
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    # The project's optional embedded Python runtime uses an isolated ._pth
    # configuration and may not add the script directory automatically.
    sys.path.insert(0, str(SCRIPT_DIR))


def configure_dpi_awareness_early() -> bool:
    """Set DPI mode before PyAutoGUI imports and initializes its Win32 backend."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        if set_context(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return True
    except (AttributeError, OSError):
        pass

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        set_awareness = shcore.SetProcessDpiAwareness
        set_awareness.argtypes = [ctypes.c_int]
        set_awareness.restype = ctypes.c_long
        if set_awareness(2) == 0:  # PROCESS_PER_MONITOR_DPI_AWARE
            return True
    except (AttributeError, OSError):
        pass

    try:
        set_aware = user32.SetProcessDPIAware
        set_aware.argtypes = []
        set_aware.restype = wintypes.BOOL
        return bool(set_aware())
    except (AttributeError, OSError):
        return False


DPI_AWARENESS_CONFIGURED = configure_dpi_awareness_early()

import pyautogui
import pyperclip
import win32clipboard
import win32con
import win32gui
import win32process
from PIL import ImageChops, ImageStat

from philippine_holidays import check_philippine_holiday


APP_DIR = SCRIPT_DIR
LOG_FILE = APP_DIR / "wechat_sender.log"
DEFAULT_PREVIEW_FILE = APP_DIR / "timeout_screenshot_preview.png"
TIME_IN_MARKER_FILE = APP_DIR / ".wechat_last_time_in"

DEFAULT_CONTACT_NAME = os.getenv("WECHAT_CONTACT", "Attedance Recording")
DEFAULT_SEND_TIME = os.getenv("WECHAT_SEND_TIME", "18:00")
DEFAULT_GRACE_MINUTES = 0
DEFAULT_CAPTURE_WIDTH = 500
DEFAULT_CAPTURE_HEIGHT = 660
WECHAT_PROCESS_NAMES = {"wechat.exe", "weixin.exe"}
MUTEX_NAME = r"Local\WeChatTimeoutScreenshotSender"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ALREADY_EXISTS = 183

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
USER32 = ctypes.WinDLL("user32", use_last_error=True)

KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.CloseHandle.restype = wintypes.BOOL
KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
KERNEL32.CreateMutexW.restype = wintypes.HANDLE
KERNEL32.GetCurrentThreadId.argtypes = []
KERNEL32.GetCurrentThreadId.restype = wintypes.DWORD

USER32.GetForegroundWindow.argtypes = []
USER32.GetForegroundWindow.restype = wintypes.HWND
USER32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
USER32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
USER32.AttachThreadInput.restype = wintypes.BOOL
USER32.BringWindowToTop.argtypes = [wintypes.HWND]
USER32.BringWindowToTop.restype = wintypes.BOOL
USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
USER32.SetForegroundWindow.restype = wintypes.BOOL
USER32.SetFocus.argtypes = [wintypes.HWND]
USER32.SetFocus.restype = wintypes.HWND
if hasattr(USER32, "GetDpiForSystem"):
    USER32.GetDpiForSystem.argtypes = []
    USER32.GetDpiForSystem.restype = wintypes.UINT

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def configure_dpi_awareness() -> None:
    """Report whether early DPI setup succeeded before PyAutoGUI initialized."""
    if not DPI_AWARENESS_CONFIGURED:
        logging.warning(
            "Windows DPI awareness could not be configured; verify the preview crop."
        )


def display_scale() -> float:
    """Return the primary display scale (1.25 for Windows 125%, for example)."""
    try:
        return max(1.0, USER32.GetDpiForSystem() / 96.0)
    except (AttributeError, OSError):
        return 1.0


def acquire_single_instance_mutex():
    """Prevent two scheduled/manual instances from typing into WeChat together."""
    ctypes.set_last_error(0)
    handle = KERNEL32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        KERNEL32.CloseHandle(handle)
        return None
    return handle


def executable_candidates() -> list[Path]:
    """Return likely WeChat/Weixin executable locations."""
    candidates: list[Path] = []
    custom_path = os.getenv("WECHAT_PATH")
    if custom_path:
        candidates.append(Path(custom_path).expanduser())

    program_files = os.getenv("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.getenv("LOCALAPPDATA", "")

    candidates.extend(
        [
            Path(program_files) / "Tencent" / "Weixin" / "Weixin.exe",
            Path(program_files) / "Tencent" / "WeChat" / "WeChat.exe",
            Path(program_files_x86) / "Tencent" / "WeChat" / "WeChat.exe",
        ]
    )
    if local_app_data:
        candidates.extend(
            [
                Path(local_app_data) / "Tencent" / "Weixin" / "Weixin.exe",
                Path(local_app_data) / "Tencent" / "WeChat" / "WeChat.exe",
            ]
        )
    return candidates


def find_wechat_executable() -> Path:
    for candidate in executable_candidates():
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "WeChat was not found. Set WECHAT_PATH to the full path of "
        "WeChat.exe or Weixin.exe."
    )


def process_image_name(process_id: int) -> str:
    """Return a process executable name without relying on a window title."""
    handle = KERNEL32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        process_id,
    )
    if not handle:
        return ""

    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name.lower()
    finally:
        KERNEL32.CloseHandle(handle)


def window_process_id(window_handle: int) -> int:
    return win32process.GetWindowThreadProcessId(window_handle)[1]


def is_wechat_window(window_handle: int) -> bool:
    if not window_handle or not win32gui.IsWindow(window_handle):
        return False
    return process_image_name(window_process_id(window_handle)) in WECHAT_PROCESS_NAMES


def find_wechat_window() -> int | None:
    """Find the largest visible top-level window owned by WeChat itself."""
    candidates: list[tuple[int, int]] = []

    def add_candidate(window_handle: int, _extra: object) -> bool:
        if not (win32gui.IsWindowVisible(window_handle) or win32gui.IsIconic(window_handle)):
            return True
        if not is_wechat_window(window_handle):
            return True

        try:
            if win32gui.IsIconic(window_handle):
                left, top, right, bottom = win32gui.GetWindowPlacement(window_handle)[4]
            else:
                left, top, right, bottom = win32gui.GetWindowRect(window_handle)
            width = max(0, right - left)
            height = max(0, bottom - top)
            # The signed-in chat window is substantially larger than WeChat's
            # login window and transient notification surfaces.
            if width < 600 or height < 400:
                return True
            area = width * height
        except win32gui.error:
            area = 0
        candidates.append((area, window_handle))
        return True

    win32gui.EnumWindows(add_candidate, None)
    if not candidates:
        return None
    return max(candidates)[1]


def is_wechat_foreground(expected_window: int | None = None) -> bool:
    foreground = win32gui.GetForegroundWindow()
    if not is_wechat_window(foreground):
        return False
    return expected_window is None or foreground == expected_window


def set_foreground_with_attached_threads(window_handle: int) -> None:
    """Fallback for Windows foreground-lock restrictions."""
    current_thread = KERNEL32.GetCurrentThreadId()
    foreground = USER32.GetForegroundWindow()
    foreground_thread = (
        USER32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    )
    target_thread = USER32.GetWindowThreadProcessId(window_handle, None)
    attached_threads: list[int] = []

    for thread_id in {foreground_thread, target_thread}:
        if thread_id and thread_id != current_thread:
            if USER32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)

    try:
        USER32.BringWindowToTop(window_handle)
        USER32.SetForegroundWindow(window_handle)
        USER32.SetFocus(window_handle)
    finally:
        for thread_id in reversed(attached_threads):
            USER32.AttachThreadInput(current_thread, thread_id, False)


def focus_wechat_window(window_handle: int, timeout_seconds: float = 6) -> None:
    """Restore WeChat, retry foreground activation, and verify the process."""
    deadline = time.monotonic() + timeout_seconds
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            if win32gui.IsIconic(window_handle):
                win32gui.ShowWindow(window_handle, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(window_handle, win32con.SW_SHOW)
            win32gui.SetWindowPos(
                window_handle,
                win32con.HWND_TOP,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE
                | win32con.SWP_NOSIZE
                | win32con.SWP_SHOWWINDOW,
            )
            win32gui.BringWindowToTop(window_handle)
            win32gui.SetForegroundWindow(window_handle)
        except win32gui.error:
            logging.debug("Direct WeChat activation attempt failed.", exc_info=True)

        time.sleep(0.35)
        if is_wechat_foreground(window_handle):
            return

        if attempt == 2:
            # Pressing Alt once lets the calling process request foreground focus.
            pyautogui.press("alt")
        if attempt >= 3:
            try:
                set_foreground_with_attached_threads(window_handle)
            except OSError:
                logging.debug("Attached-thread activation failed.", exc_info=True)
        time.sleep(0.35)
        if is_wechat_foreground(window_handle):
            return

    raise RuntimeError("WeChat could not be brought to the foreground safely.")


def activate_wechat(timeout_seconds: int = 20) -> int:
    """Show WeChat (including from its tray state), focus it, and verify focus."""
    window_handle = find_wechat_window()
    if window_handle is None:
        executable = find_wechat_executable()
        logging.info("Opening WeChat from %s", executable)
        subprocess.Popen([str(executable)])

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(0.75)
            window_handle = find_wechat_window()
            if window_handle is not None:
                break

    if window_handle is None:
        raise RuntimeError(
            "The WeChat window did not appear. Open and sign in to WeChat, then retry."
        )

    focus_wechat_window(window_handle)
    return window_handle


def ensure_wechat_has_focus(expected_window: int) -> None:
    if not is_wechat_foreground(expected_window):
        raise RuntimeError(
            "The intended WeChat chat window lost foreground focus; stopped before "
            "sending keyboard input."
        )


def paste_text(text: str) -> None:
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")


def capture_timeout_screenshot(
    *,
    full_screen: bool = False,
    capture_width: int = DEFAULT_CAPTURE_WIDTH,
    capture_height: int = DEFAULT_CAPTURE_HEIGHT,
):
    """Open Windows date/time, then capture the proof area shown in the example."""
    if not win32gui.GetForegroundWindow():
        raise RuntimeError(
            "No interactive desktop is available. Keep the laptop awake and unlocked."
        )

    screen_width, screen_height = pyautogui.size()
    scale = display_scale()
    width = min(capture_width, screen_width)
    height = min(capture_height, screen_height)
    region = (screen_width - width, screen_height - height, width, height)

    # Escape closes an existing flyout. Clicking the taskbar clock is more
    # dependable than a shell hotkey across Windows 11 builds and keyboard maps.
    pyautogui.press("esc")
    time.sleep(0.25)
    before = pyautogui.screenshot(region=region)
    pyautogui.click(
        screen_width - round(45 * scale),
        screen_height - round(30 * scale),
    )
    time.sleep(1.25)

    try:
        screenshot = (
            pyautogui.screenshot()
            if full_screen
            else pyautogui.screenshot(region=region)
        )
        verification_image = (
            screenshot.crop(
                (
                    region[0],
                    region[1],
                    region[0] + region[2],
                    region[1] + region[3],
                )
            )
            if full_screen
            else screenshot
        )
        difference = ImageChops.difference(
            before.convert("RGB"), verification_image.convert("RGB")
        )
        mean_difference = sum(ImageStat.Stat(difference).mean) / 3
        if mean_difference < 5:
            raise RuntimeError(
                "The Windows date/time panel did not open; refusing to send an "
                "ordinary desktop screenshot."
            )
        return screenshot
    finally:
        pyautogui.press("esc")
        time.sleep(0.25)


def save_screenshot(image, output_path: Path) -> Path:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
    return output_path


def copy_image_to_clipboard(image) -> None:
    """Copy a Pillow image to the Windows clipboard as bitmap data."""
    with BytesIO() as output:
        image.convert("RGB").save(output, "BMP")
        bitmap_data = output.getvalue()[14:]

    for attempt in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bitmap_data)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception:
            if attempt == 4:
                raise
            time.sleep(0.3)


def inside_schedule_window(
    now: datetime,
    scheduled_time: clock_time,
    grace_minutes: int,
) -> bool:
    scheduled = datetime.combine(now.date(), scheduled_time)
    if grace_minutes == 0:
        # Exact-time mode permits normal Task Scheduler/UI startup latency
        # during the scheduled clock minute, but never a later-minute catch-up.
        return scheduled <= now < scheduled + timedelta(minutes=1)
    return scheduled <= now <= scheduled + timedelta(minutes=grace_minutes)


def weekday_rule_allows(day: date, *, weekdays_only: bool) -> bool:
    """Return whether an automatic run passes its weekday rule."""
    if weekdays_only and day.weekday() >= 5:
        logging.warning("Today is a weekend; skipping the weekday task.")
        return False
    return True


def philippine_holiday_rule_allows(day: date) -> bool:
    """Return whether verified nationwide holiday data permits an automatic run."""
    holiday_check = check_philippine_holiday(day)
    if holiday_check.refresh_warning:
        logging.warning(
            "%s Continuing with %s.",
            holiday_check.refresh_warning,
            holiday_check.source_description,
        )
    if not holiday_check.known_year:
        logging.warning(
            "No verified nationwide Philippine holiday calendar is available "
            "for %s; skipping rather than guessing that today is a workday.",
            day.year,
        )
        return False
    if holiday_check.holiday and holiday_check.holiday.is_non_working:
        logging.info(
            "Today is %s (%s); skipping the scheduled workday message.",
            holiday_check.holiday.name,
            holiday_check.holiday.display_type,
        )
        return False
    if holiday_check.holiday:
        logging.info(
            "Today is %s (%s); this is a working day, so the scheduled "
            "message will continue.",
            holiday_check.holiday.name,
            holiday_check.holiday.display_type,
        )
    return True


def time_in_was_sent_on(day: date, marker_path: Path = TIME_IN_MARKER_FILE) -> bool:
    """Return whether the time-in marker records an actual send on ``day``."""
    try:
        marker_value = marker_path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise RuntimeError(f"The time-in marker could not be read: {error}") from error

    try:
        marker_day = date.fromisoformat(marker_value)
    except ValueError as error:
        raise RuntimeError(
            f"The time-in marker contains an invalid date: {marker_value!r}."
        ) from error
    return marker_day == day


def record_time_in_sent(day: date, marker_path: Path = TIME_IN_MARKER_FILE) -> None:
    """Atomically record that an actual time-in send completed on ``day``."""
    marker_path = marker_path.resolve()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            newline="\n",
            dir=marker_path.parent,
            prefix=f"{marker_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(f"{day.isoformat()}\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, marker_path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def attendance_caption(label: str, now: datetime) -> str:
    """Return the 'Time In'/'Time Out' text sent alongside the screenshot."""
    return f"{label}\n{now.strftime('%I:%M %p | %B %d, %Y')}"


def deliver_screenshot(
    image,
    contact_name: str,
    *,
    caption: str | None = None,
    draft_only: bool = False,
) -> None:
    """Select a WeChat conversation, paste the caption and image, then optionally send."""
    window_handle = activate_wechat()
    ensure_wechat_has_focus(window_handle)

    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.8)
    ensure_wechat_has_focus(window_handle)
    pyautogui.hotkey("ctrl", "a")
    paste_text(contact_name)
    time.sleep(1.2)
    ensure_wechat_has_focus(window_handle)
    pyautogui.press("enter")
    time.sleep(1.2)
    ensure_wechat_has_focus(window_handle)

    if caption:
        # A trailing newline in the pasted clipboard text (not a physical Enter
        # key press) moves the cursor to its own line before the image, without
        # risking a premature send under WeChat's "Enter to send" preference.
        paste_text(f"{caption}\n")
        time.sleep(0.5)
        ensure_wechat_has_focus(window_handle)

    copy_image_to_clipboard(image)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(1.2)
    ensure_wechat_has_focus(window_handle)

    if draft_only:
        logging.info(
            "Screenshot pasted into the '%s' conversation but not sent (draft mode).",
            contact_name,
        )
        return

    # Alt+S works with either WeChat Enter-key preference.
    pyautogui.hotkey("alt", "s")
    time.sleep(1)
    ensure_wechat_has_focus(window_handle)


def parse_send_time(value: str) -> clock_time:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise argparse.ArgumentTypeError(
            "Time must use 24-hour HH:MM format, for example 18:00."
        )
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Time must use 24-hour HH:MM format, for example 18:00."
        ) from error


def contact_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("The WeChat contact name cannot be blank.")
    return value


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a whole number.") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("Expected a number greater than zero.")
    return number


def nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a whole number.") from error
    if number < 0:
        raise argparse.ArgumentTypeError("Expected zero or a positive number.")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--scheduled",
        action="store_true",
        help="Send only inside the configured schedule window.",
    )
    mode.add_argument(
        "--time-in",
        action="store_true",
        help=(
            "Send one time-in per local workday, without requiring a configured "
            "clock time."
        ),
    )
    mode.add_argument(
        "--send-now",
        action="store_true",
        help="Capture and send immediately.",
    )
    mode.add_argument(
        "--preview",
        action="store_true",
        help="Capture to a PNG without opening or messaging WeChat.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check the screen and WeChat installation without sending anything.",
    )
    parser.add_argument(
        "--contact",
        type=contact_name,
        default=contact_name(DEFAULT_CONTACT_NAME),
        help=f"Exact WeChat contact name (default: {DEFAULT_CONTACT_NAME!r}).",
    )
    parser.add_argument(
        "--send-time",
        type=parse_send_time,
        default=parse_send_time(DEFAULT_SEND_TIME),
        help="Scheduled time in 24-hour HH:MM format (default: %(default)s).",
    )
    parser.add_argument(
        "--grace-minutes",
        type=nonnegative_int,
        default=DEFAULT_GRACE_MINUTES,
        help=(
            "How many minutes a delayed scheduled run may still send; "
            "0 permits only the scheduled clock minute (default: 0)."
        ),
    )
    parser.add_argument(
        "--draft-only",
        action="store_true",
        help="Paste into the selected conversation but do not press Send.",
    )
    parser.add_argument(
        "--weekdays-only",
        action="store_true",
        help=(
            "With --scheduled, skip Saturday and Sunday; --time-in always skips "
            "weekends."
        ),
    )
    parser.add_argument(
        "--full-screen",
        action="store_true",
        help="Capture the whole primary display instead of the calendar corner.",
    )
    parser.add_argument(
        "--capture-width",
        type=positive_int,
        default=DEFAULT_CAPTURE_WIDTH,
        help="Calendar-crop width in screenshot pixels (default: 500).",
    )
    parser.add_argument(
        "--capture-height",
        type=positive_int,
        default=DEFAULT_CAPTURE_HEIGHT,
        help="Calendar-crop height in screenshot pixels (default: 660).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PREVIEW_FILE,
        help="PNG path used by --preview.",
    )
    return parser.parse_args()


def run_check(args: argparse.Namespace) -> int:
    executable = find_wechat_executable()
    screen_width, screen_height = pyautogui.size()
    holiday_check = check_philippine_holiday(datetime.now().date())
    print("Automation check passed.")
    print(f"WeChat: {executable}")
    print(f"Screen: {screen_width}x{screen_height}")
    print(f"Contact: {args.contact}")
    print(f"Scheduled send time: {args.send_time.strftime('%H:%M')}")
    if holiday_check.known_year:
        print(
            "Philippine holiday calendar: ready "
            f"({holiday_check.source_description})"
        )
    else:
        print(
            "Philippine holiday calendar: not published or not reachable for "
            f"{holiday_check.day.year}; scheduled runs will safely skip until it "
            "can be verified."
        )
    if holiday_check.refresh_warning:
        print(f"Holiday calendar refresh warning: {holiday_check.refresh_warning}")
    print("The laptop must be awake, unlocked, and signed in to WeChat when it runs.")
    return 0


def main() -> int:
    args = parse_args()
    configure_logging()
    configure_dpi_awareness()

    if args.draft_only and not (args.send_now or args.scheduled or args.time_in):
        logging.error("--draft-only requires --send-now, --scheduled, or --time-in.")
        return 2

    mutex_handle = acquire_single_instance_mutex()
    if mutex_handle is None:
        if args.scheduled or args.time_in:
            logging.warning("Another sender instance is already running; skipping.")
            return 0
        logging.error("Another sender instance is already running.")
        return 3

    try:
        if args.check:
            return run_check(args)

        now = datetime.now()
        if args.scheduled or args.time_in:
            weekdays_only = args.weekdays_only or args.time_in
            if not weekday_rule_allows(now.date(), weekdays_only=weekdays_only):
                return 0

        if args.scheduled:
            if not inside_schedule_window(now, args.send_time, args.grace_minutes):
                logging.warning(
                    "Not within the %s schedule window; skipping.",
                    args.send_time.strftime("%H:%M"),
                )
                return 0

        if args.scheduled or args.time_in:
            if not philippine_holiday_rule_allows(now.date()):
                return 0

        if args.time_in:
            # A holiday refresh can span midnight. Re-evaluate the new local
            # date before duplicate checking or capture so a late Friday run,
            # for example, can never continue under Saturday's date using
            # Friday's workday decision.
            refreshed_now = datetime.now()
            if refreshed_now.date() != now.date():
                logging.info(
                    "The local date changed during the time-in workday check; "
                    "rechecking %s.",
                    refreshed_now.date().isoformat(),
                )
                now = refreshed_now
                if not weekday_rule_allows(now.date(), weekdays_only=True):
                    return 0
                if not philippine_holiday_rule_allows(now.date()):
                    return 0

        if args.scheduled:
            # A calendar refresh can use several seconds. Recheck exact-minute
            # mode so a refresh never turns an on-time start into a late send.
            now = datetime.now()
            if not inside_schedule_window(now, args.send_time, args.grace_minutes):
                logging.warning(
                    "The holiday check finished after the %s schedule window; "
                    "skipping the late send.",
                    args.send_time.strftime("%H:%M"),
                )
                return 0

        if (
            args.time_in
            and not args.draft_only
            and time_in_was_sent_on(now.date(), TIME_IN_MARKER_FILE)
        ):
            logging.info(
                "A time-in was already sent on %s; skipping the duplicate.",
                now.date().isoformat(),
            )
            return 0

        screenshot = capture_timeout_screenshot(
            full_screen=args.full_screen,
            capture_width=args.capture_width,
            capture_height=args.capture_height,
        )

        if args.preview:
            saved_path = save_screenshot(screenshot, args.output)
            logging.info("Preview saved to %s; nothing was sent.", saved_path)
            print(saved_path)
            return 0

        caption = None
        if args.time_in:
            caption = attendance_caption("Time In", now)
        elif args.scheduled:
            caption = attendance_caption("Time Out", now)

        deliver_screenshot(
            screenshot, args.contact, caption=caption, draft_only=args.draft_only
        )
        if args.draft_only:
            return 0

        if args.time_in:
            record_time_in_sent(now.date(), TIME_IN_MARKER_FILE)

        logging.info(
            "Send shortcut submitted to %s at %s.",
            args.contact,
            now.strftime("%I:%M %p | %B %d, %Y"),
        )
        return 0
    except Exception:
        logging.exception("The WeChat screenshot workflow did not complete.")
        return 1
    finally:
        KERNEL32.CloseHandle(mutex_handle)


if __name__ == "__main__":
    sys.exit(main())
