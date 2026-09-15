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
        cross_checks: false,
        cross_check_backend: Default::default(),
        cross_check_configs: Default::default(),
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

fn transpile_and_compile(fixture_path: &Path) {
    // Keep every generated file out of the source checkout, including on failures.
    let temp_dir = tempfile::tempdir().expect("failed to create fixture directory");
    let c_path = temp_dir.path().join(fixture_path.file_name().unwrap());
    fs::copy(fixture_path, &c_path).expect("failed to copy C fixture");
    let runtime = c_path
        .file_stem()
        .unwrap()
        .to_string_lossy()
        .ends_with("_runtime");

    // Ensure clang accepts the C input.
    let status = Command::new("clang")
        .args(["-c", "-o", "/dev/null", "-w"])
        .arg(&c_path)
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
    let rust_output = c_path.with_extension(if runtime { "rust-bin" } else { "rlib" });

    // Runtime fixtures take addresses, emitting raw_ref_op attributes. Match the
    // upstream snapshot toolchain for them; keep the original compile checks on stable.
    let status = Command::new("rustc")
        .arg(if runtime {
            "+nightly-2023-04-15"
        } else {
            "+stable"
        })
        .args([
            "--crate-type",
            if runtime { "bin" } else { "lib" },
            "--edition",
            "2021",
            "--crate-name",
            &crate_name,
            "-o",
            rust_output.to_str().unwrap(),
            "-Awarnings",
        ])
        .arg(&rs_path)
        .status()
        .expect("failed to run rustc");
    assert!(status.success(), "rustc failed for {}", c_path.display());

    if runtime {
        let c_output = c_path.with_extension("c-bin");
        let status = Command::new("clang")
            .arg(&c_path)
            .arg("-o")
            .arg(&c_output)
            .status()
            .expect("failed to build C executable");
        assert!(
            status.success(),
            "clang link failed for {}",
            c_path.display()
        );

        let expected = Command::new(&c_output)
            .output()
            .expect("failed to run C executable");
        assert!(
            expected.status.success(),
            "C fixture {} failed its own checks: {:?}",
            fixture_path.display(),
            expected
        );
        let actual = Command::new(&rust_output)
            .output()
            .expect("failed to run Rust executable");
        assert_eq!(
            actual.status.code(),
            expected.status.code(),
            "runtime result differs for {}: {:?}",
            fixture_path.display(),
            actual
        );
        assert_eq!(actual.stdout, expected.stdout);
        assert_eq!(actual.stderr, expected.stderr);
    }
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
