# Source this file to use an existing Rust toolchain; nothing is installed.
carpatic_rust_env() {
    if command -v cargo >/dev/null 2>&1 && command -v rustc >/dev/null 2>&1; then return 0; fi
    for bin in "$HOME/.cargo/bin" \
        "$HOME/.local/share/flatpak/runtime/org.freedesktop.Sdk.Extension.rust-stable/x86_64/25.08/active/files/bin"; do
        if [ -x "$bin/cargo" ] && [ -x "$bin/rustc" ]; then
            PATH="$bin:$PATH"
            export PATH
            return 0
        fi
    done
    printf 'Rust 1.85+ and Cargo are required. Install a toolchain or add it to PATH.\n' >&2
    return 1
}
carpatic_rust_env
