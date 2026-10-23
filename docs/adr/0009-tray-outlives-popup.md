# Tray and menu outlive the popup webview

The tray icon and its menu are created at launch and never depend on the webview, so Refresh works before the popup has ever opened and a crashed or reloaded webview does not break the app. The popup is a frameless window that is recreated if its webview dies. The menu always offers Show versions because Linux trays do not report left-clicks.
