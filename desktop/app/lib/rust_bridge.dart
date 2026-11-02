import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:isolate';

import 'package:ffi/ffi.dart';
import 'package:path/path.dart' as p;

// C ABI 类型。
typedef _NoArgNative = Pointer<Utf8> Function();
typedef _NoArgDart = Pointer<Utf8> Function();
typedef _OneArgNative = Pointer<Utf8> Function(Pointer<Utf8>);
typedef _OneArgDart = Pointer<Utf8> Function(Pointer<Utf8>);
typedef _TwoArgNative = Pointer<Utf8> Function(Pointer<Utf8>, Pointer<Utf8>);
typedef _TwoArgDart = Pointer<Utf8> Function(Pointer<Utf8>, Pointer<Utf8>);
typedef _HistoryNative = Pointer<Utf8> Function(
  Pointer<Utf8>,
  Pointer<Utf8>,
  Int32,
);
typedef _HistoryDart = Pointer<Utf8> Function(
  Pointer<Utf8>,
  Pointer<Utf8>,
  int,
);
typedef _FreeNative = Void Function(Pointer<Utf8>);
typedef _FreeDart = void Function(Pointer<Utf8>);

/// Rust C ABI 的轻量封装。
///
/// Rust 返回统一 JSON：`{"ok":true,"data":...}` 或
/// `{"ok":false,"error":"..."}`。本类负责 UTF-8 编解码和释放 Rust 字符串。
class RustBridge {
  RustBridge._(this._lib) {
    _free = _lib.lookupFunction<_FreeNative, _FreeDart>('ss_free');
    _init = _lib.lookupFunction<_NoArgNative, _NoArgDart>('ss_init');
    _version = _lib.lookupFunction<_NoArgNative, _NoArgDart>('ss_version');
    _progress = _lib.lookupFunction<_NoArgNative, _NoArgDart>('ss_progress');
    _watchStop = _lib.lookupFunction<_NoArgNative, _NoArgDart>('ss_watch_stop');
    _watchStatus =
        _lib.lookupFunction<_NoArgNative, _NoArgDart>('ss_watch_status');
    _shutdown = _lib.lookupFunction<_NoArgNative, _NoArgDart>('ss_shutdown');

    _mount = _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_mount');
    _unmount = _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_unmount');
    _mountInfo =
        _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_mount_info');
    _plan = _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_plan');
    _watchStart =
        _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_watch_start');
    _restore = _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_restore');
    _remoteStat =
        _lib.lookupFunction<_OneArgNative, _OneArgDart>('ss_remote_stat');
    _sync = _lib.lookupFunction<_TwoArgNative, _TwoArgDart>('ss_sync');
    _history =
        _lib.lookupFunction<_HistoryNative, _HistoryDart>('ss_history');

    _decode(_init());
  }

  static RustBridge? _instance;

  static RustBridge get instance {
    return _instance ??= RustBridge._(_openLibrary());
  }

  late final _FreeDart _free;
  late final _NoArgDart _init;
  late final _NoArgDart _version;
  late final _NoArgDart _progress;
  late final _NoArgDart _watchStop;
  late final _NoArgDart _watchStatus;
  late final _NoArgDart _shutdown;
  late final _OneArgDart _mount;
  late final _OneArgDart _unmount;
  late final _OneArgDart _mountInfo;
  late final _OneArgDart _plan;
  late final _OneArgDart _watchStart;
  late final _OneArgDart _restore;
  late final _OneArgDart _remoteStat;
  late final _TwoArgDart _sync;
  late final _HistoryDart _history;
  final DynamicLibrary _lib;

  static DynamicLibrary _openLibrary() {
    if (Platform.isWindows) {
      final besideExe = p.join(
        p.dirname(Platform.resolvedExecutable),
        'selfshare_core.dll',
      );
      try {
        return DynamicLibrary.open(besideExe);
      } catch (_) {
        // 开发态：flutter run 的 cwd 通常是 desktop/app。
        return DynamicLibrary.open(
          p.normalize(p.join('..', 'core', 'target', 'release', 'selfshare_core.dll')),
        );
      }
    }
    if (Platform.isMacOS) {
      return DynamicLibrary.open('libselfshare_core.dylib');
    }
    if (Platform.isLinux) {
      return DynamicLibrary.open('libselfshare_core.so');
    }
    throw UnsupportedError('SelfShare GUI 暂不支持 ${Platform.operatingSystem}');
  }

  Map<String, dynamic> _decode(Pointer<Utf8> ptr) {
    if (ptr == nullptr) {
      throw StateError('Rust Core 返回空指针');
    }
    try {
      final text = ptr.toDartString();
      final decoded = jsonDecode(text);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Rust Core 返回的不是 JSON 对象');
      }
      return decoded;
    } finally {
      _free(ptr);
    }
  }

  Map<String, dynamic> _callOne(
    Pointer<Utf8> Function(Pointer<Utf8>) fn,
    String value,
  ) {
    final input = value.toNativeUtf8();
    try {
      return _decode(fn(input));
    } finally {
      malloc.free(input);
    }
  }

  dynamic _unwrap(Map<String, dynamic> response) {
    if (response['ok'] == false) {
      throw SelfShareException(response['error']?.toString() ?? '未知错误');
    }
    return response['data'];
  }

  Map<String, dynamic> version() => _decode(_version());

  Future<Map<String, dynamic>> mount({
    required String folder,
    required String url,
    required String vault,
    required String token,
  }) async {
    return Isolate.run(() {
      final bridge = RustBridge._(_openLibrary());
      final response = bridge._callOne(
        bridge._mount,
        jsonEncode({
          'folder': folder,
          'url': url,
          'vault': vault,
          'token': token,
        }),
      );
      return Map<String, dynamic>.from(bridge._unwrap(response));
    });
  }

  Map<String, dynamic> mountInfo(String folder) {
    return Map<String, dynamic>.from(_unwrap(_callOne(_mountInfo, folder)));
  }

  void unmount(String folder) => _unwrap(_callOne(_unmount, folder));

  Future<Map<String, dynamic>> sync(
    String folder, {
    bool dryRun = false,
  }) async {
    // 同步可能持续数秒；在独立 isolate 里重新打开 DLL，避免阻塞 Flutter UI。
    return Isolate.run(() {
      final bridge = RustBridge._(_openLibrary());
      final f = folder.toNativeUtf8();
      final opts = jsonEncode({'dry_run': dryRun}).toNativeUtf8();
      try {
        final response = bridge._decode(bridge._sync(f, opts));
        return Map<String, dynamic>.from(bridge._unwrap(response));
      } finally {
        malloc.free(f);
        malloc.free(opts);
      }
    });
  }

  Future<List<Map<String, dynamic>>> plan(String folder) async {
    final data = _unwrap(_callOne(_plan, folder));
    return (data as List)
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  Map<String, dynamic> progress() => _decode(_progress());

  void watchStart(
    String folder, {
    int intervalSecs = 5,
    int debounceSecs = 2,
  }) {
    _unwrap(_callOne(
      _watchStart,
      jsonEncode({
        'folder': folder,
        'interval_secs': intervalSecs,
        'debounce_secs': debounceSecs,
      }),
    ));
  }

  void watchStop() => _unwrap(_decode(_watchStop()));

  bool watchStatus() => _decode(_watchStatus())['watching'] == true;

  List<Map<String, dynamic>> history(
    String folder, {
    String? path,
    int limit = 100,
  }) {
    final f = folder.toNativeUtf8();
    final q = (path ?? '').toNativeUtf8();
    try {
      final response = _decode(_history(f, q, limit));
      final data = _unwrap(response) as List;
      return data
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    } finally {
      malloc.free(f);
      malloc.free(q);
    }
  }

  Map<String, dynamic> remoteStat(String folder) {
    return Map<String, dynamic>.from(_unwrap(_callOne(_remoteStat, folder)));
  }

  Future<Map<String, dynamic>> restore({
    required String folder,
    required String hash,
    required String path,
    String? output,
    bool overwrite = false,
  }) async {
    final response = _callOne(
      _restore,
      jsonEncode({
        'folder': folder,
        'hash': hash,
        'path': path,
        'output': output ?? '',
        'overwrite': overwrite,
      }),
    );
    return Map<String, dynamic>.from(_unwrap(response));
  }

  void shutdown() => _decode(_shutdown());
}

class SelfShareException implements Exception {
  const SelfShareException(this.message);
  final String message;

  @override
  String toString() => message;
}
