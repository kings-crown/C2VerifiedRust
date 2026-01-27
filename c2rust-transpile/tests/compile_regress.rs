use std::fs;
use std::path::Path;
use std::process::Command;

use c2rust_transpile::{ReplaceMode, TranspilerConfig};

fn config() -> TranspilerConfig {
    TranspilerConfig {
        dump_untyped_context: false,
        dump_typed_context: false,
        pretty_typed_context: false,
        dump_function_cfgs: false,
        json_function_cfgs: false,
        dump_cfg_liveness: false,
        dump_structures: false,
        verbose: false,
        debug_ast_exporter: false,
        emit_c_decl_map: false,
        incremental_relooper: true,
        fail_on_multiple: false,
        filter: None,
        debug_relooper_labels: false,
        prefix_function_names: None,
        translate_asm: true,
        use_c_loop_info: true,
        use_c_multiple_info: true,
        simplify_structures: true,
        panic_on_translator_failure: false,
        emit_modules: false,
        fail_on_error: true,
        replace_unsupported_decls: ReplaceMode::Extern,
        translate_valist: true,
        overwrite_existing: true,
        reduce_type_annotations: false,
        reorganize_definitions: false,
        enabled_warnings: Default::default(),
        emit_no_std: false,
        output_dir: None,
        translate_const_macros: Default::default(),
        translate_fn_macros: Default::default(),
        disable_rustfmt: false,
        disable_refactoring: false,
        preserve_unused_functions: false,
        log_level: log::LevelFilter::Warn,
        emit_build_files: false,
        binaries: Vec::new(),
        c2rust_dir: Some(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .to_path_buf(),
        ),
    }
}

fn transpile_and_compile(c_path: &Path) {
    // Ensure clang accepts the C input.
    let status = Command::new("clang")
        .args(["-c", "-o", "/dev/null", "-w"])
        .arg(c_path)
        .status()
        .expect("failed to run clang");
    assert!(status.success(), "clang failed for {}", c_path.display());

    // Transpile to Rust.
    let (_tmp, compile_commands) =
        c2rust_transpile::create_temp_compile_commands(&[c_path.to_owned()]);
    c2rust_transpile::transpile(config(), &compile_commands, &["-w"]);

    // Build the generated Rust to catch type issues.
    let rs_path = c_path.with_extension("rs");
    let crate_name = c_path
        .file_stem()
        .unwrap()
        .to_string_lossy()
        .replace('.', "_");
    let rlib_path = c_path.with_extension("rlib");

    let status = Command::new("rustc")
        .args([
            "--crate-type",
            "lib",
            "--edition",
            "2021",
            "--crate-name",
            &crate_name,
            "-o",
            rlib_path.to_str().unwrap(),
            "-Awarnings",
        ])
        .arg(&rs_path)
        .status()
        .expect("failed to run rustc");
    assert!(status.success(), "rustc failed for {}", c_path.display());

    let _ = fs::remove_file(rlib_path);
    let _ = fs::remove_file(rs_path);
}

#[test]
fn compile_regressions() {
    for entry in fs::read_dir("tests/compile_regress").unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) == Some("c") {
            transpile_and_compile(&path);
        }
    }
}

