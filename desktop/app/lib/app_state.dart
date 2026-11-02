import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'autostart.dart';
import 'rust_bridge.dart';

class MountView {
  const MountView({
    required this.folder,
    required this.url,
    required this.vault,
    required this.hostId,
    required this.tracked,
    required this.headRev,
    required this.lastSync,
  });

  final String folder;
  final String url;
  final String vault;
  final String hostId;
  final int tracked;
  final int headRev;
  final String lastSync;

  factory MountView.fromJson(Map<String, dynamic> j) => MountView(
        folder: j['folder']?.toString() ?? '',
        url: j['url']?.toString() ?? '',
        vault: j['vault']?.toString() ?? '',
        hostId: j['host_id']?.toString() ?? '',
        tracked: (j['tracked'] as num?)?.toInt() ?? 0,
        headRev: (j['head_rev'] as num?)?.toInt() ?? 0,
        lastSync: j['last_sync']?.toString() ?? '',
      );
}

class AppState extends ChangeNotifier {
  AppState(this.bridge);

  final RustBridge bridge;
  final List<MountView> mounts = [];
  int selectedIndex = -1;
  bool loading = false;
  bool watching = false;
  bool startWithWindows = false;
  String status = '就绪';
  String? error;
  Map<String, dynamic>? progress;
  Map<String, dynamic>? lastReport;
  Map<String, dynamic>? remoteStat;
  List<Map<String, dynamic>> history = [];
  Timer? _timer;

  MountView? get selected =>
      selectedIndex >= 0 && selectedIndex < mounts.length
          ? mounts[selectedIndex]
          : null;

  Future<void> initialise() async {
    final prefs = await SharedPreferences.getInstance();
    startWithWindows = await Autostart.isEnabled();
    final folders = prefs.getStringList('mountFolders') ?? const [];
    for (final folder in folders) {
      try {
        mounts.add(MountView.fromJson(bridge.mountInfo(folder)));
      } catch (_) {
        // 挂载目录已被移动/删除，不阻塞其他项。
      }
    }
    if (mounts.isNotEmpty) {
      selectedIndex = 0;
      await refreshSelected();
      if (prefs.getBool('watchEnabled') ?? true) {
        startWatch();
      }
    }
    _timer = Timer.periodic(const Duration(milliseconds: 750), (_) {
      _pollProgress();
    });
    notifyListeners();
  }

  Future<void> disposeAsync() async {
    _timer?.cancel();
    bridge.shutdown();
  }

  Future<void> _persistMounts() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(
      'mountFolders',
      mounts.map((e) => e.folder).toList(),
    );
  }

  Future<void> addMount({
    required String folder,
    required String url,
    required String vault,
    required String token,
  }) async {
    await _guard(() async {
      await bridge.mount(folder: folder, url: url, vault: vault, token: token);
      final view = MountView.fromJson(bridge.mountInfo(folder));
      mounts.removeWhere((e) => e.folder == view.folder);
      mounts.add(view);
      selectedIndex = mounts.length - 1;
      await _persistMounts();
      await refreshSelected();
      startWatch();
    });
  }

  Future<void> removeSelected() async {
    final mount = selected;
    if (mount == null) return;
    await _guard(() async {
      if (watching) stopWatch();
      bridge.unmount(mount.folder);
      mounts.removeAt(selectedIndex);
      selectedIndex = mounts.isEmpty ? -1 : (selectedIndex - 1).clamp(0, mounts.length - 1);
      await _persistMounts();
      if (selected != null) await refreshSelected();
    });
  }

  Future<void> select(int index) async {
    if (index == selectedIndex || index < 0 || index >= mounts.length) return;
    if (watching) stopWatch();
    selectedIndex = index;
    notifyListeners();
    await refreshSelected();
    startWatch();
  }

  Future<void> syncNow({bool dryRun = false}) async {
    final mount = selected;
    if (mount == null) return;
    await _guard(() async {
      status = dryRun ? '正在预演…' : '正在同步…';
      lastReport = await bridge.sync(mount.folder, dryRun: dryRun);
      status = _summary(lastReport!);
      await refreshSelected(quiet: true);
    });
  }

  Future<void> refreshSelected({bool quiet = false}) async {
    final mount = selected;
    if (mount == null) return;
    if (!quiet) loading = true;
    try {
      final info = MountView.fromJson(bridge.mountInfo(mount.folder));
      mounts[selectedIndex] = info;
      remoteStat = bridge.remoteStat(mount.folder);
      history = bridge.history(mount.folder, limit: 100);
      error = null;
    } catch (e) {
      error = e.toString();
    } finally {
      if (!quiet) loading = false;
      notifyListeners();
    }
  }

  void startWatch() {
    final mount = selected;
    if (mount == null || watching) return;
    try {
      bridge.watchStart(mount.folder);
      watching = true;
      status = '自动同步已开启';
      _setWatchPreference(true);
    } catch (e) {
      error = e.toString();
    }
    notifyListeners();
  }

  void stopWatch() {
    if (!watching) return;
    bridge.watchStop();
    watching = false;
    status = '自动同步已暂停';
    _setWatchPreference(false);
    notifyListeners();
  }

  Future<void> _setWatchPreference(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('watchEnabled', value);
  }

  Future<void> setStartWithWindows(bool value) async {
    try {
      await Autostart.setEnabled(value);
      startWithWindows = value;
      error = null;
    } catch (e) {
      error = e.toString();
      startWithWindows = await Autostart.isEnabled();
    }
    notifyListeners();
  }

  Future<void> restore(Map<String, dynamic> item) async {
    final mount = selected;
    final hash = item['hash']?.toString();
    final path = item['path']?.toString();
    if (mount == null || hash == null || path == null) return;
    await _guard(() async {
      await bridge.restore(
        folder: mount.folder,
        hash: hash,
        path: path,
      );
      status = '已恢复 $path 的历史版本';
      await syncNow();
    });
  }

  void _pollProgress() {
    try {
      progress = bridge.progress();
      final p = progress!;
      final message = p['message']?.toString();
      if (message != null && message.isNotEmpty) status = message;
      final report = p['last_report'];
      if (report is Map) lastReport = Map<String, dynamic>.from(report);
      watching = p['watching'] == true;
      notifyListeners();
    } catch (_) {
      // 应用退出或 Rust Core 尚未加载时忽略轮询错误。
    }
  }

  Future<void> _guard(Future<void> Function() body) async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      await body();
    } catch (e) {
      error = e.toString();
      status = '操作失败';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  String _summary(Map<String, dynamic> r) {
    int count(String key) => (r[key] as List?)?.length ?? 0;
    return '拉取 ${count('pulls')} · 上传 ${count('pushes')} · '
        '删除 ${count('deletes_local') + count('deletes_remote')} · '
        '冲突 ${count('conflicts')}';
  }
}
