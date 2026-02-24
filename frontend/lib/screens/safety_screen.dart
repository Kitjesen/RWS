/// 安全管控 Safety Screen — preflight checklist + NFZ management + IFF whitelist.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';
import '../widgets/preflight_widget.dart';
import '../widgets/safety_zones_widget.dart';
import '../widgets/iff_widget.dart';

class SafetyScreen extends StatelessWidget {
  const SafetyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final api = Provider.of<TrackingProvider>(context, listen: false).api;

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
              return _wideLayout(api);
            }
            return _narrowLayout(api);
          },
        ),
      ),
    );
  }

  /// Two-panel side-by-side layout for wide screens (tablet / desktop).
  Widget _wideLayout(api) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Preflight checklist — spans full width at the top
        PreflightWidget(api: api),
        const SizedBox(height: 12),
        // NFZ + IFF side by side below
        const Expanded(
          child: Row(
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
          ),
        ),
      ],
    );
  }

  /// Stacked layout for narrow screens (phone).
  Widget _narrowLayout(api) {
    return ListView(
      children: [
        PreflightWidget(api: api),
        const SizedBox(height: 12),
        const SizedBox(height: 380, child: SafetyZonesWidget()),
        const SizedBox(height: 12),
        const SizedBox(height: 380, child: IffWidget()),
      ],
    );
  }
}
