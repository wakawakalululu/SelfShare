import App from './App.svelte'
import './styles.css'

// 项目使用 Svelte 4：组件实例化用 `new App(...)`，不是 Svelte 5 的 `mount()`。
const target = document.getElementById('app')
if (!target) throw new Error('#app container is missing')

const app = new App({ target })

export default app
