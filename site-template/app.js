/* DSH 插件社区站点（纯静态，GitHub Pages 部署；数据来自 catalog.json）。 */
/* global Vue */
(function () {
	"use strict";
	const { createApp, ref, computed, onMounted } = Vue;

	const App = {
		setup() {
			const loading = ref(true);
			const error = ref("");
			const plugins = ref([]);
			const categories = ref([]);
			const q = ref("");
			const cat = ref("");
			const act = ref("");
			const lang = ref(localStorage.getItem("dsh_hub_lang") === "en" ? "en" : "zh");
			const generatedAt = ref("");
			const visibleCount = ref(72);
			const sentinel = ref(null);
			let observer = null;

			async function load() {
				try {
					const res = await fetch("catalog.json", { cache: "no-cache" });
					if (!res.ok) throw new Error("HTTP " + res.status);
					const data = await res.json();
					plugins.value = data.plugins || [];
					categories.value = data.categories || [];
					generatedAt.value = data.generated_at || "";
				} catch (e) {
					error.value = "目录加载失败：" + e.message;
				} finally { loading.value = false; }
			}
			onMounted(() => {
				load();
				observer = new IntersectionObserver((entries) => {
					if (entries.some((e) => e.isIntersecting)) {
						visibleCount.value += 72;
					}
				}, { rootMargin: "600px" });
				Vue.watch(sentinel, (el) => { if (el !== null) observer.observe(el); });
			});

			const ACT_SIG = { active: "sig-active", watch: "sig-watch", slowing: "sig-slowing", stalled: "sig-stalled" };
			function actLabel(p) {
				return lang.value === "zh" ? p.activity.label_zh : p.activity.label_en;
			}
			const counts = computed(() => {
				const map = {};
				for (const p of plugins.value) {
					map[p.category.slug] = (map[p.category.slug] || 0) + 1;
				}
				return map;
			});
			const filtered = computed(() => {
				const needle = q.value.trim().toLowerCase();
				return plugins.value.filter((p) => {
					if (cat.value !== "" && p.category.slug !== cat.value) return false;
					if (act.value !== "" && p.activity.level !== act.value) return false;
					if (needle !== "") {
						const hay = [p.name, p.full_name, p.summary_zh, p.summary_en, (p.tags || []).join(" "),
							p.category.name_zh, p.category.name_en].join(" ").toLowerCase();
						if (hay.indexOf(needle) === -1) return false;
					}
					return true;
				});
			});
			function pickCat(slug) { cat.value = cat.value === slug ? "" : slug; visibleCount.value = 72; }
			function pickAct(level) { act.value = act.value === level ? "" : level; visibleCount.value = 72; }
			Vue.watch([q, cat, act], () => { visibleCount.value = 72; });
			const shown = computed(() => filtered.value.slice(0, visibleCount.value));
			const hasMore = computed(() => filtered.value.length > shown.value.length);
			function copyCmd(p, event) {
				const text = p.install.command;
				const done = () => {
					const btn = event.target;
					btn.textContent = lang.value === "zh" ? "已复制 ✓" : "Copied ✓";
					setTimeout(() => { btn.textContent = lang.value === "zh" ? "复制" : "Copy"; }, 1500);
				};
				if (navigator.clipboard && navigator.clipboard.writeText) {
					navigator.clipboard.writeText(text).then(done).catch(() => fallback());
				} else fallback();
				function fallback() {
					const ta = document.createElement("textarea");
					ta.value = text;
					document.body.appendChild(ta);
					ta.select();
					document.execCommand("copy");
					ta.remove();
					done();
				}
			}
			function switchLang() {
				lang.value = lang.value === "zh" ? "en" : "zh";
				localStorage.setItem("dsh_hub_lang", lang.value);
			}
			const zh = computed(() => lang.value === "zh");
			return {
				loading, error, plugins, categories, q, cat, act, lang, zh, generatedAt,
				filtered, shown, hasMore, sentinel, visibleCount,
				counts, ACT_SIG, actLabel, pickCat, pickAct, copyCmd, switchLang,
			};
		},
		template: `
<main>
	<div class="toolbar">
		<input type="search" v-model="q" :placeholder="zh ? '搜索插件（名称 / 简介 / 标签）…' : 'Search plugins (name / summary / tags)…'" />
		<span class="chip" :class="{ active: lang === 'en' }" @click="switchLang">{{ zh ? 'EN' : '中文' }}</span>
	</div>
	<div class="chips">
		<span class="chip" :class="{ active: cat === '' }" @click="cat = ''">
			{{ zh ? '全部' : 'All' }}<span class="cnt">{{ plugins.length }}</span></span>
		<span v-for="c in categories" :key="c.slug" class="chip" :class="{ active: cat === c.slug }" @click="pickCat(c.slug)">
			{{ zh ? c.name_zh : c.name_en }}<span class="cnt">{{ counts[c.slug] || 0 }}</span></span>
	</div>
	<div class="chips">
		<span class="chip" :class="{ active: act === 'active' }" @click="pickAct('active')">{{ zh ? '🟢 活跃' : '🟢 Active' }}</span>
		<span class="chip" :class="{ active: act === 'watch' }" @click="pickAct('watch')">{{ zh ? '🔵 关注' : '🔵 Watch' }}</span>
		<span class="chip" :class="{ active: act === 'slowing' }" @click="pickAct('slowing')">{{ zh ? '🟡 放缓' : '🟡 Slowing' }}</span>
		<span class="chip" :class="{ active: act === 'stalled' }" @click="pickAct('stalled')">{{ zh ? '🔴 停更' : '🔴 Stalled' }}</span>
	</div>
	<div v-if="loading" class="empty">{{ zh ? '正在加载目录…' : 'Loading catalog…' }}</div>
	<div v-else-if="error !== ''" class="empty">{{ error }}</div>
	<div v-else-if="filtered.length === 0" class="empty">{{ zh ? '没有匹配的插件' : 'No matching plugins' }}</div>
	<div v-else class="grid">
		<div class="card" v-for="p in shown" :key="p.full_name">
			<div class="card-head">
				<h3 :title="p.full_name">
					<a :href="p.url" target="_blank">{{ p.name }}</a>
				</h3>
				<span class="badge cat">{{ zh ? p.category.name_zh : p.category.name_en }}</span>
				<span class="badge" :class="ACT_SIG[p.activity.level]" :title="(zh ? '最近提交距今 ' : 'Last push ') + (p.activity.days_since !== null ? p.activity.days_since + ' 天' : '—')">
					{{ actLabel(p) }}</span>
			</div>
			<p class="summary" v-if="zh && p.summary_zh !== ''">{{ p.summary_zh }}</p>
			<p class="summary en" v-if="zh && p.summary_en !== ''">{{ p.summary_en }}</p>
			<p class="summary" v-if="!zh && p.summary_en !== ''">{{ p.summary_en }}</p>
			<p class="summary en" v-if="!zh && p.summary_zh !== ''">{{ p.summary_zh }}</p>
			<div class="meta">
				<span>★ {{ p.stats.stars }}</span>
				<span v-if="p.stats.license !== ''">{{ p.stats.license }}</span>
				<span v-if="p.stats.language !== ''">{{ p.stats.language }}</span>
				<span v-if="p.archived">{{ zh ? '已归档' : 'Archived' }}</span>
			</div>
			<div class="install" v-if="p.install.command !== ''">
				<code :title="p.install.command">{{ p.install.command }}</code>
				<button @click="copyCmd(p, $event)">{{ zh ? '复制' : 'Copy' }}</button>
			</div>
		</div>
	</div>
	<div v-if="!loading && hasMore" style="text-align:center;padding:16px">
		<button class="chip active" ref="sentinel" @click="visibleCount += 144" style="font-size:14px;padding:8px 18px">
			{{ zh ? '显示更多（剩余 ' + (filtered.length - shown.length) + '）' : 'Show more (' + (filtered.length - shown.length) + ' left)' }}</button>
	</div>
	<p class="empty" v-if="!loading && generatedAt !== ''" style="padding: 18px 0">
		{{ zh ? '目录生成于 ' : 'Catalog generated at ' }}{{ generatedAt }}</p>
</main>`,
	};

	createApp(App).mount("#app");
})();
