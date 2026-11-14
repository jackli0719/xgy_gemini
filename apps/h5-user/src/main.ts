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

import "./styles.css";

const pinia = createPinia();
const app = createApp(App);

app.use(pinia);
app.use(createAppRouter(pinia));
app.mount("#app");
