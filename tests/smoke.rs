use std::fs;

use eclipse::{
    audit_log, runtime_dir, run_carve, run_drive_erase, run_file_erase,
    BLOB_SIZE, DRIVE_SIZE,
};

#[test]
fn smoke_test() {
    let runtime = runtime_dir();
    let mut logs = Vec::new();

    {
        let mut log = |line: String| logs.push(line);

        let drive_target = run_drive_erase(&mut log);
        assert_eq!(drive_target.parent().unwrap(), runtime);
        assert_eq!(fs::metadata(&drive_target).unwrap().len(), DRIVE_SIZE as u64);

        let file_target = run_file_erase(None, &mut log);
        assert!(!file_target.exists());

        let temp_dir = tempfile::tempdir().unwrap();
        let folder_path = temp_dir.path().join("target");
        let nested_path = folder_path.join("nested");
        fs::create_dir_all(&nested_path).unwrap();
        fs::write(folder_path.join("one.txt"), "one").unwrap();
        fs::write(nested_path.join("two.txt"), "two").unwrap();

        run_file_erase(Some(folder_path.as_path()), &mut log);
        assert!(!folder_path.exists());
    }

    assert!(logs.iter().any(|line| line.contains("[DONE] 2 files securely erased")));

    let results = {
        let mut log = |line: String| logs.push(line);
        run_carve(&mut log)
    };

    assert_eq!(results.iter().map(|(kind, _, _)| kind.as_str()).collect::<Vec<_>>(), vec!["JPEG", "PNG", "PDF"]);
    assert_eq!(runtime.join("synthetic_blob.bin").metadata().unwrap().len(), BLOB_SIZE as u64);
    assert!(results.iter().all(|(_, _, offset)| offset.parse::<i64>().unwrap() >= 0));
    assert!(audit_log().exists());
    assert!(logs.len() > 15);
}
