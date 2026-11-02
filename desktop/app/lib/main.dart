import 'dart:io';

import 'package:flutter/material.dart';
import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';

import 'app_state.dart';
import 'home_page.dart';
import 'rust_bridge.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  await windowManager.setPreventClose(true);

  const options = WindowOptions(
    size: Size(1180, 760),
    minimumSize: Size(960, 640),
    center: true,
    title: 'SelfShare',
    titleBarStyle: TitleBarStyle.hidden,
  );
  final minimized = args.contains('--minimized');
  await windowManager.waitUntilReadyToShow(options, () async {
    if (minimized) {
      await windowManager.hide();
    } else {
      await windowManager.show();
      await windowManager.focus();
    }
  });

  final state = AppState(RustBridge.instance);
  await state.initialise();
  runApp(SelfShareApp(state: state));
}

class SelfShareApp extends StatefulWidget {
  const SelfShareApp({super.key, required this.state});
  final AppState state;

  @override
  State<SelfShareApp> createState() => _SelfShareAppState();
}

class _SelfShareAppState extends State<SelfShareApp>
    with WindowListener, TrayListener {
  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    trayManager.addListener(this);
    _configureTray();
  }

  Future<void> _configureTray() async {
    // 资产缺失时不阻塞主界面；打包脚本会替换成正式图标。
    final icon = Platform.isWindows ? 'assets/app_icon.ico' : 'assets/app_icon.png';
    try {
      await trayManager.setIcon(icon);
    } catch (_) {}
    await trayManager.setToolTip('SelfShare 文件同步');
    await trayManager.setContextMenu(Menu(items: [
      MenuItem(key: 'show', label: '打开 SelfShare'),
      MenuItem(key: 'sync', label: '立即同步'),
      MenuItem.separator(),
      MenuItem(key: 'quit', label: '退出'),
    ]));
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    trayManager.removeListener(this);
    widget.state.disposeAsync();
    super.dispose();
  }

  @override
  Future<void> onWindowClose() async {
    // 关闭按钮只隐藏到托盘，watch 继续工作。
    await windowManager.hide();
  }

  @override
  Future<void> onTrayIconMouseDown() async {
    await windowManager.show();
    await windowManager.focus();
  }

  @override
  Future<void> onTrayMenuItemClick(MenuItem item) async {
    switch (item.key) {
      case 'show':
        await windowManager.show();
        await windowManager.focus();
        break;
      case 'sync':
        await widget.state.syncNow();
        break;
      case 'quit':
        await widget.state.disposeAsync();
        await trayManager.destroy();
        exit(0);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF2563EB),
      brightness: Brightness.light,
      surface: const Color(0xFFF8FAFC),
    );
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'SelfShare',
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: scheme,
        scaffoldBackgroundColor: const Color(0xFFF4F7FB),
        fontFamily: Platform.isWindows ? 'Microsoft YaHei UI' : null,
        cardTheme: const CardThemeData(
          elevation: 0,
          color: Colors.white,
          margin: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(16)),
            side: BorderSide(color: Color(0xFFE5EAF1)),
          ),
        ),
        inputDecorationTheme: const InputDecorationTheme(
          filled: true,
          fillColor: Color(0xFFF8FAFC),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.all(Radius.circular(10)),
            borderSide: BorderSide(color: Color(0xFFDDE3EC)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.all(Radius.circular(10)),
            borderSide: BorderSide(color: Color(0xFFDDE3EC)),
          ),
        ),
      ),
      home: HomePage(state: widget.state),
    );
  }
}
