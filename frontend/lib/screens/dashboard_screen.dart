import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';
import '../widgets/status_card.dart';
import '../widgets/error_chart.dart';
import '../widgets/gimbal_indicator.dart';
import '../widgets/control_panel.dart';
import '../widgets/video_feed.dart';
import '../widgets/metrics_card.dart';
import '../widgets/system_health_widget.dart';
import '../widgets/fire_control_widget.dart';
import '../widgets/threat_queue_widget.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('RWS Tracking Dashboard'),
        actions: [
          Consumer<TrackingProvider>(
            builder: (_, p, __) => Row(
              children: [
                Icon(
                  p.connected ? Icons.wifi : Icons.wifi_off,
                  color: p.connected ? Colors.green : Colors.red,
                ),
                const SizedBox(width: 16),
              ],
            ),
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: LayoutBuilder(
          builder: (context, constraints) {
            if (constraints.maxWidth > 1200) {
              return _wideLayout();
            } else if (constraints.maxWidth > 800) {
              return _mediumLayout();
            }
            return _narrowLayout();
          },
        ),
      ),
    );
  }

  Widget _wideLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 左列: 视频 + 云台
        Expanded(
          flex: 3,
          child: Column(
            children: [
              const Expanded(flex: 3, child: VideoFeedWidget()),
              const SizedBox(height: 12),
              const Expanded(flex: 2, child: GimbalIndicator()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 中列: 图表
        Expanded(
          flex: 3,
          child: Column(
            children: [
              const Expanded(flex: 1, child: StatusCard()),
              const SizedBox(height: 12),
              const Expanded(flex: 2, child: ErrorChartWidget()),
              const SizedBox(height: 12),
              const Expanded(flex: 1, child: MetricsCard()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 右列: 控制面板 + 新面板
        Expanded(
          flex: 2,
          child: Column(
            children: [
              const Expanded(flex: 2, child: SystemHealthWidget()),
              const SizedBox(height: 12),
              const Expanded(flex: 3, child: FireControlWidget()),
              const SizedBox(height: 12),
              const Expanded(flex: 3, child: ThreatQueueWidget()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 最右列: 控制面板
        const Expanded(flex: 2, child: ControlPanel()),
      ],
    );
  }

  Widget _mediumLayout() {
    return Column(
      children: [
        Expanded(
          flex: 2,
          child: Row(
            children: [
              const Expanded(flex: 2, child: VideoFeedWidget()),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  children: [
                    const Expanded(child: StatusCard()),
                    const SizedBox(height: 12),
                    const Expanded(child: MetricsCard()),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          flex: 2,
          child: Row(
            children: [
              const Expanded(child: ErrorChartWidget()),
              const SizedBox(width: 12),
              const Expanded(child: ControlPanel()),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          flex: 2,
          child: Row(
            children: [
              const Expanded(child: SystemHealthWidget()),
              const SizedBox(width: 12),
              const Expanded(child: FireControlWidget()),
              const SizedBox(width: 12),
              const Expanded(child: ThreatQueueWidget()),
            ],
          ),
        ),
      ],
    );
  }

  Widget _narrowLayout() {
    return ListView(
      children: const [
        SizedBox(height: 250, child: VideoFeedWidget()),
        SizedBox(height: 12),
        SizedBox(height: 120, child: StatusCard()),
        SizedBox(height: 12),
        SizedBox(height: 200, child: ErrorChartWidget()),
        SizedBox(height: 12),
        SizedBox(height: 120, child: MetricsCard()),
        SizedBox(height: 12),
        SizedBox(height: 400, child: ControlPanel()),
        SizedBox(height: 12),
        SizedBox(height: 200, child: SystemHealthWidget()),
        SizedBox(height: 12),
        SizedBox(height: 280, child: FireControlWidget()),
        SizedBox(height: 12),
        SizedBox(height: 300, child: ThreatQueueWidget()),
      ],
    );
  }
}
