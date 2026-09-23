use std::env;
use std::path::PathBuf;

use eclipse::{audit_log, run_carve, run_drive_erase, run_file_erase};

fn print_json<T: serde::Serialize>(value: &T) {
    println!("{}", serde_json::to_string(value).unwrap());
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let command = args.first().map(String::as_str).unwrap_or("all");

    let mut log = |line: String| println!("{}", line);

    match command {
        "drive" => {
            let _ = run_drive_erase(&mut log);
        }
        "file" => {
            let target = args.get(1).map(PathBuf::from).or_else(|| Some(std::env::current_dir().unwrap().join("dummy_evidence.txt")));
            let _ = run_file_erase(target.as_deref(), &mut log);
        }
        "carve" => {
            let results = run_carve(&mut log);
            print_json(&results);
        }
        "audit" => {
            println!("{}", audit_log().display());
        }
        "all" | _ => {
            let _drive_target = run_drive_erase(&mut log);
            let _file_target = run_file_erase(None, &mut log);
            let _carve_results = run_carve(&mut log);
            println!("audit log: {}", audit_log().display());
        }
    }
}
