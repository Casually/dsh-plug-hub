/* dsh-plug-hub 管理台（Vue 3 + Element Plus，CDN 全局构建，无构建步骤）。 */
/* global Vue, ElementPlus */
(function () {
	"use strict";
	const { createApp, reactive, ref, computed, onMounted } = Vue;

	const TOKEN_KEY = "dsh_plug_hub_admin_token";

	async function api(path, options) {
		const opts = Object.assign({ headers: {} }, options || {});
		const token = localStorage.getItem(TOKEN_KEY) || "";
		opts.headers["X-Admin-Token"] = token;
		if (opts.body !== undefined) opts.headers["Content-Type"] = "application/json";
		const res = await fetch(path, opts);
		if (res.status === 401) throw new Error("管理令牌无效或已过期");
		const data = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));
		return data;
	}

	function fmtTime(epoch) {
		if (!epoch) return "—";
		const d = new Date(epoch * 1000);
		return d.toLocaleString("zh-CN", { hour12: false });
	}
	function daysSince(iso) {
		if (!iso) return null;
		const t = Date.parse(iso);
		if (Number.isNaN(t)) return null;
		return Math.max(0, Math.floor((Date.now() - t) / 86400000));
	}
	function activityOf(row) {
		if (row.archived) return { label: "已归档", type: "info" };
		const days = daysSince(row.pushed_at);
		if (days === null) return { label: "未知", type: "info" };
		if (days <= 30) return { label: "活跃 · " + days + "d", type: "success" };
		if (days <= 90) return { label: "关注 · " + days + "d", type: "primary" };
		if (days <= 180) return { label: "放缓 · " + days + "d", type: "warning" };
		return { label: "停更 · " + days + "d", type: "danger" };
	}
	const STATUS_META = {
		none: { label: "未策展", type: "info" },
		candidate: { label: "候选", type: "warning" },
		approved: { label: "已收录", type: "success" },
		rejected: { label: "已排除", type: "danger" },
	};
	const KIND_META = {
		"new": { label: "新增", type: "success" },
		"renamed": { label: "更名", type: "warning" },
		"archived": { label: "归档", type: "info" },
		"unarchived": { label: "恢复", type: "success" },
		"vanished": { label: "消失", type: "danger" },
	};

	const EditDialog = {
		props: ["modelValue", "repo", "categories"],
		emits: ["update:modelValue", "saved"],
		setup(props, ctx) {
			const form = reactive({
				name: "", category_id: 11, status: "candidate", summary_zh: "",
				summary_en: "", npm_package: "", install_cmd: "", tagsText: "",
			});
			const saving = ref(false);
			function fill() {
				const r = props.repo || {};
				form.name = r.plugin_name || r.name || "";
				form.category_id = r.plugin_category_id || 11;
				form.status = r.plugin_status || "candidate";
				form.summary_zh = r.summary_zh || "";
				form.summary_en = r.summary_en || "";
				form.npm_package = r.npm_package || "";
				form.install_cmd = r.install_cmd || "";
				try { form.tagsText = (JSON.parse(r.plugin_tags || "[]") || []).join(", "); }
				catch (e) { form.tagsText = ""; }
			}
			Vue.watch(() => props.repo, fill);
			Vue.watch(() => props.modelValue, (v) => { if (v) fill(); });
			async function save() {
				saving.value = true;
				try {
					const tags = form.tagsText.split(",").map((s) => s.trim()).filter((s) => s !== "");
					await api("/api/admin/plugins/" + props.repo.repo_id, {
						method: "POST",
						body: JSON.stringify({
							name: form.name, category_id: form.category_id, status: form.status,
							summary_zh: form.summary_zh, summary_en: form.summary_en,
							npm_package: form.npm_package, install_cmd: form.install_cmd, tags,
						}),
					});
					ElementPlus.ElMessage.success("已保存策展信息");
					ctx.emit("saved");
					ctx.emit("update:modelValue", false);
				} catch (e) {
					ElementPlus.ElMessage.error(e.message);
				} finally { saving.value = false; }
			}
			return { form, saving, save };
		},
		template: `
<el-dialog :model-value="modelValue" @update:model-value="(v) => $emit('update:modelValue', v)" :title="'策展：' + (repo ? repo.full_name : '')" width="640px">
	<el-form label-width="90px" label-position="right">
		<el-form-item label="展示名">
			<el-input v-model="form.name" placeholder="包名或展示名" />
		</el-form-item>
		<el-form-item label="分类">
			<el-select v-model="form.category_id" style="width: 100%">
				<el-option v-for="c in categories" :key="c.id" :value="c.id" :label="c.name_zh + ' / ' + c.name_en" />
			</el-select>
		</el-form-item>
		<el-form-item label="状态">
			<el-radio-group v-model="form.status">
				<el-radio value="candidate">候选</el-radio>
				<el-radio value="approved">收录</el-radio>
				<el-radio value="rejected">排除</el-radio>
			</el-radio-group>
		</el-form-item>
		<el-form-item label="简介（中）">
			<el-input v-model="form.summary_zh" type="textarea" :rows="2" placeholder="一句话中文简介" />
		</el-form-item>
		<el-form-item label="简介（英）">
			<el-input v-model="form.summary_en" type="textarea" :rows="2" placeholder="One-line English summary" />
		</el-form-item>
		<el-form-item label="npm 包">
			<el-input v-model="form.npm_package" placeholder="已发布到 npm 时填写（可留空走 github: 安装）" />
		</el-form-item>
		<el-form-item label="安装命令">
			<el-input v-model="form.install_cmd" placeholder="留空自动生成 dsh plugin --profile web add -w ..." />
		</el-form-item>
		<el-form-item label="标签">
			<el-input v-model="form.tagsText" placeholder="逗号分隔，如：sidebar, theme" />
		</el-form-item>
	</el-form>
	<template #footer>
		<el-button @click="$emit('update:modelValue', false)">取消</el-button>
		<el-button type="primary" :loading="saving" @click="save">保存</el-button>
	</template>
</el-dialog>`,
	};

	const App = {
		components: { EditDialog },
		setup() {
			const token = ref(localStorage.getItem(TOKEN_KEY) || "");
			const authorized = ref(localStorage.getItem(TOKEN_KEY) !== null);
			const tab = ref("curation");
			const loading = ref(false);
			const overview = ref(null);
			const repos = ref([]);
			const repoTotal = ref(0);
			const categories = ref([]);
			const filterText = ref("");
			const filterStatus = ref("");
			const filterCategory = ref("");
			const page = ref(1);
			const pageSize = ref(100);
			const editVisible = ref(false);
			const editRepo = ref(null);

			async function loadOverview() {
				try { overview.value = await api("/api/admin/overview"); }
				catch (e) { ElementPlus.ElMessage.error(e.message); }
			}
			async function loadRepos() {
				loading.value = true;
				try {
					const data = await api("/api/admin/repos");
					repos.value = data.repos;
					repoTotal.value = data.total !== undefined ? data.total : data.repos.length;
					categories.value = data.categories;
				} catch (e) {
					ElementPlus.ElMessage.error(e.message);
				} finally { loading.value = false; }
			}
			function enterToken() {
				if (token.value.trim() === "") return;
				localStorage.setItem(TOKEN_KEY, token.value.trim());
				authorized.value = true;
				loadAll();
			}
			async function loadAll() { await Promise.all([loadOverview(), loadRepos()]); }

			const filtered = computed(() => {
				const needle = filterText.value.trim().toLowerCase();
				return repos.value.filter((r) => {
					const status = r.plugin_status || "none";
					if (filterStatus.value !== "" && status !== filterStatus.value) return false;
					if (filterCategory.value !== "" && String(r.plugin_category_id || "") !== filterCategory.value) return false;
					if (needle !== "") {
						const hay = (r.full_name + " " + (r.description || "") + " " + (r.summary_zh || "") + " " + (r.summary_en || "")).toLowerCase();
						if (hay.indexOf(needle) === -1) return false;
					}
					return true;
				});
			});
			const stats = computed(() => {
				const total = repos.value.length;
				let approved = 0, candidate = 0, none = 0;
				for (const r of repos.value) {
					const s = r.plugin_status || "none";
					if (s === "approved") approved++;
					else if (s === "candidate") candidate++;
					else if (s === "none") none++;
				}
				return { total, approved, candidate, none };
			});
			const paged = computed(() => filtered.value.slice(
				(page.value - 1) * pageSize.value, page.value * pageSize.value));
			Vue.watch([filterText, filterStatus, filterCategory], () => { page.value = 1; });

			function openEdit(row) { editRepo.value = row; editVisible.value = true; }
			async function quickApprove(row) {
				try {
					await api("/api/admin/plugins/" + row.repo_id, {
						method: "POST",
						body: JSON.stringify({
							name: row.plugin_name || row.name,
							category_id: row.plugin_category_id || 11,
							status: "approved",
							summary_zh: row.summary_zh || "", summary_en: row.summary_en || "",
							npm_package: row.npm_package || "", install_cmd: row.install_cmd || "",
							tags: JSON.parse(row.plugin_tags || "[]"),
						}),
					});
					ElementPlus.ElMessage.success("已收录：" + row.full_name);
					await loadRepos();
				} catch (e) { ElementPlus.ElMessage.error(e.message); }
			}
			async function doSync() {
				loading.value = true;
				try {
					const r = await api("/api/admin/sync", { method: "POST" });
					ElementPlus.ElMessage.success("同步完成：共 " + r.total + " 个仓库（新增 " + r.added + "，更名 " + r.renamed + "，归档 " + r.archived + "）");
					await loadAll();
				} catch (e) { ElementPlus.ElMessage.error(e.message); }
				finally { loading.value = false; }
			}
			async function doGenerate() {
				try {
					const r = await api("/api/admin/generate-site", { method: "POST" });
					ElementPlus.ElMessage.success("站点已生成：" + r.plugins + " 个收录插件");
				} catch (e) { ElementPlus.ElMessage.error(e.message); }
			}
			function catName(id) {
				const c = categories.value.find((x) => x.id === id);
				return c !== undefined ? c.name_zh : "—";
			}
			onMounted(() => { if (authorized.value) loadAll(); });

			return {
				token, authorized, tab, loading, overview, repos, categories, repoTotal,
				filterText, filterStatus, filterCategory, filtered, paged, stats,
				page, pageSize,
				editVisible, editRepo, enterToken, loadAll, openEdit, quickApprove,
				doSync, doGenerate, catName, fmtTime, activityOf, STATUS_META, KIND_META,
			};
		},
		template: `
<div>
	<div class="hub-head">
		<h1>dsh-plug-hub 管理台</h1>
		<span class="sub">DeepSeek Harness 插件社区目录 · 全量监测 / 人工策展 / 分类编目</span>
	</div>
	<div class="hub-body" v-if="!authorized">
		<div class="panel" style="max-width: 460px; margin: 60px auto;">
			<h3 style="margin-top:0">输入管理令牌</h3>
			<p class="muted">服务端启动时会打印 HUB_ADMIN_TOKEN（未配置环境变量时为临时令牌）。</p>
			<el-input v-model="token" placeholder="管理令牌" show-password @keyup.enter="enterToken" />
			<el-button type="primary" style="margin-top:12px" @click="enterToken">进入管理台</el-button>
		</div>
	</div>
	<div class="hub-body" v-else>
		<div class="stat-cards">
			<div class="stat-card"><div class="num">{{ repoTotal }}</div><div class="lbl">主题仓库（全量快照）</div></div>
			<div class="stat-card"><div class="num" style="color:#67c23a">{{ stats.approved }}</div><div class="lbl">已收录</div></div>
			<div class="stat-card"><div class="num" style="color:#909399">{{ stats.none }}</div><div class="lbl">未策展（快照内）</div></div>
			<div class="stat-card"><div class="num">{{ overview && overview.last_sync_at ? overview.last_sync_at.replace('T',' ').replace('Z','') : '—' }}</div><div class="lbl">上次同步 (UTC)</div></div>
		</div>
		<div class="panel">
			<div class="toolbar">
				<el-button type="primary" :loading="loading" @click="doSync">立即同步</el-button>
				<el-button @click="doGenerate">重新生成站点</el-button>
				<el-button @click="loadAll">刷新</el-button>
				<span class="spacer"></span>
				<span class="muted">自动同步：每 4 小时（进程内调度器 / CI 定时）</span>
			</div>
			<el-tabs v-model="tab">
				<el-tab-pane label="策展管理" name="curation">
					<div class="toolbar">
						<el-input v-model="filterText" placeholder="搜索仓库 / 描述 / 简介…" style="width: 260px" clearable />
						<el-select v-model="filterStatus" placeholder="状态" clearable style="width: 130px">
							<el-option value="none" label="未策展" />
							<el-option value="candidate" label="候选" />
							<el-option value="approved" label="已收录" />
							<el-option value="rejected" label="已排除" />
						</el-select>
						<el-select v-model="filterCategory" placeholder="分类" clearable style="width: 200px">
							<el-option v-for="c in categories" :key="c.id" :value="String(c.id)" :label="c.name_zh" />
						</el-select>
						<span class="muted">共 {{ filtered.length }} 条</span>
					</div>
					<el-table :data="paged" v-loading="loading" size="small" max-height="560">
						<el-table-column prop="full_name" label="仓库" min-width="200">
							<template #default="{ row }">
								<a :href="row.html_url" target="_blank" style="color:#409eff;text-decoration:none">{{ row.full_name }}</a>
								<el-tag v-if="row.archived" size="small" type="info" style="margin-left:6px">已归档</el-tag>
							</template>
						</el-table-column>
						<el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
						<el-table-column label="活跃度" width="120">
							<template #default="{ row }">
								<el-tag size="small" :type="activityOf(row).type">{{ activityOf(row).label }}</el-tag>
							</template>
						</el-table-column>
						<el-table-column prop="stars" label="★" width="70" sortable />
						<el-table-column label="分类" width="130">
							<template #default="{ row }">{{ row.plugin_category_id ? catName(row.plugin_category_id) : '—' }}</template>
						</el-table-column>
						<el-table-column label="状态" width="90">
							<template #default="{ row }">
								<el-tag size="small" :type="STATUS_META[row.plugin_status || 'none'].type">{{ STATUS_META[row.plugin_status || 'none'].label }}</el-tag>
							</template>
						</el-table-column>
						<el-table-column label="操作" width="150" fixed="right">
							<template #default="{ row }">
								<el-button size="small" @click="openEdit(row)">策展</el-button>
								<el-button size="small" type="success" v-if="(row.plugin_status || 'candidate') !== 'approved'" @click="quickApprove(row)">收录</el-button>
							</template>
						</el-table-column>
					</el-table>
					<el-pagination style="margin-top:12px;justify-content:flex-end" background
						layout="total, sizes, prev, pager, next" :total="filtered.length"
						v-model:current-page="page" v-model:page-size="pageSize"
						:page-sizes="[100, 200, 500, 1000]" />
				</el-tab-pane>
				<el-tab-pane label="事件监测" name="events">
					<el-table :data="overview ? overview.events : []" size="small" max-height="560">
						<el-table-column label="时间" width="170">
							<template #default="{ row }">{{ fmtTime(row.detected_at) }}</template>
						</el-table-column>
						<el-table-column label="事件" width="90">
							<template #default="{ row }">
								<el-tag size="small" :type="(KIND_META[row.kind] || {type:'info'}).type">{{ (KIND_META[row.kind] || {label:row.kind}).label }}</el-tag>
							</template>
						</el-table-column>
						<el-table-column prop="full_name" label="仓库" min-width="220" />
						<el-table-column prop="detail" label="说明" min-width="260" show-overflow-tooltip />
					</el-table>
				</el-tab-pane>
				<el-tab-pane label="同步日志" name="runs">
					<el-table :data="overview ? overview.sync_runs : []" size="small" max-height="560">
						<el-table-column label="开始" width="170">
							<template #default="{ row }">{{ fmtTime(row.started_at) }}</template>
						</el-table-column>
						<el-table-column prop="trigger" label="来源" width="90" />
						<el-table-column label="结果" width="80">
							<template #default="{ row }">
								<el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? '成功' : '失败' }}</el-tag>
							</template>
						</el-table-column>
						<el-table-column label="新增" width="70"><template #default="{ row }">{{ row.added }}</template></el-table-column>
						<el-table-column label="更名" width="70"><template #default="{ row }">{{ row.renamed }}</template></el-table-column>
						<el-table-column label="归档" width="70"><template #default="{ row }">{{ row.archived }}</template></el-table-column>
						<el-table-column label="消失" width="70"><template #default="{ row }">{{ row.vanished }}</template></el-table-column>
						<el-table-column prop="message" label="信息" min-width="240" show-overflow-tooltip />
					</el-table>
				</el-tab-pane>
			</el-tabs>
		</div>
	</div>
	<edit-dialog v-model="editVisible" :repo="editRepo" :categories="categories" @saved="loadRepos" />
</div>`,
	};

	const app = createApp(App);
	app.use(ElementPlus, { locale: ElementPlusLocaleZhCn || undefined });
	app.mount("#app");
})();
