package browseruse

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const defaultFileSystemDir = ".browseruse"

// FileSystem provides a minimal, sandboxed filesystem similar to browser_use.
type FileSystem struct {
	Root string
}

func NewFileSystem(root string) (*FileSystem, error) {
	if root == "" {
		home, _ := os.UserHomeDir()
		if home == "" {
			home = os.TempDir()
		}
		root = filepath.Join(home, defaultFileSystemDir)
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	return &FileSystem{Root: root}, nil
}

func (fs *FileSystem) resolvePath(name string) (string, error) {
	if name == "" {
		return "", errors.New("file_name required")
	}
	if filepath.IsAbs(name) {
		return "", errors.New("absolute paths not allowed")
	}
	clean := filepath.Clean(name)
	if strings.HasPrefix(clean, "..") {
		return "", errors.New("path traversal not allowed")
	}
	return filepath.Join(fs.Root, clean), nil
}

func (fs *FileSystem) WriteFile(name, content string, appendMode, trailingNewline, leadingNewline bool) error {
	path, err := fs.resolvePath(name)
	if err != nil {
		return err
	}
	if leadingNewline {
		content = "\n" + content
	}
	if trailingNewline {
		content += "\n"
	}
	flag := os.O_CREATE | os.O_WRONLY
	if appendMode {
		flag |= os.O_APPEND
	} else {
		flag |= os.O_TRUNC
	}
	file, err := os.OpenFile(path, flag, 0o644)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = file.WriteString(content)
	return err
}

func (fs *FileSystem) ReplaceFile(name, oldStr, newStr string) error {
	path, err := fs.resolvePath(name)
	if err != nil {
		return err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	replaced := strings.ReplaceAll(string(data), oldStr, newStr)
	return os.WriteFile(path, []byte(replaced), 0o644)
}

func (fs *FileSystem) ReadFile(name string) (string, error) {
	path, err := fs.resolvePath(name)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func (fs *FileSystem) ListFiles() ([]string, error) {
	entries, err := os.ReadDir(fs.Root)
	if err != nil {
		return nil, err
	}
	files := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		files = append(files, entry.Name())
	}
	return files, nil
}

func (fs *FileSystem) Open(name string) (io.ReadCloser, error) {
	path, err := fs.resolvePath(name)
	if err != nil {
		return nil, err
	}
	return os.Open(path)
}
