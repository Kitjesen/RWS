// Web implementation — opens URL in a new browser tab.
// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;

void launchExternalUrl(String url) {
  html.window.open(url, '_blank');
}
