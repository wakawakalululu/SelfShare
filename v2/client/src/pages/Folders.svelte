<script lang="ts">
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  let mounts: any[] = []
  let showAddDialog = false
  let defaultServerUrl = ''
  let newMount = { name: '', local_path: '', server_url: '', vault_id: '', token: '' }

  onMount(async () => {
    await loadMounts()
    try {
      const s: any = await invoke('get_settings')
      defaultServerUrl = s?.default_server_url || ''
      newMount = { ...newMount, server_url: defaultServerUrl }
    } catch (e) {
      console.warn('get_settings failed:', e)
    }
  })

  async function loadMounts() {
    try {
      mounts = await invoke('list_mounts')
    } catch (e) {
      console.error('failed to load mounts:', e)
    }
  }

  async function addMount() {
    try {
      await invoke('add_mount', { req: newMount })
      showAddDialog = false
      newMount = { name: '', local_path: '', server_url: defaultServerUrl, vault_id: '', token: '' }
      await loadMounts()
    } catch (e) {
      alert('添加失败: ' + e)
    }
  }

  async function removeMount(name: string) {
    if (!confirm('确定要移除同步文件夹 "' + name + '" 吗?')) return
    try {
      await invoke('remove_mount', { name })
      await loadMounts()
    } catch (e) {
      alert('移除失败: ' + e)
    }
  }

  async function startWatch(name: string) {
    try {
      await invoke('start_watching', { name })
      await loadMounts()
    } catch (e) {
      alert('启动监控失败: ' + e)
    }
  }

  async function stopWatch(name: string) {
    try {
      await invoke('stop_watching', { name })
      await loadMounts()
    } catch (e) {
      alert('停止监控失败: ' + e)
    }
  }
</script>

<div class="folders">
  <div class="header">
    <h2>同步文件夹</h2>
    <button class="add-btn" on:click={() => showAddDialog = true}>+ 添加</button>
  </div>

  {#if showAddDialog}
    <div class="dialog-overlay" role="presentation" on:click|self={() => showAddDialog = false}>
      <div class="dialog">
        <h3>添加同步文件夹</h3>
        <form on:submit|preventDefault={addMount}>
          <label>
            名称
            <input bind:value={newMount.name} placeholder="我的工作文件夹" required />
          </label>
          <label>
            本地路径
            <input bind:value={newMount.local_path} placeholder="D:\Sync\work" required />
          </label>
          <label>
            服务器地址
            <input bind:value={newMount.server_url} placeholder="http://192.168.1.100:8484" required />
          </label>
          <label>
            库ID
            <input bind:value={newMount.vault_id} placeholder="default" required />
          </label>
          <label>
            令牌
            <input bind:value={newMount.token} type="password" placeholder="通过配对码获取" required />
          </label>
          <div class="dialog-actions">
            <button type="button" on:click={() => showAddDialog = false}>取消</button>
            <button type="submit">添加</button>
          </div>
        </form>
      </div>
    </div>
  {/if}

  <table>
    <thead>
      <tr>
        <th>名称</th>
        <th>本地路径</th>
        <th>服务器</th>
        <th>状态</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody>
      {#each mounts as mount}
        <tr>
          <td>{mount.name}</td>
          <td><code>{mount.local_path}</code></td>
          <td>{mount.server_url}</td>
          <td>
            <span class="badge" class:active={mount.status === 'idle' || mount.status === 'watching'}>
              {mount.status}
            </span>
          </td>
          <td class="actions">
            {#if mount.status === 'watching'}
              <button on:click={() => stopWatch(mount.name)}>停止监控</button>
            {:else}
              <button on:click={() => startWatch(mount.name)}>开始监控</button>
            {/if}
            <button class="danger" on:click={() => removeMount(mount.name)}>移除</button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .add-btn {
    padding: 0.5rem 1rem;
    background: #0f3460;
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
  }

  .dialog-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }

  .dialog {
    background: #16213e;
    padding: 2rem;
    border-radius: 8px;
    min-width: 400px;
  }

  .dialog h3 {
    margin-top: 0;
  }

  .dialog label {
    display: block;
    margin-bottom: 1rem;
    font-size: 0.9rem;
  }

  .dialog input {
    width: 100%;
    padding: 0.5rem;
    margin-top: 0.25rem;
    background: #1a1a2e;
    border: 1px solid #333;
    border-radius: 4px;
    color: #fff;
    box-sizing: border-box;
  }

  .dialog-actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    margin-top: 1.5rem;
  }

  .dialog-actions button {
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }

  .dialog-actions button[type="submit"] {
    background: #0f3460;
    color: #fff;
  }

  .dialog-actions button[type="button"] {
    background: #333;
    color: #aaa;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
  }

  th, td {
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid #333;
  }

  th {
    background: #16213e;
    font-weight: 600;
  }

  .badge {
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    border-radius: 10px;
    background: #333;
  }

  .badge.active {
    background: #1a936f;
  }

  .actions button {
    padding: 0.3rem 0.6rem;
    margin-right: 0.5rem;
    background: #0f3460;
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.8rem;
  }

  .actions .danger {
    background: #8b0000;
  }

  code {
    background: #1a1a2e;
    padding: 0.2rem 0.4rem;
    border-radius: 3px;
    font-size: 0.85rem;
  }
</style>
