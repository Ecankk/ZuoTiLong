//! Windows Job Object：sidecar 及其所有子孙进程（Codex 等）绑定在一个
//! KILL_ON_JOB_CLOSE 的 Job 里。外壳无论正常退出还是被强杀，Job 句柄关闭时系统结束整棵树。
//!
//! 子进程以 CREATE_SUSPENDED 启动，先入 Job 再恢复主线程，创建与绑定之间不执行任何代码。

#![cfg(windows)]

use std::io;
use std::mem::{size_of, zeroed};
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE, STILL_ACTIVE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectBasicAccountingInformation,
    JobObjectBasicProcessIdList, JobObjectExtendedLimitInformation, QueryInformationJobObject,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{
    GetExitCodeProcess, OpenProcess, OpenThread, ResumeThread, PROCESS_QUERY_LIMITED_INFORMATION,
    THREAD_SUSPEND_RESUME,
};

pub struct Job {
    handle: HANDLE,
}

// SAFETY: Job 句柄可在线程间使用，所有调用都是线程安全的内核 API。
unsafe impl Send for Job {}
unsafe impl Sync for Job {}

impl Job {
    /// 新建匿名 Job，设置 KILL_ON_JOB_CLOSE（不允许 breakaway）。
    pub fn new_kill_on_close() -> io::Result<Self> {
        // SAFETY: 匿名 Job，默认安全属性。
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(io::Error::last_os_error());
        }
        let job = Self { handle };
        // SAFETY: 结构体全零是合法初值。
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        // SAFETY: 传入正确的信息类与结构体大小。
        let ok = unsafe {
            SetInformationJobObject(
                job.handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(job)
    }

    /// 把子进程放进本 Job。
    pub fn assign_child(&self, child: &std::process::Child) -> io::Result<()> {
        use std::os::windows::io::AsRawHandle;
        // SAFETY: 句柄来自调用方借用的 Child，调用期间有效。
        if unsafe { AssignProcessToJobObject(self.handle, child.as_raw_handle() as HANDLE) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    /// 立即结束 Job 内全部进程。
    pub fn terminate(&self, exit_code: u32) -> io::Result<()> {
        // SAFETY: 有效 Job 句柄。
        if unsafe { TerminateJobObject(self.handle, exit_code) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    /// Job 内当前存活的进程数。
    pub fn active_processes(&self) -> io::Result<u32> {
        // SAFETY: 全零初值；正确的信息类与大小。
        let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { zeroed() };
        let ok = unsafe {
            QueryInformationJobObject(
                self.handle,
                JobObjectBasicAccountingInformation,
                &mut info as *mut _ as *mut _,
                size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(info.ActiveProcesses)
    }

    /// Job 内全部进程 ID（用于核对 sidecar 报告的 pid 是否属于本次启动）。
    pub fn process_ids(&self) -> io::Result<Vec<u32>> {
        const CAP: usize = 256;
        // 布局：两个 u32 计数，随后是 ULONG_PTR 数组。用 u64 缓冲保证对齐。
        let mut buf = vec![0u64; 1 + CAP];
        // SAFETY: 缓冲大小如实传入。
        let ok = unsafe {
            QueryInformationJobObject(
                self.handle,
                JobObjectBasicProcessIdList,
                buf.as_mut_ptr() as *mut _,
                (buf.len() * size_of::<u64>()) as u32,
                std::ptr::null_mut(),
            )
        };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        let in_list = (buf[0] >> 32) as usize;
        Ok(buf[1..1 + in_list.min(CAP)]
            .iter()
            .map(|&pid| pid as u32)
            .collect())
    }

    pub fn contains(&self, pid: u32) -> bool {
        self.process_ids()
            .map(|ids| ids.contains(&pid))
            .unwrap_or(false)
    }
}

impl Drop for Job {
    fn drop(&mut self) {
        // SAFETY: 句柄只在此关闭一次；KILL_ON_JOB_CLOSE 会结束仍存活的进程。
        unsafe { CloseHandle(self.handle) };
    }
}

/// 恢复某个以 CREATE_SUSPENDED 启动的进程的全部线程，返回恢复的线程数。
pub fn resume_process(pid: u32) -> io::Result<usize> {
    // SAFETY: 系统快照，结束时关闭。
    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    let mut resumed = 0usize;
    // SAFETY: dwSize 必须预先设置。
    let mut entry: THREADENTRY32 = unsafe { zeroed() };
    entry.dwSize = size_of::<THREADENTRY32>() as u32;
    let mut more = unsafe { Thread32First(snapshot, &mut entry) } != 0;
    while more {
        if entry.th32OwnerProcessID == pid {
            // SAFETY: 只请求挂起/恢复权限。
            let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID) };
            if !thread.is_null() {
                if unsafe { ResumeThread(thread) } != u32::MAX {
                    resumed += 1;
                }
                unsafe { CloseHandle(thread) };
            }
        }
        more = unsafe { Thread32Next(snapshot, &mut entry) } != 0;
    }
    unsafe { CloseHandle(snapshot) };
    if resumed == 0 {
        return Err(io::Error::other(format!("没有找到进程 {pid} 的线程")));
    }
    Ok(resumed)
}

/// 进程是否仍在运行（测试与诊断用）。
pub fn process_alive(pid: u32) -> bool {
    // SAFETY: 只查询退出码。
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
    if handle.is_null() {
        return false;
    }
    let mut code = 0u32;
    let ok = unsafe { GetExitCodeProcess(handle, &mut code) } != 0;
    unsafe { CloseHandle(handle) };
    ok && code == STILL_ACTIVE as u32
}
