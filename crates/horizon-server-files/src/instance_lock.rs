//! A supervisor and the launcher share this guard while starting, running or deleting a server.
//! The outside lock remains open during a directory move on Windows; the legacy inside lock
//! still detects a supervisor from before this guard was introduced.
use std::fs::{self, File};
use std::io;
use std::path::Path;

#[derive(Debug)]
pub struct InstanceLock {
    _legacy: Option<File>,
    _outside: File,
}

impl InstanceLock {
    /// Keep this guard alive through the move. Only the inside handle must close on Windows.
    pub fn prepare_move(&mut self) {
        #[cfg(windows)]
        self._legacy.take();
    }
}

fn locked(file: &File) -> io::Result<bool> {
    match file.try_lock() {
        Ok(()) => Ok(true),
        Err(std::fs::TryLockError::WouldBlock) => Ok(false),
        Err(std::fs::TryLockError::Error(e)) => Err(e),
    }
}

fn open(path: &Path) -> io::Result<File> {
    File::options()
        .create(true)
        .truncate(false)
        .write(true)
        .open(path)
}

/// None means another supervisor or deletion owns the folder. Do not remove outside lock
/// files on release: unlinking one could let two processes lock different files for one path.
pub fn try_lock(dir: &Path) -> io::Result<Option<InstanceLock>> {
    let canonical = dir.canonicalize()?;
    let parent = canonical
        .parent()
        .ok_or_else(|| io::Error::other("a server needs a parent folder"))?;
    let name = canonical
        .file_name()
        .ok_or_else(|| io::Error::other("a server needs a folder name"))?;
    let guard_name = if name
        .to_string_lossy()
        .eq_ignore_ascii_case(".horizon-server-locks")
    {
        ".horizon-server-locks.guard"
    } else {
        ".horizon-server-locks"
    };
    let outside_dir = parent.join(guard_name);
    fs::create_dir_all(&outside_dir)?;
    let outside = open(&outside_dir.join(name))?;
    if !locked(&outside)? {
        return Ok(None);
    }
    // Deletion may have finished while this process waited to acquire the outside guard.
    // Never recreate a deleted server just to put its legacy lock back.
    if !canonical.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "the server folder was removed",
        ));
    }
    let state = canonical.join(".horizon");
    fs::create_dir_all(&state)?;
    let legacy = open(&state.join("lock"))?;
    if !locked(&legacy)? {
        return Ok(None);
    }
    Ok(Some(InstanceLock {
        _legacy: Some(legacy),
        _outside: outside,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    fn fixture() -> (PathBuf, PathBuf) {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "horizon-instance-lock-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        assert!(!root.exists());
        let dir = root.join("server");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("server.toml"), "[server]").unwrap();
        (root, dir)
    }

    #[test]
    fn another_instance_waits_until_the_guard_closes() {
        let (root, dir) = fixture();
        let guard = try_lock(&dir).unwrap().unwrap();
        assert!(try_lock(&dir.join(".")).unwrap().is_none());
        let other = root.join("other");
        fs::create_dir_all(&other).unwrap();
        drop(try_lock(&other).unwrap().unwrap());
        drop(guard);
        drop(try_lock(&dir).unwrap().unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_legacy_supervisor_also_prevents_deletion() {
        let (root, dir) = fixture();
        fs::create_dir_all(dir.join(".horizon")).unwrap();
        let legacy = open(&dir.join(".horizon/lock")).unwrap();
        legacy.try_lock().unwrap();
        assert!(try_lock(&dir).unwrap().is_none());
        drop(legacy);
        drop(try_lock(&dir).unwrap().unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn moving_releases_inside_handle_but_keeps_startup_excluded() {
        let (root, dir) = fixture();
        let mut guard = try_lock(&dir).unwrap().unwrap();
        guard.prepare_move();
        // This covers the gap between closing the legacy handle and moving the directory.
        assert!(try_lock(&dir).unwrap().is_none());
        let moved = root.join("moved");
        fs::rename(&dir, &moved).unwrap();
        assert_eq!(
            fs::read_to_string(moved.join("server.toml")).unwrap(),
            "[server]"
        );
        assert!(try_lock(&dir).is_err());
        assert!(!dir.exists());
        drop(guard);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_server_named_like_the_guard_directory_can_still_move() {
        let (root, original) = fixture();
        let dir = root.join(".horizon-server-locks");
        fs::rename(original, &dir).unwrap();
        let mut guard = try_lock(&dir).unwrap().unwrap();
        guard.prepare_move();
        assert!(try_lock(&dir).unwrap().is_none());
        fs::rename(&dir, root.join("moved")).unwrap();
        drop(guard);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn a_failed_move_does_not_leave_the_original_folder_locked() {
        let (root, dir) = fixture();
        let mut guard = try_lock(&dir).unwrap().unwrap();
        guard.prepare_move();
        assert!(fs::rename(&dir, root.join("missing/target")).is_err());
        assert!(try_lock(&dir).unwrap().is_none());
        drop(guard);
        drop(try_lock(&dir).unwrap().unwrap());
        assert!(dir.join("server.toml").is_file());
        fs::remove_dir_all(root).unwrap();
    }
}
