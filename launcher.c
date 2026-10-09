#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show) {
    wchar_t folder[32768], interpreter[32768], arguments[32768];
    if (!GetModuleFileNameW(NULL, folder, 32768)) return 1;
    wchar_t *slash = wcsrchr(folder, L'\\');
    if (!slash) return 1;
    *slash = 0;
    if (wcslen(folder) > 32000) return 1;
    swprintf(interpreter, 32768, L"%ls\\runtime\\pythonw.exe", folder);
    swprintf(arguments, 32768, L"\"%ls\\main.py\"", folder);
    SHELLEXECUTEINFOW launch = {0};
    launch.cbSize = sizeof(launch);
    launch.fMask = SEE_MASK_NOCLOSEPROCESS;
    launch.lpFile = interpreter;
    launch.lpParameters = arguments;
    launch.lpDirectory = folder;
    launch.nShow = SW_SHOWNORMAL;
    if (!ShellExecuteExW(&launch)) {
        MessageBoxW(NULL, L"JARVIS could not start. Extract the whole ZIP first, then run Debug JARVIS.cmd for details.", L"JARVIS", MB_OK | MB_ICONERROR);
        return 1;
    }
    if (launch.hProcess) {
        if (WaitForSingleObject(launch.hProcess, 2500) == WAIT_OBJECT_0) {
            DWORD code = 0;
            if (GetExitCodeProcess(launch.hProcess, &code) && code != 0) {
                MessageBoxW(NULL, L"JARVIS exited during startup. Run Debug JARVIS.cmd in the extracted folder to see the error.", L"JARVIS", MB_OK | MB_ICONERROR);
            }
        }
        CloseHandle(launch.hProcess);
    }
    return 0;
}
