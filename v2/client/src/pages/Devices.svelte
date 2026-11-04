<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  export let navigate: (page: string) => void = () => {}

  let pairUrl = ''
  let pairCode = ''
  let pairResult: any = null
  let pairError = ''
  let pairing = false
  let probeResult = ''
  let mounts: any[] = []
  let selectedMount = ''
  let peers: any[] = []
  let peerError = ''
  let timer: any = null

  async function loadMounts() {
    try {
      mounts = await invoke('list_mounts')
      if (!selectedMount && mounts.length > 0) selectedMount = mounts[0].name
      if (selectedMount && !pairUrl) pairUrl = mounts[0].server_url
    } catch (e) {
      console.warn('list_mounts failed:', e)
    }
  }

  async function loadPeers() {
    if (!selectedMount) { peers = []; return }
    try {
      peers = await invoke('list_peers', { mount_name: selectedMount })
      peerError = ''
    } catch (e) {
      peerError = String(e)
      peers = []
    }
  }

  async function probe() {
    probeResult = '正在探测 ...'
    try {
      const r: any = await invoke('probe_server', { req: { url: pairUrl } })
      probeResult = `${r.service} v${r.version} · ${r.vaults} 个同步库`
    } catch (e) {
      probeResult = '连接失败: ' + e
    }
  }

  async function doPair() {
    pairError = ''
    pairResult = null
    pairing = true
    try {
      pairResult = await invoke('pair_with_code', { req: { url: pairUrl, code: pairCode } })
      await loadMounts()
    } catch (e: any) {
      pairError = e.toString()
    } finally {
      pairing = false
    }
  }

  async function copyToken() {
    if (!pairResult?.token) return
    try {
      await navigator.clipboard.writeText(pairResult.token)
      probeResult = '令牌已复制'
    } catch (e) {
      probeResult = '复制失败: ' + e
    }
  }

  onMount(async () => {
    await loadMounts()
    await loadPeers()
    timer = setInterval(loadPeers, 10000)
  })

  onDestroy(() => { if (timer) clearInterval(timer) })
</script>

<div class="devices">
  <h2>设备管理</h2>

  <div class="pair-section">
    <h3>配对新设备</h3>
    <p class="hint">在 Go 服务端或 Docker 容器启动时获取配对码，填入下方完成连接</p>

    <form on:submit|preventDefault={doPair}>
      <label>
        服务器地址
        <input bind:value={pairUrl} placeholder="http://192.168.1.100:8484" required />
      </label>
      <label>
        配对码
        <input bind:value={pairCode} placeholder="SS-XXXX-XXXX-XXXX" required />
      </label>
      <div class="row">
        <button type="submit" disabled={pairing}>
          {pairing ? '配对中...' : '配对'}
        </button>
        <button type="button" class="secondary" on:click={probe}>测试连接</button>
      </div>
    </form>

    {#if probeResult}<p class="hint">{probeResult}</p>{/if}
    {#if pairError}<div class="error">{pairError}</div>{/if}

    {#if pairResult}
      <div class="success">
        <p>配对成功！</p>
        <p><strong>库ID:</strong> {pairResult.vault}</p>
        <p><strong>令牌:</strong> <code>{pairResult.token}</code></p>
        <div class="row">
          <button class="secondary" on:click={copyToken}>复制令牌</button>
          <button on:click={() => navigate('folders')}>添加同步文件夹</button>
        </div>
      </div>
    {/if}
  </div>

  <div class="peer-section">
    <h3>在线节点（P2P）</h3>
    <div class="row">
      <select bind:value={selectedMount} on:change={loadPeers}>
        <option value="">选择同步文件夹</option>
        {#each mounts as mount}
          <option value={mount.name}>{mount.name}</option>
        {/each}
      </select>
      <button class="secondary" on:click={loadPeers}>刷新</button>
    </div>
    {#if peerError}<div class="error">{peerError}</div>{/if}
    {#if peers.length === 0}
      <p class="hint">当前没有在线节点。开启设置中的 P2P 后，节点会在同步时注册到中心服务端。</p>
    {:else}
      <table>
        <thead><tr><th>节点</th><th>地址</th><th>主机</th><th>内容块</th></tr></thead>
        <tbody>
          {#each peers as peer}
            <tr>
              <td><code>{peer.peer_id}</code></td>
              <td>{peer.listen}</td>
              <td>{peer.host_id}</td>
              <td>{peer.blob_count}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<style>
  .pair-section, .peer-section {
    background: #16213e; padding: 1.5rem; border-radius: 8px;
    max-width: 640px; margin-bottom: 1.5rem;
  }
  h3 { margin-top: 0; }
  .hint { color: #888; font-size: 0.85rem; }
  label { display: block; margin-bottom: 1rem; }
  input, select { width: 100%; margin-top: 0.25rem; }
  .row { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; }
  .secondary { background: #333; }
  .error { margin-top: 1rem; padding: 0.75rem; background: #8b0000; border-radius: 4px; }
  .success { margin-top: 1rem; padding: 1rem; background: #1a4a3a; border-radius: 6px; border-left: 4px solid #1a936f; }
  .success code { background: #1a1a2e; padding: 0.2rem 0.4rem; border-radius: 3px; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.85rem; }
  th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #333; }
  th { color: #888; }
</style>
