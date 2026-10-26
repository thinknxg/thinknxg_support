import { createApp } from "vue";
import App from "./support_portal/App.vue";
import { startRouter } from "./support_portal/router";

startRouter();
const mount = document.getElementById("support-app");
if (mount) {
	mount.innerHTML = "";
	createApp(App).mount(mount);
}
