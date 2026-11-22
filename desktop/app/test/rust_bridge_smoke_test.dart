// 桥接层冒烟（roadmap P2「flutter test 冒烟」）：flutter test 在宿主机 VM 直跑
// dart:ffi，不打 GUI 桩。CI（ci.yml gui job）在 flutter test 之前必先
// `cargo build --release`，此时 _openLibrary() 的开发态回退路径
// `../core/target/release/selfshare_core.dll`（相对 desktop/app 的 cwd）恰好命中；
// 本机若无该 DLL，用例会以明确的 DynamicLibrary 异常失败——本层验证口径见
// AGENTS §6（与 test_core_dll.py 的 DLL 冒烟互为两端：Python 侧对产物 DLL、
// Dart 侧对 CI 内核构建）。
//
// 覆盖面 = 桥接层自然业务面，不为 ss_find_mount 硬接业务调用点：
// 裸 JSON 双函数（ss_version / ss_progress / ss_watch_status）、ok_json 包装
// （ss_watch_stop）、C5-3 无匹配白名单（tryFindMount → null / findMount → 异常）、
// 错误通道（ok:false → SelfShareException，不崩）与不可达 probe。
import 'package:flutter_test/flutter_test.dart';
import 'package:selfshare_desktop/rust_bridge.dart';

void main() {
  // ss_version 裸 JSON（不走 ok_json 包装）：version 口径 = 内核发行版本 1.0.0
  // （与 tests/test_core_dll.py::test_version_reports_core_version_and_host_id 同源）。
  test('ss_version 返回裸 JSON：version=1.0.0 且 host_id 非空', () {
    final v = RustBridge.instance.version();
    expect(v, containsPair('version', '1.0.0'));
    expect((v['host_id'] as String).isNotEmpty, isTrue, reason: 'host_id 不应为空');
  });

  // ss_progress 裸 JSON 快照：state 必为字符串字段（与 P2 断言加固的反序列化口径
  // 对齐——形状改动在此显式失败，而不是静默假通过）。
  test('ss_progress 快照：state 为字符串且初始非 syncing', () {
    final snapshot = RustBridge.instance.progress();
    expect(snapshot, isA<Map<String, dynamic>>());
    expect(snapshot['state'], isA<String>());
    expect(snapshot['state'], isNot('syncing'), reason: '未同步时不得停在 syncing');
  });

  test('ss_watch_status 裸 JSON：未启动 watcher 时 watching=false', () {
    expect(RustBridge.instance.watchStatus(), isFalse);
  });

  // ss_watch_stop 走 ok_json 包装：未启动 watcher 时重复 stop 不抛（幂等）。
  test('ss_watch_stop 幂等：未启动 watcher 仍为 ok_json', () {
    RustBridge.instance.watchStop();
  });

  // C5-3：无匹配与真实错误共用 {"ok":false,"error":...}，桥接层用冻结文案白名单
  // 区分——「无匹配」→ tryFindMount 返回 null；findMount 保持可观测抛异常。
  test('ss_find_mount 无匹配：tryFindMount → null，findMount → SelfShareException', () {
    final bridge = RustBridge.instance;
    const missingPath = r'Z:\__ss_smoke_missing__\x.bin';
    expect(bridge.tryFindMount(missingPath), isNull);
    expect(
      () => bridge.findMount(missingPath),
      throwsA(isA<SelfShareException>()),
    );
  });

  // 错误通道：ok:false → SelfShareException（文本透传），不得崩溃或静默吞。
  test('mountInfo 对不存在目录：ok:false → SelfShareException', () {
    expect(
      () => RustBridge.instance.mountInfo(r'Z:\__ss_smoke_missing__'),
      throwsA(isA<SelfShareException>()),
    );
  });

  test('ss_probe 不可达地址：返回 false 不崩溃', () async {
    final ok = await RustBridge.instance.probe('http://127.0.0.1:1/');
    expect(ok, isFalse);
  });

  test('SelfShareException.toString 透传消息', () {
    expect(const SelfShareException('测试错误').toString(), '测试错误');
  });
}
