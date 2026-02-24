import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/audio_service.dart';
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
          // 静音切换
          StatefulBuilder(
            builder: (ctx, setState) => IconButton(
              icon: Icon(
                AudioService().enabled ? Icons.volume_up : Icons.volume_off,
              ),
              tooltip: AudioService().enabled ? '静音' : '开启声音',
              onPressed: () {
                AudioService().setEnabled(!AudioService().enabled);
                setState(() {});
              },
            ),
          ),
          // 调参 Drawer 入口
          Builder(
            builder: (ctx) => IconButton(
              icon: const Icon(Icons.tune),
              tooltip: '调参 / 预飞检查',
              onPressed: () => Scaffold.of(ctx).openEndDrawer(),
            ),
          ),
          Consumer<TrackingProvider>(
            builder: (_, p, __) => Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // SSE bolt indicator
                  Consumer<EventStreamService>(
                    builder: (_, es, __) => Tooltip(
                      message: es.connected ? 'SSE 已连接' : 'SSE 已断开',
                      child: Icon(
                        es.connected ? Icons.bolt : Icons.bolt_outlined,
                        color: es.connected ? Colors.amber : Colors.grey,
                        size: 18,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  // Connection status dot + label
                  if (p.connected)
                    Tooltip(
                      message: '已连接 · ${p.status.fps.toStringAsFixed(1)} FPS',
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            width: 8,
                            height: 8,
                            decoration: const BoxDecoration(
                              color: Colors.green,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 4),
                          const Text(
                            'LIVE',
                            style: TextStyle(
                              fontSize: 10,
                              color: Colors.green,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                    )
                  else
                    Tooltip(
                      message: '连接中断 · ${p.error}',
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            width: 8,
                            height: 8,
                            decoration: const BoxDecoration(
                              color: Colors.red,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 4),
                          const Text(
                            '离线',
                            style: TextStyle(
                              fontSize: 10,
                              color: Colors.red,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
      // 调参抽屉 — 不占用主战斗视图空间
      endDrawer: const _TuningDrawer(),
      body: AlertBannerOverlay(
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth > 1100) return _wideLayout();
              if (constraints.maxWidth > 720) return _mediumLayout();
              return _narrowLayout();
            },
          ),
        ),
      ),
    );
  }

  /// 宽屏（> 1100px）：三列全战斗视图，无 Tab
  ///   左 flex:4  — 视频 + 云台指示
  ///   中 flex:3  — 状态 + 误差图 + 系统健康
  ///   右 flex:4  — 火控 + 威胁队列 + 任务控制
  Widget _wideLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // 左列
        Expanded(
          flex: 4,
          child: Column(
            children: const [
              Expanded(child: VideoFeedWidget()),
              SizedBox(height: 8),
              SizedBox(height: 124, child: GimbalIndicator()),
            ],
          ),
        ),
        const SizedBox(width: 8),
        // 中列
        Expanded(
          flex: 3,
          child: Column(
            children: const [
              Expanded(flex: 1, child: StatusCard()),
              SizedBox(height: 8),
              Expanded(flex: 2, child: ErrorChartWidget()),
              SizedBox(height: 8),
              Expanded(flex: 1, child: SystemHealthWidget()),
            ],
          ),
        ),
        const SizedBox(width: 8),
        // 右列 — 核心火控视图，始终可见
        Expanded(
          flex: 4,
          child: Column(
            children: const [
              SizedBox(height: 196, child: FireControlWidget()),
              SizedBox(height: 8),
              Expanded(child: ThreatQueueWidget()),
              SizedBox(height: 8),
              SizedBox(height: 128, child: MissionControlWidget()),
            ],
          ),
        ),
      ],
    );
  }

  /// 中等屏（720-1100px）：三列，右列带 Tab（威胁/任务）
  Widget _mediumLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // 左列
        Expanded(
          flex: 4,
          child: Column(
            children: const [
              Expanded(child: VideoFeedWidget()),
              SizedBox(height: 8),
              SizedBox(height: 110, child: GimbalIndicator()),
            ],
          ),
        ),
        const SizedBox(width: 8),
        // 中列
        Expanded(
          flex: 3,
          child: Column(
            children: const [
              Expanded(flex: 1, child: StatusCard()),
              SizedBox(height: 8),
              Expanded(flex: 2, child: ErrorChartWidget()),
              SizedBox(height: 8),
              Expanded(flex: 1, child: SystemHealthWidget()),
            ],
          ),
        ),
        const SizedBox(width: 8),
        // 右列 — 火控始终置顶，Tab 切换威胁/任务
        Expanded(
          flex: 4,
          child: _mediumRightColumn(),
        ),
      ],
    );
  }

  Widget _mediumRightColumn() {
    return DefaultTabController(
      length: 2,
      child: Column(
        children: [
          const SizedBox(height: 196, child: FireControlWidget()),
          const SizedBox(height: 4),
          const TabBar(
            labelPadding: EdgeInsets.symmetric(horizontal: 0, vertical: 2),
            tabs: [Tab(text: '威胁队列'), Tab(text: '任务控制')],
          ),
          Expanded(
            child: TabBarView(
              children: const [
                ThreatQueueWidget(),
                MissionControlWidget(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 窄屏（< 720px）：滚动列表，按优先级排序
  Widget _narrowLayout() {
    return ListView(
      children: [
        const SizedBox(height: 240, child: VideoFeedWidget()),
        const SizedBox(height: 8),
        const SizedBox(height: 210, child: FireControlWidget()),
        const SizedBox(height: 8),
        const SizedBox(height: 240, child: ThreatQueueWidget()),
        const SizedBox(height: 8),
        const SizedBox(height: 110, child: StatusCard()),
        const SizedBox(height: 8),
        const SizedBox(height: 180, child: GimbalIndicator()),
        const SizedBox(height: 8),
        const SizedBox(height: 160, child: MissionControlWidget()),
        const SizedBox(height: 8),
        const SizedBox(height: 200, child: ErrorChartWidget()),
        const SizedBox(height: 8),
        const SizedBox(height: 180, child: SystemHealthWidget()),
      ],
    );
  }
}

/// 调参抽屉 — 包含 PID 调参 + 指标 + 预飞检查
class _TuningDrawer extends StatelessWidget {
  const _TuningDrawer();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final screenW = MediaQuery.of(context).size.width;
    final drawerW = (screenW * 0.38).clamp(300.0, 480.0);

    return Drawer(
      width: drawerW,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 标题栏
          Container(
            color: theme.colorScheme.primaryContainer,
            padding: const EdgeInsets.fromLTRB(16, 40, 8, 12),
            child: Row(
              children: [
                Icon(Icons.tune, color: theme.colorScheme.onPrimaryContainer),
                const SizedBox(width: 8),
                Text(
                  '调参 / 预飞检查',
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: theme.colorScheme.onPrimaryContainer,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: Icon(Icons.close,
                      color: theme.colorScheme.onPrimaryContainer),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
          ),
          // 内容区域
          Expanded(
            child: DefaultTabController(
              length: 3,
              child: Column(
                children: [
                  TabBar(
                    labelPadding:
                        const EdgeInsets.symmetric(horizontal: 0, vertical: 4),
                    tabs: const [
                      Tab(text: 'PID'),
                      Tab(text: '指标'),
                      Tab(text: '预飞'),
                    ],
                  ),
                  Expanded(
                    child: TabBarView(
                      children: [
                        // PID 调参
                        const Padding(
                          padding: EdgeInsets.all(8),
                          child: ControlPanel(),
                        ),
                        // 指标
                        const Padding(
                          padding: EdgeInsets.all(8),
                          child: MetricsCard(),
                        ),
                        // 预飞检查
                        Padding(
                          padding: const EdgeInsets.all(8),
                          child: Builder(
                            builder: (ctx) => PreflightWidget(
                              api: ctx.read<TrackingProvider>().api,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
