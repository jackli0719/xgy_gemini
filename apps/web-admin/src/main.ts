/**
 * 应用入口。
 *
 * 组装顺序有讲究：pinia 先装（会话 store 要在路由守卫之前可用），
 * 再装路由（守卫里 useSessionStore(pinia) 用的是这个实例）。
 */
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { createAppRouter } from "./router";

// Element Plus 的样式：整包引一次就够了（组件本身在各个 .vue 里按需 import）
import "element-plus/dist/index.css";
import "./styles.css";

const pinia = createPinia();
const app = createApp(App);

app.use(pinia);
app.use(createAppRouter(pinia));
app.mount("#app");
