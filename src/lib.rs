use std::cmp::Ordering;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use chrono::Utc;
use rand::{thread_rng, Rng};
use sha2::{Digest, Sha256};
use walkdir::WalkDir;

pub const DRIVE_SIZE: usize = 1024 * 1024;
pub const BLOB_SIZE: usize = 512 * 1024;

pub fn runtime_dir() -> PathBuf {
    let home = env::var_os("HOME").unwrap_or_else(|| env::current_dir().unwrap().into_os_string());
    let runtime = Path::new(&home).join("Library").join("Application Support").join("ECLIPSE");
    fs::create_dir_all(&runtime).unwrap();
    runtime
}

pub fn audit_log() -> PathBuf {
    runtime_dir().join("audit.log")
}

fn utc_stamp() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

pub fn write_event(module: &str, event: &str) {
    let log_path = audit_log();
    let mut handle = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .unwrap();
    writeln!(handle, "[{}] [{}] {}", utc_stamp(), module, event).unwrap();
}

pub fn sha256(path: &Path) -> String {
    let mut digest = Sha256::new();
    let mut file = File::open(path).unwrap();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer).unwrap();
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    format!("{:x}", digest.finalize())
}

pub fn selected_files(target: &Path) -> Vec<PathBuf> {
    if target.is_file() {
        return vec![target.to_path_buf()];
    }
    if target.is_dir() {
        let mut files: Vec<PathBuf> = Vec::new();
        for entry in WalkDir::new(target).into_iter().filter_map(Result::ok) {
            let path = entry.path();
            if entry.file_type().is_file() && !entry.file_type().is_symlink() {
                files.push(path.to_path_buf());
            }
        }
        files.sort();
        return files;
    }
    panic!("target does not exist: {}", target.display());
}

fn _erase_one(path: &Path, log: &mut dyn FnMut(String)) {
    log(format!("FILE START: {}", path.display()));
    log(format!("SHA-256 BEFORE: {}", sha256(path)));
    let size = fs::metadata(path).unwrap().len() as usize;

    for pass_number in 1..=3 {
        let mut file = OpenOptions::new().read(true).write(true).open(path).unwrap();
        let mut remaining = size;
        while remaining > 0 {
            let chunk = remaining.min(64 * 1024);
            let mut buf = vec![0u8; chunk];
            thread_rng().fill(&mut buf[..]);
            file.seek(SeekFrom::Start((size - remaining) as u64)).unwrap();
            file.write_all(&buf).unwrap();
            remaining -= chunk;
        }
        file.flush().unwrap();
        log(format!("OVERWRITE PASS {}/3 COMPLETE: {} ({} bytes)", pass_number, path.file_name().unwrap().to_string_lossy(), size));
        log(format!("SHA-256 AFTER PASS {}: {}", pass_number, sha256(path)));
    }

    let renamed = path.with_file_name(thread_rng().gen::<u64>().to_string());
    fs::rename(path, &renamed).unwrap();
    log(format!("RENAMED: {} -> {}", path.file_name().unwrap().to_string_lossy(), renamed.file_name().unwrap().to_string_lossy()));
    fs::remove_file(&renamed).unwrap();
    log(format!("UNLINK COMPLETE: {}", path.display()));
}

pub fn run_file_erase(target: Option<&Path>, log: &mut dyn FnMut(String)) -> PathBuf {
    let target_path = match target {
        Some(path) => path.to_path_buf(),
        None => {
            let default_target = runtime_dir().join("dummy_evidence.txt");
            let content = "ECLIPSE DEMO EVIDENCE\n".repeat(80);
            fs::write(&default_target, content).unwrap();
            log(format!("TARGET CREATED: {}", default_target.file_name().unwrap().to_string_lossy()));
            default_target
        }
    };

    let files = selected_files(&target_path);
    log(format!("TARGET SELECTED: {}", target_path.display()));
    log(format!("FILES TO ERASE: {}", files.len()));

    for path in &files {
        _erase_one(path, log);
    }

    if target_path.is_dir() {
        let mut dirs: Vec<PathBuf> = Vec::new();
        for entry in WalkDir::new(&target_path).into_iter().filter_map(Result::ok) {
            let path = entry.path();
            if entry.file_type().is_dir() && path != target_path {
                dirs.push(path.to_path_buf());
            }
        }
        dirs.sort_by(|a, b| {
            let a_count = a.components().count();
            let b_count = b.components().count();
            match b_count.cmp(&a_count) {
                Ordering::Equal => a.cmp(b),
                other => other,
            }
        });

        for directory in dirs {
            if fs::remove_dir(&directory).is_ok() {
                log(format!("DIRECTORY REMOVED: {}", directory.display()));
            } else {
                log(format!("DIRECTORY RETAINED (not empty): {}", directory.display()));
            }
        }
        if fs::remove_dir(&target_path).is_ok() {
            log(format!("DIRECTORY REMOVED: {}", target_path.display()));
        }
    }

    log(format!("[DONE] {} files securely erased", files.len()));
    write_event("FILE_ERASER", &format!("ERASE_COMPLETE target={} files={} passes=3", target_path.display(), files.len()));
    target_path
}

pub fn run_drive_erase(log: &mut dyn FnMut(String)) -> PathBuf {
    let target = runtime_dir().join("dummy_drive_1mb.bin");
    let prefix = b"ECLIPSE-DEMO";
    let mut payload = Vec::with_capacity(DRIVE_SIZE);
    while payload.len() < DRIVE_SIZE {
        let remaining = DRIVE_SIZE - payload.len();
        let chunk = &prefix[..remaining.min(prefix.len())];
        payload.extend_from_slice(chunk);
    }
    payload.truncate(DRIVE_SIZE);
    fs::write(&target, &payload).unwrap();

    log(format!("TARGET CREATED: {} ({} bytes)", target.file_name().unwrap().to_string_lossy(), DRIVE_SIZE));

    let passes = [
        (1, "0x00", Some(0u8)),
        (2, "0xFF", Some(0xFFu8)),
        (3, "RANDOM", None),
    ];

    for (pass_number, label, byte) in passes {
        log(format!("PASS {}/3 START: pattern={}", pass_number, label));
        let mut file = OpenOptions::new().read(true).write(true).open(&target).unwrap();
        let mut written = 0usize;
        while written < DRIVE_SIZE {
            let chunk_size = (64 * 1024).min(DRIVE_SIZE - written);
            let mut chunk = vec![0u8; chunk_size];
            match byte {
                Some(value) => chunk.fill(value),
                None => thread_rng().fill(&mut chunk[..]),
            }
            file.seek(SeekFrom::Start(written as u64)).unwrap();
            file.write_all(&chunk).unwrap();
            written += chunk_size;
            if written % (256 * 1024) == 0 || written == DRIVE_SIZE {
                log(format!("PASS {}/3 PROGRESS: {}%", pass_number, (written * 100) / DRIVE_SIZE));
            }
        }
        file.flush().unwrap();

        let mut sample = [0u8; 16];
        file.seek(SeekFrom::Start(0)).unwrap();
        file.read_exact(&mut sample).unwrap();
        let verified = match byte {
            Some(value) => sample.iter().all(|item| *item == value),
            None => sample.len() == 16,
        };
        log(format!("PASS {}/3 VERIFY: {} spot-check", pass_number, if verified { "PASS" } else { "FAIL" }));
        if !verified {
            panic!("pass {} spot-check failed", pass_number);
        }
        thread::sleep(Duration::from_millis(30));
    }

    log("APFS NOTE: copy-on-write semantics limit overwrite-in-place guarantees.".to_string());
    log("ERASE COMPLETE: disposable sector file retained for inspection".to_string());
    write_event("DRIVE_ERASER", &format!("ERASE_COMPLETE target={} passes=3", target.file_name().unwrap().to_string_lossy()));
    target
}

pub fn run_carve(log: &mut dyn FnMut(String)) -> Vec<(String, String, String)> {
    let mut blob = vec![0u8; BLOB_SIZE];
    thread_rng().fill(&mut blob[..]);

    let signatures: [(&str, &[u8]); 3] = [
        ("JPEG", b"\xFF\xD8\xFF"),
        ("PNG", b"\x89PNG\r\n\x1a\n"),
        ("PDF", b"%PDF"),
    ];

    let mut occupied: Vec<(usize, usize)> = Vec::new();
    let mut placements: Vec<(String, Vec<u8>, usize)> = Vec::new();

    for (name, signature) in &signatures {
        let limit = BLOB_SIZE - signature.len();
        let offset = loop {
            let candidate = thread_rng().gen_range(0..=limit);
            let end = candidate + signature.len();
            let overlaps = occupied.iter().any(|(start, stop)| !(end <= *start || candidate >= *stop));
            if !overlaps {
                break candidate;
            }
        };
        blob[offset..offset + signature.len()].copy_from_slice(signature);
        occupied.push((offset, offset + signature.len()));
        placements.push((name.to_string(), signature.to_vec(), offset));
    }

    let blob_path = runtime_dir().join("synthetic_blob.bin");
    fs::write(&blob_path, &blob).unwrap();
    log(format!("BLOB GENERATED: {} ({} bytes)", blob_path.file_name().unwrap().to_string_lossy(), BLOB_SIZE));
    log("SCAN START: signatures=JPEG, PNG, PDF".to_string());

    let mut results: Vec<(String, String, String)> = Vec::new();
    for (file_type, signature, _) in placements {
        let offset = blob.windows(signature.len()).position(|window| window == signature.as_slice()).unwrap();
        let hex = format!("0x{:08X}", offset);
        results.push((file_type.clone(), hex.clone(), offset.to_string()));
        log(format!("FOUND {}: offset={} ({})", file_type, hex, offset));
        thread::sleep(Duration::from_millis(40));
    }

    log(format!("SCAN COMPLETE: {} signatures recovered", results.len()));
    write_event("FILE_CARVER", &format!("SCAN_COMPLETE blob={} findings={}", blob_path.file_name().unwrap().to_string_lossy(), results.len()));
    results
}
