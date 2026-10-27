//! The Start with Windows menu item, driven through the autostart interface with a fake in
//! place of the Windows registry.

use std::cell::{Cell, RefCell};

use tray_shell::autostart::{Autostart, checked_at_menu_build, toggle};

/// Remembers whether autostart is on, like the registry entry would, and can be told to fail.
#[derive(Default)]
struct FakeAutostart {
    enabled: Cell<bool>,
    fail_reads: Cell<bool>,
    fail_changes: Cell<bool>,
    calls: RefCell<Vec<&'static str>>,
}

impl Autostart for FakeAutostart {
    fn is_enabled(&self) -> Result<bool, String> {
        if self.fail_reads.get() {
            return Err("registry unreadable".to_owned());
        }
        Ok(self.enabled.get())
    }

    fn enable(&self) -> Result<(), String> {
        self.calls.borrow_mut().push("enable");
        if self.fail_changes.get() {
            return Err("access denied".to_owned());
        }
        self.enabled.set(true);
        Ok(())
    }

    fn disable(&self) -> Result<(), String> {
        self.calls.borrow_mut().push("disable");
        if self.fail_changes.get() {
            return Err("access denied".to_owned());
        }
        self.enabled.set(false);
        Ok(())
    }
}

#[test]
fn a_fresh_install_shows_start_with_windows_unchecked() {
    let autostart = FakeAutostart::default();

    assert!(!checked_at_menu_build(&autostart));
    assert!(
        autostart.calls.borrow().is_empty(),
        "building the menu must not change autostart"
    );
}

#[test]
fn the_menu_shows_autostart_already_enabled_outside_the_app() {
    let autostart = FakeAutostart::default();
    autostart.enabled.set(true);

    assert!(checked_at_menu_build(&autostart));
}

#[test]
fn toggling_when_off_enables_autostart_and_checks_the_item() {
    let autostart = FakeAutostart::default();

    assert!(toggle(&autostart));
    assert!(autostart.enabled.get());
}

#[test]
fn toggling_when_on_disables_autostart_and_unchecks_the_item() {
    let autostart = FakeAutostart::default();
    autostart.enabled.set(true);

    assert!(!toggle(&autostart));
    assert!(!autostart.enabled.get());
}

#[test]
fn a_failed_enable_leaves_the_item_unchecked() {
    let autostart = FakeAutostart::default();
    autostart.fail_changes.set(true);

    assert!(!toggle(&autostart));
    assert_eq!(*autostart.calls.borrow(), ["enable"]);
}

#[test]
fn a_failed_disable_leaves_the_item_checked() {
    let autostart = FakeAutostart::default();
    autostart.enabled.set(true);
    autostart.fail_changes.set(true);

    assert!(toggle(&autostart));
    assert_eq!(*autostart.calls.borrow(), ["disable"]);
}

#[test]
fn an_unreadable_state_shows_unchecked_and_changes_nothing() {
    // Without knowing the current state, a toggle could only guess which way to go.
    let autostart = FakeAutostart::default();
    autostart.fail_reads.set(true);

    assert!(!checked_at_menu_build(&autostart));
    assert!(!toggle(&autostart));
    assert!(autostart.calls.borrow().is_empty());
}
