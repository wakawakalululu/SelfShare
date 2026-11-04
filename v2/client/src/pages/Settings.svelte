<script lang="ts">
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  // 只暴露真正作用于 SyncEngine 的设置项；其余偏好字段暂未接线，不展示为可用开关。
  let settings: any = {
    default_server_url: 'http://127.0.0.1:8484',
    sync_interval_secs: 10,
    enable_p2p: false,
    auto_start: false,
    theme: 'system',
    show_notifications: true,
  }
  let message = ''
  let saving = false

  onMount(async () => {
    try {
      settings = await invoke('get_settings')
    } catch (e) {
      message = '读取设置失败: ' + e
    }
  })

  async function saveSettings() {
    saving = true
    message = ''
    try {
      settings.sync_interval_secs = Math.min(3600, Math.max(5, Number(settings.sync_interval_secs) || 10))
      await invoke('save_settings', { settings })
      message = '设置已保存到本地配置文件'
    } catch (e) {
      message = '保存失败: ' + e
    } finally {
      saving = false
    }
  }

  async function probe() {
    message = '正在探测 ...'
    try {
      const r: any = await invoke('probe_server', { req: { url: settings.default_server_url } })
      message = `连接正常：${r.service} v${r.version} · ${r.vaults} 个同步库`
    } catch (e) {
      message = '连接失败: ' + e
    }
  }
</script>

<div class="settings">
  <h2>设置</h2>

  <div class="section">
    <h3>服务器</h3>
    <label>
      默认服务器地址（新建同步文件夹时预填）
      <input bind:value={settings.default_server_url} placeholder="http://127.0.0.1:8484" />
    </label>
    <button class="secondary" on:click={probe}>测试连接</button>
  </div>

  <div class="section">
    <h3>同步</h3>
    <label>
      后台巡检间隔（秒，5 - 3600）
      <input type="number" bind:value={settings.sync_interval_secs} min="5" max="3600" />
    </label>
    <label class="checkbox">
      <input type="checkbox" bind:checked={settings.enable_p2p} />
      启用 P2P 直连（内网节点之间传文件，失败自动回退中心服务端）
    </label>
    <p class="hint">以上两项在下次启动「监控」时生效，已运行中的监控需先停止再启动。</p>
  </div>

  <div class="row">
    <button on:click={saveSettings} disabled={saving}>{saving ? '保存中...' : '保存设置'}</button>
    {#if message}<span class="message">{message}</span>{/if}
  </div>
</div>

<style>
  h3 { margin-top: 0; }
  .section { background: #16213e; padding: 1.5rem; border-radius: 8px; margin-bottom: 1rem; }
  label { display: block; margin-bottom: 1rem; font-size: 0.9rem; }
  input { margin-top: 0.25rem; }
  input[type="number"] { max-width: 200px; }
  .checkbox { display: flex; align-items: center; gap: 0.5rem; }
  .checkbox input { margin: 0; }
  .secondary { background: #333; }
  .hint { color: #888; font-size: 0.85rem; }
  .row { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
  .message { font-size: 0.85rem; color: #bbb; }
</style>
