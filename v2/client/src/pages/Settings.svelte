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

  // O-2：设置页首次进入一次性提示（裁决保持 P2P 默认关闭 + 一次性提示）。
  // localStorage 标记保证只在首次进入时展示，之后不再打扰。
  const FIRST_VISIT_FLAG = 'ss_settings_first_visit_hint_shown'
  let showFirstVisitHint = false

  function dismissFirstVisitHint() {
    showFirstVisitHint = false
  }

  onMount(async () => {
    try {
      settings = await invoke('get_settings')
    } catch (e) {
      message = '读取设置失败: ' + e
    }
    try {
      if (!localStorage.getItem(FIRST_VISIT_FLAG)) {
        showFirstVisitHint = true
        localStorage.setItem(FIRST_VISIT_FLAG, '1')
      }
    } catch {
      // localStorage 不可用时静默跳过一次性提示，不影响设置功能
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

  {#if showFirstVisitHint}
    <div class="first-hint">
      <strong>首次使用提示（仅显示一次）</strong>
      <ul>
        <li>「P2P 直连」默认关闭、需在此手动开启；仅限局域网节点之间直传，失败自动回退中心服务端。</li>
        <li>单文件上限 2 GiB；超过 512 MiB 的大文件同步按「改一次整体重传」处理，仪表盘会给出耗时估算。</li>
        <li>后台巡检间隔保存后，下次启动「监控」时生效；运行中的监控需先停止再启动。</li>
      </ul>
      <button class="secondary" on:click={dismissFirstVisitHint}>知道了</button>
    </div>
  {/if}

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
  .first-hint {
    background: #1d2a4a;
    border: 1px solid #0f3460;
    padding: 1rem 1.25rem;
    border-radius: 8px;
    margin-bottom: 1rem;
    font-size: 0.88rem;
  }
  .first-hint ul { margin: 0.5rem 0 0.75rem; padding-left: 1.25rem; color: #bbb; }
  .first-hint li { margin-bottom: 0.35rem; }
  .row { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
  .message { font-size: 0.85rem; color: #bbb; }
</style>
