/* SPDX-License-Identifier: GPL-2.0-or-later
 * Windows runtime adapter: support expanded TLS slots without changing
 * guest registers, flags, stack, or red zone. All main-image RVAs are guarded
 * by the patcher's SHA256 check. This DLL has no CRT dependencies.
 */
#include <windows.h>
#include <stdint.h>

typedef struct { uint64_t address, size, flags; } Segment;
typedef void *(*LowMap)(size_t size, int protection);

static volatile LONG cursor_watcher_started = 0;
static DWORD cursor_tls_index = TLS_OUT_OF_INDEXES;
static DWORD cursor_hook_threads[4];
static HHOOK cursor_hooks[4];
static DWORD cursor_hook_failed_thread = 0;
static unsigned cursor_hook_count = 0;

static void hide_cursor(int *show_cursor_calls) {
    do {
        ++*show_cursor_calls;
    } while (ShowCursor(FALSE) >= 0);
}

static void cursor_log(const char *message, DWORD length) {
    HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE);
    if (!output || output == INVALID_HANDLE_VALUE) return;
    DWORD written;
    WriteFile(output, message, length, &written, NULL);
}

static int cursor_hide_calls_for_thread(void) {
    return (int)(uintptr_t)TlsGetValue(cursor_tls_index);
}

static void hide_cursor_on_window_thread(void) {
    int calls = cursor_hide_calls_for_thread();
    const BOOL already_hidden_by_us = calls > 0;
    CURSORINFO cursor = {sizeof(cursor)};
    if (GetCursorInfo(&cursor) && !(cursor.flags & CURSOR_SHOWING)) return;

    hide_cursor(&calls);
    TlsSetValue(cursor_tls_index, (LPVOID)(uintptr_t)calls);
    SetCursor(NULL);
    if (already_hidden_by_us) return;

    static const char message[] = "Cursor hidden: game window focused.\r\n";
    cursor_log(message, sizeof(message) - 1);
}

static void restore_cursor_on_window_thread(void) {
    int calls = cursor_hide_calls_for_thread();
    if (calls <= 0) return;
    while (calls > 0) {
        ShowCursor(TRUE);
        --calls;
    }
    TlsSetValue(cursor_tls_index, NULL);
    static const char message[] = "Cursor restored: game window focus changed.\r\n";
    cursor_log(message, sizeof(message) - 1);
}

static BOOL is_cursor_message(UINT message) {
    return (message >= WM_MOUSEFIRST && message <= WM_MOUSELAST) ||
           (message >= WM_NCMOUSEMOVE && message <= WM_NCXBUTTONDBLCLK) ||
           message == WM_SETCURSOR || message == WM_ACTIVATEAPP ||
           message == WM_ACTIVATE || message == WM_SETFOCUS ||
           message == WM_KILLFOCUS || message == WM_NCACTIVATE;
}

static LRESULT CALLBACK after_game_window_proc(int code, WPARAM wparam, LPARAM lparam) {
    if (code >= 0 && lparam) {
        const CWPRETSTRUCT *message = (const CWPRETSTRUCT *)lparam;
        if (message->message == WM_ACTIVATEAPP && !message->wParam) {
            restore_cursor_on_window_thread();
        } else {
            HWND foreground = GetForegroundWindow();
            DWORD foreground_pid = 0;
            if (foreground) GetWindowThreadProcessId(foreground, &foreground_pid);
            if (foreground_pid != GetCurrentProcessId()) {
                restore_cursor_on_window_thread();
            } else if (is_cursor_message(message->message)) {
                hide_cursor_on_window_thread();
            }
        }
    }
    return CallNextHookEx(NULL, code, wparam, lparam);
}

static void install_cursor_hook(DWORD thread_id) {
    if (!thread_id || cursor_tls_index == TLS_OUT_OF_INDEXES) return;
    for (unsigned i = 0; i < cursor_hook_count; ++i) {
        if (cursor_hook_threads[i] == thread_id) return;
    }
    if (cursor_hook_count >= sizeof(cursor_hooks) / sizeof(cursor_hooks[0]) ||
        cursor_hook_failed_thread == thread_id) return;

    HHOOK hook = SetWindowsHookExW(WH_CALLWNDPROCRET, after_game_window_proc, NULL, thread_id);
    if (!hook) {
        cursor_hook_failed_thread = thread_id;
        static const char message[] = "Cursor focus hook installation failed.\r\n";
        cursor_log(message, sizeof(message) - 1);
        return;
    }
    cursor_hook_threads[cursor_hook_count] = thread_id;
    cursor_hooks[cursor_hook_count++] = hook;
    cursor_hook_failed_thread = 0;
    static const char message[] = "Cursor focus hook installed on game window thread.\r\n";
    cursor_log(message, sizeof(message) - 1);
}

static DWORD WINAPI watch_game_cursor(LPVOID unused) {
    (void)unused;
    const DWORD game_pid = GetCurrentProcessId();
    for (;;) {
        HWND foreground = GetForegroundWindow();
        DWORD foreground_pid = 0;
        DWORD foreground_thread = foreground ? GetWindowThreadProcessId(foreground, &foreground_pid) : 0;
        if (foreground_pid == game_pid) install_cursor_hook(foreground_thread);
        Sleep(75);
    }
}

static void start_cursor_watcher(void) {
    if (InterlockedCompareExchange(&cursor_watcher_started, 1, 0) != 0) return;
    cursor_tls_index = TlsAlloc();
    if (cursor_tls_index == TLS_OUT_OF_INDEXES) {
        InterlockedExchange(&cursor_watcher_started, 0);
        return;
    }
    HANDLE thread = CreateThread(NULL, 0, watch_game_cursor, NULL, 0, NULL);
    if (thread) CloseHandle(thread);
    else {
        TlsFree(cursor_tls_index);
        cursor_tls_index = TLS_OUT_OF_INDEXES;
        InterlockedExchange(&cursor_watcher_started, 0);
    }
}

static int is_tcb_load(const unsigned char *at) {
    return *(const uint64_t *)at == UINT64_C(0x25048b4865) && !at[8];
}

static void stop(void) {
    static const char message[] = "STOP: CrossOver TLS adapter could not allocate a nearby trampoline\r\n";
    DWORD written;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), message, sizeof(message) - 1, &written, NULL);
    ExitProcess(21);
}

static void relative_jump(unsigned char *at, const unsigned char *target) {
    intptr_t delta = (intptr_t)((uintptr_t)target - ((uintptr_t)at + 5));
    if (delta < INT32_MIN || delta > INT32_MAX) stop();
    at[0] = 0xe9;
    *(int32_t *)(at + 1) = (int32_t)delta;
}

__declspec(dllexport) uint64_t bb_crossover_patch_tcb(
        const Segment *segments, uint64_t count, unsigned char *image, LowMap allocate,
        const DWORD *tls_slot_address) {
    start_cursor_watcher();
    DWORD slot = *tls_slot_address;
    if (slot == TLS_OUT_OF_INDEXES) stop();
    uint64_t matches = 0;
    for (uint64_t s = 0; s < count; ++s) {
        if (!(segments[s].flags & 1) || segments[s].size < 9) continue;
        unsigned char *at = image + segments[s].address;
        unsigned char *end = at + segments[s].size - 9;
        for (; at <= end; ++at) if (is_tcb_load(at)) { ++matches; at += 8; }
    }
    unsigned char *stubs = NULL;
    if (matches && slot >= 64) {
        stubs = allocate((size_t)matches * 32, 7); /* PROT_READ|WRITE|EXEC */
        if (!stubs) stop();
    }
    uint64_t patched = 0;
    for (uint64_t s = 0; s < count; ++s) {
        if (!(segments[s].flags & 1) || segments[s].size < 9) continue;
        unsigned char *at = image + segments[s].address;
        unsigned char *end = at + segments[s].size - 9;
        for (; at <= end; ++at) {
            if (!is_tcb_load(at)) continue;
            if (slot < 64) {
                *(uint32_t *)(at + 5) = 0x1480 + slot * 8;
            } else {
                unsigned char *stub = stubs + patched * 32;
                /* mov rax,gs:[TlsExpansionSlots]; mov rax,[rax+(slot-64)*8] */
                *(uint64_t *)stub = UINT64_C(0x178025048b4865);
                stub[8] = 0;
                stub[9] = 0x48; stub[10] = 0x8b; stub[11] = 0x80;
                *(uint32_t *)(stub + 12) = (slot - 64) * 8;
                relative_jump(stub + 16, at + 9);
                relative_jump(at, stub);
                for (unsigned i = 5; i < 9; ++i) at[i] = 0x90;
            }
            ++patched;
            at += 8;
        }
    }
    if (stubs) FlushInstructionCache(GetCurrentProcess(), stubs, (SIZE_T)matches * 32);
    return patched;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reserved;
    (void)reason;
    return TRUE;
}
