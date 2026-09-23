//go:build !windows && !linux

package main

// Unsupported systems (e.g. macOS): stubs so the replay parsing still builds and tests.

import (
	"os"
	"path/filepath"
)

func playFile(string) {}

func userJSONPaths() []string { return nil }

func defaultReplayDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "Slippi")
}

func lowerPriority() {}

func ownsConsole() bool { return false }
