<script lang="ts">
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import Dashboard from './pages/Dashboard.svelte'
  import Folders from './pages/Folders.svelte'
  import Devices from './pages/Devices.svelte'
  import History from './pages/History.svelte'
  import Settings from './pages/Settings.svelte'

  let currentPage = 'dashboard'
  let version = '2.0'

  const pages: Record<string, string> = {
    dashboard: '仪表盘',
    folders: '同步文件夹',
    devices: '设备',
    history: '版本历史',
    settings: '设置',
  }

  function navigate(page: string) {
    currentPage = page
  }

  onMount(async () => {
    try {
      const info: any = await invoke('get_version')
      version = info.version
    } catch (e) {
      console.warn('get_version failed:', e)
    }
  })
</script>

<div class="app">
  <nav class="sidebar">
    <div class="logo">
      <h1>SelfShare</h1>
      <span class="version">v{version}</span>
    </div>
    <ul>
      {#each Object.entries(pages) as [key, label]}
        <li>
          <button
            class:active={currentPage === key}
            on:click={() => currentPage = key}
          >
            {label}
          </button>
        </li>
      {/each}
    </ul>
  </nav>
  <main class="content">
    {#if currentPage === 'dashboard'}
      <Dashboard {navigate} />
    {:else if currentPage === 'folders'}
      <Folders />
    {:else if currentPage === 'devices'}
      <Devices {navigate} />
    {:else if currentPage === 'history'}
      <History />
    {:else if currentPage === 'settings'}
      <Settings />
    {/if}
  </main>
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e;
    color: #eee;
  }

  .app {
    display: flex;
    height: 100vh;
  }

  .sidebar {
    width: 200px;
    background: #16213e;
    padding: 1rem;
    display: flex;
    flex-direction: column;
  }

  .logo {
    margin-bottom: 2rem;
  }

  .logo h1 {
    margin: 0;
    font-size: 1.5rem;
    color: #0f3460;
  }

  .logo .version {
    font-size: 0.75rem;
    color: #666;
  }

  .sidebar ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .sidebar li {
    margin-bottom: 0.5rem;
  }

  .sidebar button {
    width: 100%;
    padding: 0.75rem 1rem;
    background: transparent;
    border: none;
    color: #aaa;
    text-align: left;
    cursor: pointer;
    border-radius: 6px;
    font-size: 0.9rem;
    transition: all 0.2s;
  }

  .sidebar button:hover {
    background: #1a1a2e;
    color: #fff;
  }

  .sidebar button.active {
    background: #0f3460;
    color: #fff;
  }

  .content {
    flex: 1;
    padding: 2rem;
    overflow-y: auto;
  }
</style>
