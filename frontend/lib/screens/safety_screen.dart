/// 安全管控 Safety Screen — NFZ management + IFF whitelist side by side.
library;

import 'package:flutter/material.dart';
import '../widgets/safety_zones_widget.dart';
import '../widgets/iff_widget.dart';

class SafetyScreen extends StatelessWidget {
  const SafetyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.security, size: 20),
            SizedBox(width: 8),
            Text('安全管控 Safety'),
          ],
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: LayoutBuilder(
          builder: (context, constraints) {
            if (constraints.maxWidth > 700) {
              return _wideLayout();
            }
            return _narrowLayout();
          },
        ),
      ),
    );
  }

  /// Two-panel side-by-side layout for wide screens (tablet / desktop).
  Widget _wideLayout() {
    return const Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Left panel: No-Fire Zones
        Expanded(
          child: SafetyZonesWidget(),
        ),
        SizedBox(width: 12),
        // Right panel: IFF whitelist
        Expanded(
          child: IffWidget(),
        ),
      ],
    );
  }

  /// Stacked layout for narrow screens (phone).
  Widget _narrowLayout() {
    return ListView(
      children: const [
        SizedBox(height: 380, child: SafetyZonesWidget()),
        SizedBox(height: 12),
        SizedBox(height: 380, child: IffWidget()),
      ],
    );
  }
}
