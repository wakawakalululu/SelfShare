<script lang="ts">
  import { invoke } from '@tauri-apps/api/core'

  let mountName = ''
  let filterPath = ''
  let entries: any[] = []
  let loading = false

  async function loadHistory() {
    if (!mountName) return
    loading = true
    try {
      entries = await invoke('get_history', {
        req: { mount_name: mountName, path: filterPath || null, limit: 100 }
      })
    } catch (e) {
      console.error('failed to load history:', e)
      entries = []
    } finally {
      loading = false
    }
  }

  async function restoreVersion(entry: any) {
    if (!confirm(`确定要恢复 "${entry.path}" 到版本 ${entry.rev} 吗?`)) return
    try {
      await invoke('restore_version', {
        req: { mount_name: mountName, path: entry.path, rev: entry.rev }
      })
      alert('恢复成功')
    } catch (e) {
      alert('恢复失败: ' + e)
    }
  }
</script>

<div class="history">
  <h2>版本历史</h2>

  <div class="controls">
    <input bind:value={mountName} placeholder="同步文件夹名称" />
    <input bind:value={filterPath} placeholder="文件路径 (可选)" />
    <button on:click={loadHistory} disabled={loading || !mountName}>
      {loading ? '加载中...' : '查询'}
    </button>
  </div>

  {#if entries.length > 0}
    <table>
      <thead>
        <tr>
          <th>文件路径</th>
          <th>版本</th>
          <th>操作</th>
          <th>来源</th>
          <th>时间</th>
          <th>大小</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        {#each entries as entry}
          <tr>
            <td><code>{entry.path}</code></td>
            <td>{entry.rev}</td>
            <td>
              <span class="action-badge" class:put={entry.action === 'put'} class:del={entry.action === 'del'}>
                {entry.action === 'put' ? '更新' : '删除'}
              </span>
            </td>
            <td>{entry.origin}</td>
            <td>{entry.time}</td>
            <td>{entry.size ? (entry.size / 1024).toFixed(1) + ' KB' : '-'}</td>
            <td>
              {#if entry.action === 'put'}
                <button class="restore-btn" on:click={() => restoreVersion(entry)}>恢复</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else if mountName && !loading}
    <p class="empty">没有找到版本记录</p>
  {/if}
</div>

<style>
  .controls {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }

  .controls input {
    padding: 0.5rem;
    background: #16213e;
    border: 1px solid #333;
    border-radius: 4px;
    color: #fff;
  }

  .controls button {
    padding: 0.5rem 1rem;
    background: #0f3460;
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th, td {
    padding: 0.5rem;
    text-align: left;
    border-bottom: 1px solid #333;
    font-size: 0.85rem;
  }

  th {
    background: #16213e;
  }

  code {
    background: #1a1a2e;
    padding: 0.2rem 0.4rem;
    border-radius: 3px;
  }

  .action-badge {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    background: #333;
  }

  .action-badge.put {
    background: #1a936f;
  }

  .action-badge.del {
    background: #8b0000;
  }

  .restore-btn {
    padding: 0.25rem 0.5rem;
    background: #0f3460;
    color: #fff;
    border: none;
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.8rem;
  }

  .empty {
    text-align: center;
    color: #888;
    padding: 2rem;
  }
</style>
