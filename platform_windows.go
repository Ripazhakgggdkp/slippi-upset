//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

var (
	winmm    = syscall.NewLazyDLL("winmm.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")

	procPlaySound             = winmm.NewProc("PlaySoundW")
	procSHGetFolderPath       = shell32.NewProc("SHGetFolderPathW")
	procSetPriorityClass      = kernel32.NewProc("SetPriorityClass")
	procGetConsoleProcessList = kernel32.NewProc("GetConsoleProcessList")
)

const (
	sndAsync     = 0x0001
	sndNoDefault = 0x0002
	sndFilename  = 0x00020000
)

// playFile plays a .wav without blocking.
func playFile(path string) {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return
	}
	procPlaySound.Call(uintptr(unsafe.Pointer(p)), 0, sndFilename|sndAsync|sndNoDefault)
}

// documentsDir follows OneDrive redirection, unlike %USERPROFILE%\Documents.
func documentsDir() string {
	buf := make([]uint16, 260)
	const csidlPersonal = 5 // My Documents
	procSHGetFolderPath.Call(0, csidlPersonal, 0, 0, uintptr(unsafe.Pointer(&buf[0])))
	return syscall.UTF16ToString(buf)
}

// lowerPriority makes the OS always favor Dolphin.
func lowerPriority() {
	h, _ := syscall.GetCurrentProcess()
	const belowNormal = 0x4000
	procSetPriorityClass.Call(uintptr(h), belowNormal)
}

// ownsConsole is true when the console window was opened just for us (the .exe
// was double-clicked), so it would vanish before an error could be read.
func ownsConsole() bool {
	var pids [2]uint32
	n, _, _ := procGetConsoleProcessList.Call(uintptr(unsafe.Pointer(&pids[0])), 2)
	return n == 1
}
