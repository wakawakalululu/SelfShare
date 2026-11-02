import 'dart:io';

/// GUI 进程的 Windows 登录自启。
///
/// 使用计划任务而不是 Startup 文件夹：可设置延迟、忽略重复实例，并在程序移动后
/// 通过重新切换开关自动更新路径。
class Autostart {
  static const taskName = r'\SelfShare\GUI';

  static Future<bool> isEnabled() async {
    if (!Platform.isWindows) return false;
    final r = await Process.run(
      'schtasks.exe',
      ['/Query', '/TN', taskName],
      runInShell: false,
    );
    return r.exitCode == 0;
  }

  static Future<void> setEnabled(bool enabled) async {
    if (!Platform.isWindows) return;
    if (!enabled) {
      final r = await Process.run(
        'schtasks.exe',
        ['/Delete', '/TN', taskName, '/F'],
        runInShell: false,
      );
      // 任务不存在也视为已禁用。
      if (r.exitCode != 0 && !r.stderr.toString().contains('cannot find')) {
        throw StateError('删除开机任务失败：${r.stderr}');
      }
      return;
    }

    final exe = Platform.resolvedExecutable;
    final command = '"$exe" --minimized';
    final r = await Process.run(
      'schtasks.exe',
      [
        '/Create',
        '/TN',
        taskName,
        '/SC',
        'ONLOGON',
        '/DELAY',
        '0000:10',
        '/TR',
        command,
        '/RL',
        'LIMITED',
        '/F',
      ],
      runInShell: false,
    );
    if (r.exitCode != 0) {
      throw StateError('创建开机任务失败：${r.stderr}');
    }
  }
}
