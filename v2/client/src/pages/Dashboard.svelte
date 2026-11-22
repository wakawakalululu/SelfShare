<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  export let navigate: (page: string) => void = () => {}

  let mounts: any[] = []
  let loading = true
  let paused = false
  let stat: any = null
  let message = ''
  let timer: any = null

  // O-3：>512 MiB 大文件提示（按挂载名缓存；整体重传语义 + 预期时间估算）
  let largeFiles: any = {}
  let largeScanned: Set<string> = new Set()

  function estimateMinutes(bytes: number) {
    // README §限制：无分块增量，改一次整体重传；按实测基准保守取 ~10 MB/s 估算
    const rate = 10 * 1024 * 1024
    return Math.max(1, Math.round(bytes / rate / 60))
  }

  async function checkLargeFiles(name: string) {
    try {
      const files: any[] = await invoke('list_large_files', { name })
      largeFiles = { ...largeFiles, [name]: files }
    } catch (e) {
      // 扫描失败不打扰主界面，仅记录；下次手动重查
      console.warn(`list_large_files(${name}) failed:`, e)
      largeFiles = { ...largeFiles, [name]: null }
    }
  }

  async function loadMounts() {
    try {
      mounts = await invoke('list_mounts')
      paused = await invoke('is_sync_paused')
      if (mounts.length > 0) {
        try {
          stat = await invoke('get_vault_stat', { mount_name: mounts[0].name })
        } catch {
          stat = null
        }
      } else {
        stat = null
      }
      // 大文件扫描只在每个挂载首次加载时做一次，不跟 5 秒轮询重复执行
      for (const m of mounts) {
        if (!largeScanned.has(m.name)) {
          largeScanned.add(m.name)
          checkLargeFiles(m.name)
        }
      }
    } catch (e) {
      message = '加载失败: ' + e
    } finally {
      loading = false
    }
  }

  async function syncMount(name: string) {
    message = `正在同步 ${name} ...`
    try {
      // D7：sync 失败以 Ok(SyncStatus{state:"error", errors}) 返回（IPC 形状不变），
      // 必须读取返回状态，否则失败也显示「同步完成」。
      const status: any = await invoke('sync_mount', { name })
      if (status && status.state === 'error') {
        const detail = (status.errors || []).join('; ') || '未知错误'
        message = `同步失败: ${name} — ${detail}`
      } else {
        message = `同步完成: ${name}`
      }
      await loadMounts()
    } catch (e) {
      // Err 仅来自挂载查询失败（mount 不存在等），同步失败不走这里。
      message = '同步失败: ' + e
    }
  }

  async function syncAll() {
    message = '正在同步全部文件夹 ...'
    try {
      const res: any[] = await invoke('sync_all_mounts')
      const failed: any[] = res.filter((s: any) => s && s.state === 'error')
      if (failed.length > 0) {
        const detail = failed
          .map((s: any) => `${s.mount_name}: ${(s.errors || []).join('; ') || '未知错误'}`)
          .join(' | ')
        message = `同步完成 ${res.length - failed.length}/${res.length} 个，失败 ${failed.length} 个 — ${detail}`
      } else {
        message = `同步完成全部 ${res.length} 个文件夹`
      }
      await loadMounts()
    } catch (e) {
      message = '同步失败: ' + e
    }
  }

  async function togglePause() {
    try {
      await invoke(paused ? 'resume_sync_all' : 'pause_sync_all')
      message = paused ? '同步已恢复' : '同步已暂停'
      await loadMounts()
    } catch (e) {
      message = '操作失败: ' + e
    }
  }

  function humanBytes(n: number) {
    if (!n) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let i = 0
    let v = n
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
  }

  onMount(() => {
    loadMounts()
    timer = setInterval(loadMounts, 5000)
  })

  onDestroy(() => {
    if (timer) clearInterval(timer)
  })
</script>

<div class="dashboard">
  <div class="header">
    <h2>仪表盘</h2>
    <div class="actions">
      <button on:click={syncAll} disabled={mounts.length === 0}>立即同步全部</button>
      <button class="secondary" on:click={togglePause}>
        {paused ? '恢复同步' : '暂停同步'}
      </button>
      <button class="secondary" on:click={() => navigate('folders')}>管理文件夹</button>
    </div>
  </div>

  {#if paused}
    <div class="banner">同步已暂停，可在托盘菜单或点击「恢复同步」继续</div>
  {/if}
  {#if message}
    <div class="message">{message}</div>
  {/if}

  {#if stat}
    <div class="stats">
      <div class="stat"><span>文件</span><strong>{stat.files}</strong></div>
      <div class="stat"><span>版本</span><strong>{stat.versions}</strong></div>
      <div class="stat"><span>内容块</span><strong>{stat.blobs}</strong></div>
      <div class="stat"><span>占用</span><strong>{humanBytes(stat.blob_bytes)}</strong></div>
      <div class="stat"><span>修订</span><strong>{stat.head_rev}</strong></div>
    </div>
  {/if}

  {#if loading}
    <p>加载中...</p>
  {:else if mounts.length === 0}
    <div class="empty">
      <p>还没有同步文件夹</p>
      <button on:click={() => navigate('folders')}>添加同步文件夹</button>
    </div>
  {:else}
    <div class="mount-grid">
      {#each mounts as mount}
        <div class="mount-card" class:syncing={mount.status === 'syncing'} class:paused={mount.status === 'paused'}>
          <div class="mount-header">
            <h3>{mount.name}</h3>
            <span class="status" class:active={mount.status === 'idle' || mount.status === 'watching'}>
              {mount.status === 'idle' ? '已同步' : mount.status === 'watching' ? '监控中' : mount.status === 'syncing' ? '同步中' : mount.status === 'paused' ? '已暂停' : mount.status}
            </span>
          </div>
          <div class="mount-info">
            <p><strong>本地路径:</strong> {mount.local_path}</p>
            <p><strong>服务器:</strong> {mount.server_url}</p>
            <p><strong>库ID:</strong> {mount.vault_id}</p>
          </div>
          {#if largeFiles[mount.name]?.length}
            <div class="large-hint">
              <strong>大文件提示</strong>（>512 MiB，改动即整体重传）：
              {largeFiles[mount.name].slice(0, 3).map((f) => `${f.path}（${humanBytes(f.size_bytes)}）`).join('、')}
              {largeFiles[mount.name].length > 3 ? ` 等 ${largeFiles[mount.name].length} 个` : ''}
              — 按基准 ~10 MB/s 估算约 {estimateMinutes(largeFiles[mount.name].reduce((s, f) => s + f.size_bytes, 0))} 分钟
            </div>
          {/if}
          <div class="mount-actions">
            <button on:click={() => syncMount(mount.name)}>立即同步</button>
            <button class="secondary" on:click={() => checkLargeFiles(mount.name)}>查大文件</button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dashboard h2 { margin: 0; }
  .header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  .secondary { background: #333; }
  .banner, .message {
    margin-top: 1rem; padding: 0.7rem 1rem; border-radius: 6px;
    background: #3a2a10; color: #ffd79a; font-size: 0.85rem;
  }
  .message { background: #16213e; color: #bbb; }
  .stats { display: flex; gap: 0.75rem; margin: 1.25rem 0; flex-wrap: wrap; }
  .stat {
    background: #16213e; border-radius: 8px; padding: 0.8rem 1.2rem; min-width: 110px;
    display: flex; flex-direction: column; gap: 0.3rem;
  }
  .stat span { font-size: 0.75rem; color: #888; }
  .stat strong { font-size: 1.1rem; }
  .empty { text-align: center; padding: 3rem; background: #16213e; border-radius: 8px; }
  .mount-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 1.5rem; }
  .mount-card { background: #16213e; border-radius: 8px; padding: 1.5rem; border-left: 4px solid #0f3460; }
  .mount-card.syncing { border-left-color: #e94560; }
  .mount-card.paused { border-left-color: #888; opacity: 0.85; }
  .mount-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
  .mount-header h3 { margin: 0; }
  .status { font-size: 0.8rem; padding: 0.25rem 0.75rem; border-radius: 12px; background: #333; }
  .status.active { background: #1a936f; }
  .mount-info p { margin: 0.5rem 0; font-size: 0.85rem; color: #aaa; }
  .mount-info strong { color: #ddd; }
  .large-hint {
    margin-top: 0.75rem;
    padding: 0.6rem 0.75rem;
    border-radius: 6px;
    background: #3a2a10;
    color: #ffd79a;
    font-size: 0.8rem;
  }
  .mount-actions { margin-top: 1rem; display: flex; gap: 0.6rem; flex-wrap: wrap; }
</style>
