# 20 - Power Management, Sleep Prevention & Auto-Sleep on Finish

## Background
Full-length audiobook alignment often runs unattended for 1 to 3+ hours (or overnight). 

On Windows, WSL2, and macOS, operating systems employ aggressive idle timers that automatically suspend or sleep the computer after a period without physical user keyboard or mouse activity. Because WSL2 Linux processes do not automatically register power requests with the Windows host, the host OS frequently goes to sleep mid-build, freezing GPU compute.

Conversely, users running long unattended jobs overnight often want the machine to automatically enter sleep or standby mode once the entire book is finished to conserve energy.

A dedicated cross-platform power management mechanism within EchoPage will prevent unintended sleep during execution and optionally suspend the system upon successful completion.

---

## What to do

1. **Active Sleep Prevention Guard (`prevent_system_sleep` Context Manager):**
   - Wrap long-running execution phases (`echopage build`, `echopage align`) in a power guard context manager.
   - Platform implementations:
     - **WSL2**: Detect WSL environment (`/proc/sys/fs/binfmt_misc/WSLInterop` or `WSL_DISTRO_NAME`). Maintain an active Windows execution power request via `powershell.exe` calling `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` or background keep-awake heartbeat.
     - **Native Windows**: Call `ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)` (`ES_CONTINUOUS | ES_SYSTEM_REQUIRED`).
     - **macOS**: Spawn a non-blocking `caffeinate -i -w <pid>` subprocess or call `IOPMAssertionCreateWithName`.
     - **Linux (systemd/desktop)**: Utilize `systemd-inhibit` or DBus org.freedesktop.ScreenSaver inhibit interface.
   - **Guaranteed Release**: Power assertions must be cleanly released in a `finally` block on exit, normal completion, or unexpected error.

2. **CLI Post-Build Action Flag (`--sleep-on-finish`):**
   - Add `--sleep-on-finish` flag (or `--post-action none|sleep|shutdown`) to `echopage build`:
     - Default: `none`.
     - Flag triggers host OS suspend/sleep **only** after the final EPUB package is successfully built and verified.
     - If the build errors out or aborts early, sleep is suppressed so users can inspect error logs.
   - Graceful Countdown: Display a 30-second cancellation countdown in the terminal before triggering system sleep (allowing a present user to abort sleep by pressing any key).

---

## Acceptance Criteria
- [ ] **WSL2 / Windows Sleep Prevention:** While `echopage build` is running in WSL2 or native Windows, host OS idle sleep is inhibited.
- [ ] **macOS / Linux Support:** Platform-appropriate power assertions (`caffeinate` / `systemd-inhibit`) are engaged.
- [ ] **Clean Resource Teardown:** Host power assertions are immediately released when the CLI process terminates.
- [ ] **`--sleep-on-finish` Implementation:** Specifying `--sleep-on-finish` triggers system sleep only upon successful EPUB build completion.
- [ ] **Error Guard:** Failed or interrupted builds do not trigger post-build sleep.
- [ ] **Automated Tests:** Unit tests for platform power detection, context manager entry/exit, countdown logic, and mock power state transitions.
