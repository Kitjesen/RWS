/// Cross-platform URL launcher.
///
/// On Flutter web this opens a new browser tab.
/// On other platforms this is a no-op (extend as needed).
export 'launch_url_stub.dart'
    if (dart.library.html) 'launch_url_web.dart';
