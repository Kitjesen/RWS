import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/api_client.dart';
import 'services/event_stream.dart';
import 'services/tracking_provider.dart';
import 'screens/dashboard_screen.dart';
import 'screens/replay_screen.dart';
import 'screens/safety_screen.dart';

void main() {
  const backendUrl = 'http://localhost:5000';
  final api = RwsApiClient(baseUrl: backendUrl);
  final eventStream = EventStreamService(baseUrl: backendUrl)..connect();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => TrackingProvider(api: api)..startPolling(),
        ),
        ChangeNotifierProvider.value(value: eventStream),
      ],
      child: const RwsApp(),
    ),
  );
}

class RwsApp extends StatelessWidget {
  const RwsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RWS Dashboard',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1B5E20),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const RwsHome(),
    );
  }
}

class RwsHome extends StatefulWidget {
  const RwsHome({super.key});

  @override
  State<RwsHome> createState() => _RwsHomeState();
}

class _RwsHomeState extends State<RwsHome> {
  int _selectedIndex = 0;

  static const List<Widget> _screens = [
    DashboardScreen(),
    ReplayScreen(),
    SafetyScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _selectedIndex,
        children: _screens,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) {
          setState(() => _selectedIndex = index);
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard),
            label: 'Dashboard',
          ),
          NavigationDestination(
            icon: Icon(Icons.history_outlined),
            selectedIcon: Icon(Icons.history),
            label: 'Replay',
          ),
          NavigationDestination(
            icon: Icon(Icons.security_outlined),
            selectedIcon: Icon(Icons.security),
            label: 'Safety',
          ),
        ],
      ),
    );
  }
}
