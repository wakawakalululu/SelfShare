import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'app_state.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.state});
  final AppState state;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int tab = 0;

  AppState get state => widget.state;

  @override
  void initState() {
    super.initState();
    state.addListener(_changed);
  }

  @override
  void dispose() {
    state.removeListener(_changed);
    super.dispose();
  }

  void _changed() => mounted ? setState(() {}) : null;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          const _TitleBar(),
          Expanded(
            child: Row(
              children: [
                _Sidebar(
                  state: state,
                  tab: tab,
                  onTab: (v) => setState(() => tab = v),
                  onAdd: _showAddMount,
                ),
                Expanded(
                  child: switch (tab) {
                    0 => _Overview(state: state, onAdd: _showAddMount),
                    1 => _History(state: state),
                    _ => _Settings(state: state),
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 主入口：输入配对码 + 选目录，两步完成。
  Future<void> _showAddMount() async {
    final folder = TextEditingController();
    final url = TextEditingController(text: 'http://');
    final code = TextEditingController();
    final formKey = GlobalKey<FormState>();
    var busy = false;
    var probing = false;
    String? probeMsg;

    final submit = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogCtx) => StatefulBuilder(
        builder: (dialogCtx, setDialogState) => AlertDialog(
          title: const Row(children: [
            Icon(Icons.link_rounded, size: 20),
            SizedBox(width: 8),
            Text('连接同步文件夹'),
          ]),
          content: SizedBox(
            width: 560,
            child: Form(
              key: formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const _InfoStrip(
                    icon: Icons.lightbulb_outline,
                    text: '在已运行 SelfShare 的电脑上执行 `selfshare vault pair-code <库名>`，'
                        '把打印出的配对码填到下面即可。',
                  ),
                  const SizedBox(height: 16),
                  _FolderField(controller: folder),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: url,
                    readOnly: probing,
                    onChanged: (_) => setDialogState(() => probeMsg = null),
                    decoration: InputDecoration(
                      labelText: '服务端地址',
                      hintText: 'http://192.168.1.10:8484',
                      prefixIcon: const Icon(Icons.dns_outlined),
                      suffixIcon: probing
                          ? const Padding(
                              padding: EdgeInsets.all(12),
                              child: SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              ),
                            )
                          : IconButton(
                              icon: const Icon(Icons.wifi_tethering),
                              tooltip: '测试连接',
                              onPressed: () async {
                                setDialogState(() {
                                  probing = true;
                                  probeMsg = null;
                                });
                                final ok = await state.bridge.probe(url.text.trim());
                                setDialogState(() {
                                  probing = false;
                                  probeMsg = ok ? '连接正常' : '连不上，检查地址与服务端状态';
                                });
                              },
                            ),
                    ),
                    validator: (v) => v == null || v.trim().isEmpty ? '不能为空' : null,
                  ),
                  if (probeMsg != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 6, left: 4),
                      child: Text(
                        probeMsg!,
                        style: TextStyle(
                          fontSize: 12,
                          color: probeMsg == '连接正常'
                              ? const Color(0xFF16A34A)
                              : const Color(0xFFDC2626),
                        ),
                      ),
                    ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: code,
                    style: const TextStyle(
                      fontFamily: 'Consolas',
                      fontSize: 18,
                      letterSpacing: 2,
                    ),
                    decoration: const InputDecoration(
                      labelText: '配对码',
                      hintText: 'SS-XXXX-XXXX-XXXX',
                      prefixIcon: Icon(Icons.vpn_key_outlined),
                    ),
                    validator: (v) => v == null || v.trim().isEmpty ? '不能为空' : null,
                  ),
                  const SizedBox(height: 14),
                  Row(children: [
                    const Icon(Icons.schedule, size: 14, color: Color(0xFF64748B)),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '配对码一次性有效、默认 30 分钟过期；用后作废。',
                        style: TextStyle(fontSize: 11, color: Colors.grey.shade600),
                      ),
                    ),
                  ]),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: busy ? null : () => Navigator.pop(dialogCtx, false),
              child: const Text('取消'),
            ),
            FilledButton.icon(
              onPressed: busy
                  ? null
                  : () async {
                      if (!formKey.currentState!.validate()) return;
                      setDialogState(() => busy = true);
                      final ok = await state.pairMount(
                        folder: folder.text.trim(),
                        url: url.text.trim(),
                        code: code.text.trim(),
                      );
                      if (dialogCtx.mounted) {
                        setDialogState(() => busy = false);
                        if (ok) Navigator.pop(dialogCtx, true);
                      }
                    },
              icon: busy
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.link),
              label: Text(busy ? '正在连接…' : '连接'),
            ),
          ],
        ),
      ),
    );
    if (submit == true && mounted) {
      // 由 AppState.pairMount 负责刷新列表与提示
    }
  }

}

class _TitleBar extends StatelessWidget {
  const _TitleBar();

  @override
  Widget build(BuildContext context) {
    return DragToMoveArea(
      child: Container(
        height: 48,
        padding: const EdgeInsets.only(left: 18),
        decoration: const BoxDecoration(color: Colors.white, border: Border(bottom: BorderSide(color: Color(0xFFE5EAF1)))),
        child: Row(
          children: [
            Container(
              width: 26,
              height: 26,
              decoration: BoxDecoration(color: const Color(0xFF2563EB), borderRadius: BorderRadius.circular(8)),
              child: const Icon(Icons.sync_rounded, size: 17, color: Colors.white),
            ),
            const SizedBox(width: 10),
            const Text('SelfShare', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            const Spacer(),
            _WindowButton(icon: Icons.remove, onTap: () => windowManager.minimize()),
            _WindowButton(
              icon: Icons.crop_square,
              onTap: () async => await windowManager.isMaximized() ? windowManager.unmaximize() : windowManager.maximize(),
            ),
            _WindowButton(icon: Icons.close, danger: true, onTap: () => windowManager.hide()),
          ],
        ),
      ),
    );
  }
}

class _WindowButton extends StatelessWidget {
  const _WindowButton({required this.icon, required this.onTap, this.danger = false});
  final IconData icon;
  final VoidCallback onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        hoverColor: danger ? const Color(0xFFE81123) : const Color(0xFFF0F3F7),
        child: SizedBox(width: 46, height: 48, child: Icon(icon, size: 17)),
      );
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.state, required this.tab, required this.onTab, required this.onAdd});
  final AppState state;
  final int tab;
  final ValueChanged<int> onTab;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 260,
      color: const Color(0xFF0F172A),
      padding: const EdgeInsets.fromLTRB(14, 22, 14, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 10),
            child: Text('同步文件夹', style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12)),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: ListView.builder(
              itemCount: state.mounts.length,
              itemBuilder: (context, i) {
                final m = state.mounts[i];
                final active = i == state.selectedIndex;
                return _MountTile(mount: m, active: active, watching: active && state.watching, onTap: () => state.select(i));
              },
            ),
          ),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              foregroundColor: Colors.white,
              side: const BorderSide(color: Color(0xFF334155)),
              minimumSize: const Size.fromHeight(42),
            ),
            onPressed: onAdd,
            icon: const Icon(Icons.add, size: 18),
            label: const Text('添加同步文件夹'),
          ),
          const SizedBox(height: 16),
          _NavItem(icon: Icons.dashboard_outlined, label: '概览', active: tab == 0, onTap: () => onTab(0)),
          _NavItem(icon: Icons.history, label: '版本历史', active: tab == 1, onTap: () => onTab(1)),
          _NavItem(icon: Icons.settings_outlined, label: '设置', active: tab == 2, onTap: () => onTab(2)),
        ],
      ),
    );
  }
}

class _MountTile extends StatelessWidget {
  const _MountTile({required this.mount, required this.active, required this.watching, required this.onTap});
  final MountView mount;
  final bool active;
  final bool watching;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Material(
          color: active ? const Color(0xFF1E3A5F) : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          child: InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Row(
                children: [
                  const Icon(Icons.folder_rounded, color: Color(0xFF60A5FA)),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(mount.vault, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                        Text(mount.folder, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11)),
                      ],
                    ),
                  ),
                  if (watching) Container(width: 8, height: 8, decoration: const BoxDecoration(color: Color(0xFF22C55E), shape: BoxShape.circle)),
                ],
              ),
            ),
          ),
        ),
      );
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.icon, required this.label, required this.active, required this.onTap});
  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
        color: active ? const Color(0xFF1E293B) : Colors.transparent,
        borderRadius: BorderRadius.circular(9),
        child: ListTile(
          dense: true,
          leading: Icon(icon, size: 20, color: active ? Colors.white : const Color(0xFF94A3B8)),
          title: Text(label, style: TextStyle(color: active ? Colors.white : const Color(0xFFCBD5E1), fontSize: 13)),
          onTap: onTap,
        ),
      );
}

class _Overview extends StatelessWidget {
  const _Overview({required this.state, required this.onAdd});
  final AppState state;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final mount = state.selected;
    if (mount == null) return _Empty(onAdd: onAdd);
    final stats = state.remoteStat ?? const <String, dynamic>{};
    final report = state.lastReport ?? const <String, dynamic>{};
    final p = state.progress ?? const <String, dynamic>{};
    final current = (p['current'] as num?)?.toDouble() ?? 0;
    final total = (p['total'] as num?)?.toDouble() ?? 0;

    return Padding(
      padding: const EdgeInsets.all(26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(mount.vault, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 3),
                    Text(mount.folder, style: const TextStyle(color: Color(0xFF64748B))),
                  ],
                ),
              ),
              OutlinedButton.icon(onPressed: () => state.syncNow(dryRun: true), icon: const Icon(Icons.preview_outlined), label: const Text('预演')),
              const SizedBox(width: 10),
              FilledButton.icon(onPressed: state.loading ? null : state.syncNow, icon: const Icon(Icons.sync), label: const Text('立即同步')),
            ],
          ),
          const SizedBox(height: 24),
          if (state.error != null)
            _ErrorStrip(text: state.error!)
          else
            _StatusCard(state: state, current: current, total: total),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(child: _Metric(icon: Icons.insert_drive_file_outlined, label: '远端文件', value: '${stats['files'] ?? 0}')),
              const SizedBox(width: 12),
              Expanded(child: _Metric(icon: Icons.cloud_outlined, label: '逻辑容量', value: _bytes((stats['bytes'] as num?)?.toInt() ?? 0))),
              const SizedBox(width: 12),
              Expanded(child: _Metric(icon: Icons.history, label: '版本记录', value: '${stats['versions'] ?? 0}')),
              const SizedBox(width: 12),
              Expanded(child: _Metric(icon: Icons.tag, label: '当前修订', value: '${stats['head_rev'] ?? mount.headRev}')),
            ],
          ),
          const SizedBox(height: 18),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  flex: 3,
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('最近一次同步', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                          const SizedBox(height: 18),
                          _ReportRow(label: '拉取', icon: Icons.arrow_downward, color: const Color(0xFF3B82F6), items: report['pulls']),
                          _ReportRow(label: '上传', icon: Icons.arrow_upward, color: const Color(0xFF22C55E), items: report['pushes']),
                          _ReportRow(
                            label: '删除',
                            icon: Icons.delete_outline,
                            color: const Color(0xFF64748B),
                            items: [
                              ...?report['deletes_local'] as List?,
                              ...?report['deletes_remote'] as List?,
                            ],
                          ),
                          _ReportRow(label: '冲突', icon: Icons.call_split, color: const Color(0xFFF59E0B), items: report['conflicts']),
                          const Spacer(),
                          Text(
                            mount.lastSync.isEmpty ? '尚未同步' : '上次同步：${mount.lastSync}',
                            style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 18),
                Expanded(
                  flex: 2,
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('同步设置', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                          const SizedBox(height: 10),
                          SwitchListTile.adaptive(
                            contentPadding: EdgeInsets.zero,
                            value: state.watching,
                            title: const Text('自动同步', style: TextStyle(fontSize: 14)),
                            subtitle: const Text('监视本地变更并定期拉取远端', style: TextStyle(fontSize: 11)),
                            onChanged: (v) => v ? state.startWatch() : state.stopWatch(),
                          ),
                          const Divider(),
                          _Detail(label: '服务端', value: mount.url),
                          _Detail(label: '同步库', value: mount.vault),
                          _Detail(label: '本机标识', value: mount.hostId),
                          _Detail(label: '已跟踪', value: '${mount.tracked} 项'),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.state, required this.current, required this.total});
  final AppState state;
  final double current;
  final double total;

  @override
  Widget build(BuildContext context) {
    final busy = state.loading || (state.progress?['state'] == 'syncing');
    final progress = total > 0 ? (current / total).clamp(0.0, 1.0) : null;
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: busy ? const Color(0xFFDBEAFE) : const Color(0xFFDCFCE7),
                shape: BoxShape.circle,
              ),
              child: busy
                  ? const Padding(padding: EdgeInsets.all(10), child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.check, color: Color(0xFF16A34A)),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(state.status, style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (busy) ...[
                    const SizedBox(height: 8),
                    LinearProgressIndicator(value: progress),
                  ] else
                    const Text('所有文件均已同步', style: TextStyle(color: Color(0xFF64748B), fontSize: 12)),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: state.watching ? const Color(0xFFDCFCE7) : const Color(0xFFF1F5F9),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(state.watching ? '● 自动同步' : '暂停', style: TextStyle(color: state.watching ? const Color(0xFF15803D) : const Color(0xFF64748B), fontSize: 12)),
            ),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.icon, required this.label, required this.value});
  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Icon(icon, color: const Color(0xFF3B82F6), size: 22),
              const SizedBox(width: 12),
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(value, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
                Text(label, style: const TextStyle(color: Color(0xFF64748B), fontSize: 11)),
              ]),
            ],
          ),
        ),
      );
}

class _ReportRow extends StatelessWidget {
  const _ReportRow({required this.label, required this.icon, required this.color, required this.items});
  final String label;
  final IconData icon;
  final Color color;
  final dynamic items;

  @override
  Widget build(BuildContext context) {
    final count = items is List ? (items as List).length : 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 13),
      child: Row(children: [
        Container(width: 30, height: 30, decoration: BoxDecoration(color: color.withValues(alpha: .12), borderRadius: BorderRadius.circular(8)), child: Icon(icon, color: color, size: 16)),
        const SizedBox(width: 10),
        Expanded(child: Text(label, style: const TextStyle(fontSize: 13))),
        Text('$count', style: const TextStyle(fontWeight: FontWeight.w700)),
      ]),
    );
  }
}

class _Detail extends StatelessWidget {
  const _Detail({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 70, child: Text(label, style: const TextStyle(color: Color(0xFF64748B), fontSize: 12))),
          Expanded(child: Text(value, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12))),
        ]),
      );
}

class _History extends StatelessWidget {
  const _History({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final mount = state.selected;
    return Padding(
      padding: const EdgeInsets.all(26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('版本历史', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 3),
              const Text('服务端保留每次上传和删除记录，可一键恢复旧版本。', style: TextStyle(color: Color(0xFF64748B))),
            ])),
            IconButton(onPressed: mount == null ? null : state.refreshSelected, icon: const Icon(Icons.refresh), tooltip: '刷新'),
          ]),
          const SizedBox(height: 22),
          Expanded(
            child: Card(
              child: mount == null
                  ? const Center(child: Text('请先添加同步文件夹'))
                  : state.history.isEmpty
                      ? const Center(child: Text('暂无版本记录'))
                      : ListView.separated(
                          padding: const EdgeInsets.all(10),
                          itemCount: state.history.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, i) {
                            final item = state.history[i];
                            final deleted = item['action'] == 'del';
                            return ListTile(
                              leading: CircleAvatar(
                                backgroundColor: deleted ? const Color(0xFFFEE2E2) : const Color(0xFFDBEAFE),
                                child: Icon(deleted ? Icons.delete_outline : Icons.description_outlined, color: deleted ? const Color(0xFFDC2626) : const Color(0xFF2563EB), size: 19),
                              ),
                              title: Text(item['path']?.toString() ?? '-', maxLines: 1, overflow: TextOverflow.ellipsis),
                              subtitle: Text('${item['time'] ?? '-'} · 修订 ${item['rev'] ?? '-'} · ${item['origin'] ?? '-'}', style: const TextStyle(fontSize: 11)),
                              trailing: deleted || item['hash'] == null
                                  ? const Text('已删除', style: TextStyle(color: Color(0xFFDC2626), fontSize: 12))
                                  : TextButton.icon(onPressed: () => _confirmRestore(context, item), icon: const Icon(Icons.restore, size: 17), label: const Text('恢复')),
                            );
                          },
                        ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmRestore(BuildContext context, Map<String, dynamic> item) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('恢复历史版本'),
        content: Text('恢复 ${item['path']} 在 ${item['time']} 的版本？\n\n当前文件不会被覆盖，系统会先生成带“恢复”标记的副本。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('恢复')),
        ],
      ),
    );
    if (yes == true) await state.restore(item);
  }
}

class _Settings extends StatelessWidget {
  const _Settings({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('设置', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 22),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('应用', style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  value: state.startWithWindows,
                  title: const Text('登录 Windows 时启动'),
                  subtitle: const Text('通过计划任务启动 GUI 并最小化到系统托盘'),
                  onChanged: state.setStartWithWindows,
                ),
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  value: state.watching,
                  title: const Text('自动同步当前文件夹'),
                  subtitle: const Text('本地变更静默 2 秒后同步；每 120 秒巡检远端'),
                  onChanged: (v) => v ? state.startWatch() : state.stopWatch(),
                ),
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  value: state.p2pEnabled,
                  title: const Text('P2P 直连传输'),
                  subtitle: const Text('中心服务器只做认证与发现，文件优先在主机之间直传'),
                  onChanged: state.setP2P,
                ),
              ]),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('当前同步文件夹', style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                if (state.selected != null) ...[
                  _Detail(label: '本地目录', value: state.selected!.folder),
                  _Detail(label: '服务端', value: state.selected!.url),
                  _Detail(label: '同步库', value: state.selected!.vault),
                  const SizedBox(height: 14),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(foregroundColor: const Color(0xFFDC2626)),
                    onPressed: () => _confirmRemove(context),
                    icon: const Icon(Icons.link_off),
                    label: const Text('解除挂载（保留本地文件）'),
                  ),
                ] else
                  const Text('尚未添加同步文件夹'),
              ]),
            ),
          ),
          const Spacer(),
          const _InfoStrip(icon: Icons.info_outline, text: 'GUI 使用 Rust 同步内核；服务端仍可与 Python CLI 客户端混用。'),
        ],
      ),
    );
  }

  Future<void> _confirmRemove(BuildContext context) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('解除挂载'),
        content: const Text('只会删除 .selfshare 配置和本地状态库；同步文件本身不会删除。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('解除挂载')),
        ],
      ),
    );
    if (yes == true) await state.removeSelected();
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.onAdd});
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) => Center(
        child: SizedBox(
          width: 430,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 88, height: 88, decoration: const BoxDecoration(color: Color(0xFFDBEAFE), shape: BoxShape.circle), child: const Icon(Icons.cloud_sync_outlined, size: 43, color: Color(0xFF2563EB))),
            const SizedBox(height: 22),
            Text('把一个文件夹挂到同步库', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            const Text('多台主机连接同一个同步库，即可像坚果云一样双向同步；发生冲突时保留双方内容。', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF64748B), height: 1.6)),
            const SizedBox(height: 22),
            FilledButton.icon(onPressed: onAdd, icon: const Icon(Icons.add), label: const Text('添加同步文件夹')),
          ]),
        ),
      );
}

class _FolderField extends StatelessWidget {
  const _FolderField({required this.controller});
  final TextEditingController controller;

  @override
  Widget build(BuildContext context) => TextFormField(
        controller: controller,
        decoration: InputDecoration(
          labelText: '本地文件夹',
          hintText: r'D:\同步盘',
          prefixIcon: const Icon(Icons.folder_outlined),
          suffixIcon: IconButton(
            icon: const Icon(Icons.more_horiz),
            onPressed: () async {
              final path = await FilePicker.platform.getDirectoryPath(dialogTitle: '选择同步文件夹');
              if (path != null) controller.text = path;
            },
          ),
        ),
        validator: (v) => v == null || v.trim().isEmpty ? '请选择文件夹' : null,
      );
}

class _InfoStrip extends StatelessWidget {
  const _InfoStrip({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: const Color(0xFFEFF6FF), borderRadius: BorderRadius.circular(10)),
        child: Row(children: [Icon(icon, size: 18, color: const Color(0xFF2563EB)), const SizedBox(width: 10), Expanded(child: Text(text, style: const TextStyle(color: Color(0xFF1E40AF), fontSize: 12))),]),
      );
}

class _ErrorStrip extends StatelessWidget {
  const _ErrorStrip({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: const Color(0xFFFEF2F2), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFFECACA))),
        child: Row(children: [const Icon(Icons.error_outline, color: Color(0xFFDC2626)), const SizedBox(width: 10), Expanded(child: Text(text, style: const TextStyle(color: Color(0xFF991B1B)))),]),
      );
}

String _bytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  if (bytes < 1024 * 1024 * 1024) return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
}
