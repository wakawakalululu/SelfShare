import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'

// 组件里使用了 <script lang="ts">，必须走 TS 预处理器，否则 Svelte 编译器
// 遇到类型注解会直接报 "Unexpected token"。
export default {
  preprocess: vitePreprocess(),
  compilerOptions: {
    tag: 'svelte:options',
  },
}
