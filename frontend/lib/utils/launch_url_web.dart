// Web implementation — opens URL in a new browser tab.
import 'package:web/web.dart' as web;

void launchExternalUrl(String url) {
  web.window.open(url, '_blank');
}
