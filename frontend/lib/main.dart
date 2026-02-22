import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/api_client.dart';
import 'services/tracking_provider.dart';
import 'screens/dashboard_screen.dart';

void main() {
  final api = RwsApiClient(baseUrl: 'http://localhost:5000');

  runApp(
    ChangeNotifierProvider(
      create: (_) => TrackingProvider(api: api)..startPolling(),
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
      home: const DashboardScreen(),
    );
  }
}
