// Release builds are a tray app with no console window; debug builds keep the console for logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tray_shell::run()
}
