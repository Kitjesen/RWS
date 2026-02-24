import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';
import '../services/event_stream.dart';
import '../widgets/alert_banner.dart';
import '../widgets/status_card.dart';
import '../widgets/error_chart.dart';
import '../widgets/gimbal_indicator.dart';
import '../widgets/control_panel.dart';
import '../widgets/video_feed.dart';
import '../widgets/metrics_card.dart';
import '../widgets/system_health_widget.dart';
import '../widgets/fire_control_widget.dart';
import '../widgets/threat_queue_widget.dart';
import '../widgets/mission_control_widget.dart';
import '../widgets/preflight_widget.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('RWS 火控指挥中心'),
        actions: [
          Consumer<TrackingProvider>(
            builder: (_, p, __) => Row(
              children: [
                Consumer<EventStreamService>(
                builder: (_, es, __) => Tooltip(
                  message: es.connected ? 'SSE 已连接' : 'SSE 已断开',
                  child: Icon(
                    es.connected ? Icons.bolt : Icons.bolt_outlined,
                    color: es.connected ? Colors.amber : Colors.grey,
                  ),
                ),
              ),
              const SizedBox(width: 8),
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
      body: AlertBannerOverlay(
        child: Padding(
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
      ),  // AlertBannerOverlay
    );
  }

  /// 右列公共 TabBar 视图：作战 Tab + 调参 Tab
  Widget _rightTabColumn() {
    return DefaultTabController(
      length: 2,
      child: Column(
        children: [
          TabBar(
            tabs: const [
              Tab(text: '作战'),
              Tab(text: '调参'),
            ],
          ),
          Expanded(
            child: TabBarView(
              children: [
                // 作战 Tab
                Column(
                  children: const [
                    SizedBox(height: 8),
                    Expanded(flex: 2, child: FireControlWidget()),
                    SizedBox(height: 8),
                    Expanded(flex: 2, child: ThreatQueueWidget()),
                    SizedBox(height: 8),
                    Expanded(flex: 1, child: MissionControlWidget()),
                  ],
                ),
                // 调参 Tab
                Column(
                  children: [
                    const SizedBox(height: 8),
                    const Expanded(flex: 2, child: ControlPanel()),
                    const SizedBox(height: 8),
                    Expanded(
                      flex: 1,
                      child: Builder(
                        builder: (ctx) => PreflightWidget(
                          api: ctx.read<TrackingProvider>().api,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 宽屏布局（> 1200px）：3 列
  /// 左列 flex:5 — VideoFeed + GimbalIndicator(固定 160px)
  /// 中列 flex:4 — StatusCard + ErrorChartWidget + MetricsCard + SystemHealthWidget
  /// 右列 flex:3 — TabBar [作战 / 调参]
  Widget _wideLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 左列: 视频 + 云台
        Expanded(
          flex: 5,
          child: Column(
            children: const [
              Expanded(flex: 3, child: VideoFeedWidget()),
              SizedBox(height: 12),
              SizedBox(height: 160, child: GimbalIndicator()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 中列: 状态 + 图表 + 指标 + 健康
        Expanded(
          flex: 4,
          child: Column(
            children: const [
              Expanded(flex: 1, child: StatusCard()),
              SizedBox(height: 12),
              Expanded(flex: 2, child: ErrorChartWidget()),
              SizedBox(height: 12),
              Expanded(flex: 1, child: MetricsCard()),
              SizedBox(height: 12),
              Expanded(flex: 1, child: SystemHealthWidget()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 右列: TabBar 作战 / 调参
        Expanded(
          flex: 3,
          child: _rightTabColumn(),
        ),
      ],
    );
  }

  /// 中等屏布局（800-1200px）：3 列，flex 比例收窄
  /// 左列 flex:4 — VideoFeed + GimbalIndicator(固定 140px)
  /// 中列 flex:3 — StatusCard + ErrorChartWidget + MetricsCard + SystemHealthWidget
  /// 右列 flex:3 — TabBar [作战 / 调参]
  Widget _mediumLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 左列: 视频 + 云台
        Expanded(
          flex: 4,
          child: Column(
            children: const [
              Expanded(flex: 3, child: VideoFeedWidget()),
              SizedBox(height: 12),
              SizedBox(height: 140, child: GimbalIndicator()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 中列: 状态 + 图表 + 指标 + 健康
        Expanded(
          flex: 3,
          child: Column(
            children: const [
              Expanded(flex: 1, child: StatusCard()),
              SizedBox(height: 12),
              Expanded(flex: 2, child: ErrorChartWidget()),
              SizedBox(height: 12),
              Expanded(flex: 1, child: MetricsCard()),
              SizedBox(height: 12),
              Expanded(flex: 1, child: SystemHealthWidget()),
            ],
          ),
        ),
        const SizedBox(width: 12),
        // 右列: TabBar 作战 / 调参
        Expanded(
          flex: 3,
          child: _rightTabColumn(),
        ),
      ],
    );
  }

  Widget _narrowLayout() {
    return ListView(
      children: [
        const SizedBox(height: 250, child: VideoFeedWidget()),
        const SizedBox(height: 12),
        const SizedBox(height: 220, child: GimbalIndicator()),
        const SizedBox(height: 12),
        const SizedBox(height: 120, child: StatusCard()),
        const SizedBox(height: 12),
        const SizedBox(height: 200, child: ErrorChartWidget()),
        const SizedBox(height: 12),
        const SizedBox(height: 120, child: MetricsCard()),
        const SizedBox(height: 12),
        const SizedBox(height: 400, child: ControlPanel()),
        const SizedBox(height: 12),
        const SizedBox(height: 200, child: SystemHealthWidget()),
        const SizedBox(height: 12),
        SizedBox(
          height: 200,
          child: Builder(
            builder: (ctx) => PreflightWidget(
              api: ctx.read<TrackingProvider>().api,
            ),
          ),
        ),
        const SizedBox(height: 12),
        const SizedBox(height: 320, child: MissionControlWidget()),
        const SizedBox(height: 12),
        const SizedBox(height: 280, child: FireControlWidget()),
        const SizedBox(height: 12),
        const SizedBox(height: 300, child: ThreatQueueWidget()),
      ],
    );
  }
}
