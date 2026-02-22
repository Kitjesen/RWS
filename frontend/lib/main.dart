import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/api_client.dart';
import 'services/event_stream.dart';
import 'services/tracking_provider.dart';
import 'screens/dashboard_screen.dart';

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
      home: const DashboardScreen(),
    );
  }
}
