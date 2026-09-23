//go:build !windows

package main

// Slippi Launcher paths and sound playback are Windows-only. These stubs let the
// replay parsing build and test on other systems.

import (
	"os"
	"path/filepath"
)

func playFile(string) {}

func documentsDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "Documents")
}

func lowerPriority() {}

func ownsConsole() bool { return false }
