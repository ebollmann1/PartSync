/** @odoo-module **/
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";

const FITMENT_FIELDS = [
    "fitment_make_ids",
    "fitment_model_ids",
    "fitment_year_ids",
    "fitment_submodel_ids",
    "fitment_wheel_ids",
    "fitment_vehicle_platform_ids",
];

const FITMENT_CONFIG = [
    { field: "fitment_make_ids",             label: "Make",                isEnabled: ()    => true },
    { field: "fitment_model_ids",            label: "Model",               isEnabled: (sel) => !!sel["fitment_make_ids"] },
    { field: "fitment_year_ids",             label: "Year",                isEnabled: (sel) => !!sel["fitment_make_ids"] },
    { field: "fitment_submodel_ids",         label: "Sub-Model",           isEnabled: (sel) => !!sel["fitment_make_ids"] && !!sel["fitment_model_ids"] },
    { field: "fitment_wheel_ids",            label: "Wheel Configuration", isEnabled: (sel) => !!sel["fitment_make_ids"] },
    { field: "fitment_vehicle_platform_ids", label: "Platform",            isEnabled: (sel) => !!sel["fitment_make_ids"] || !!sel["fitment_year_ids"] },
];

patch(SearchPanel.prototype, {

    setup() {
        super.setup(...arguments);
        this._mmy_refreshTimer = null;
        this._mmy_lastSelectionsKey = "__INIT__";
        this._mmy_widgetBuilt = false;

        onMounted(() => {
            // Build widget once on first mount
            this._buildMMYWidget();
        });

        onPatched(() => {
            // ✅ onPatched fires on EVERY re-render including toggleSidebar
            // Check if panel is visible and widget needs rebuild
            this._ensureMMYWidget();
            this._scheduleRefresh();
        });
    },

    get sections() {
        return this.env.searchModel
            .getSections(() => true)
            .filter((s) => !FITMENT_FIELDS.includes(s.fieldName) && !s.empty);
    },

    // ✅ Override toggleSidebar to force widget rebuild after expand
    toggleSidebar() {
        super.toggleSidebar(...arguments);
        // After sidebar expands, DOM is re-rendered — rebuild widget
        // Use timeout to wait for OWL to finish rendering
        setTimeout(() => {
            this._mmy_widgetBuilt = false;
            this._mmy_lastSelectionsKey = "__REBUILD__";
            this._buildMMYWidget();
        }, 10);
    },

    // ✅ Ensure widget exists — rebuild if missing (e.g. after expand)
    _ensureMMYWidget() {
        const panel = this.el || document.querySelector(".o_search_panel");
        if (!panel) return;

        // Check if fitment fields are part of the current search model
        const allSections = this.env.searchModel.getSections(() => true);
        const hasFitment = allSections.some((s) => FITMENT_FIELDS.includes(s.fieldName));
        if (!hasFitment) return;

        // If sidebar is expanded but widget is missing — rebuild
        if (this.state.sidebarExpanded) {
            const existing = panel.querySelector(".mmy_fitment_panel");
            if (!existing) {
                this._mmy_widgetBuilt = false;
                this._mmy_lastSelectionsKey = "__REBUILD__";
                this._buildMMYWidget();
            }
        }
    },

    _buildMMYWidget() {
        const allSections = this.env.searchModel.getSections(() => true);
        const hasFitment = allSections.some((s) => FITMENT_FIELDS.includes(s.fieldName));
        if (!hasFitment) return;

        const panel = this.el || document.querySelector(".o_search_panel");
        if (!panel) return;

        // Remove old widget
        panel.querySelector(".mmy_fitment_panel")?.remove();
        panel.querySelector(".mmy_clear_all_btn")?.remove();

        const container = document.createElement("div");
        container.className = "mmy_fitment_panel";

        for (const { field, label } of FITMENT_CONFIG) {
            const row = document.createElement("div");
            row.className = "mmy_row";
            const lbl = document.createElement("label");
            lbl.textContent = label;
            const sel = document.createElement("select");
            sel.dataset.field = field;
            sel.disabled = true;
            sel.appendChild(this._makePlaceholder(`-- Select ${label} --`));
            sel.addEventListener("change", (e) => this._onSelectChange(e));
            row.appendChild(lbl);
            row.appendChild(sel);
            container.appendChild(row);
        }

        // Insert BEFORE .o_search_panel_sections
        const nativeSections = panel.querySelector(".o_search_panel_sections");
        if (nativeSections) {
            nativeSections.insertAdjacentElement("beforebegin", container);
        } else {
            panel.insertAdjacentElement("afterbegin", container);
        }

        const clearBtn = document.createElement("button");
        clearBtn.className = "mmy_clear_all_btn";
        clearBtn.textContent = "Clear Filters ✕";
        clearBtn.addEventListener("click", () => this._clearAll());
        container.insertAdjacentElement("afterend", clearBtn);

        this._mmy_widgetBuilt = true;
        this._mmy_lastSelectionsKey = "__REBUILD__";
        this._refreshMMYWidget();
    },

    _scheduleRefresh() {
        if (this._mmy_refreshTimer) clearTimeout(this._mmy_refreshTimer);
        this._mmy_refreshTimer = setTimeout(() => {
            this._mmy_refreshTimer = null;
            this._refreshMMYWidget();
        }, 20);  // ✅ Reduced from 50ms to 20ms for snappier response
    },

    _refreshMMYWidget() {
        const panel = this.el || document.querySelector(".o_search_panel");
        if (!panel) return;

        // If widget not in DOM, skip
        if (!panel.querySelector(".mmy_fitment_panel")) return;

        const allSections = this.env.searchModel.getSections(() => true);

        const selections = {};
        const valueCounts = {};
        for (const { field } of FITMENT_CONFIG) {
            const section = allSections.find((s) => s.fieldName === field);
            const checked = this._getCheckedIds(section);
            selections[field] = checked.length ? checked[0] : null;
            // ✅ Track value counts so we detect when data arrives from server
            valueCounts[field] = section?.values ? section.values.size : 0;
        }

        const selKey = JSON.stringify({ sel: selections, cnt: valueCounts });
        if (selKey === this._mmy_lastSelectionsKey) return;
        this._mmy_lastSelectionsKey = selKey;

        for (const { field, label, isEnabled } of FITMENT_CONFIG) {
            const sel = panel.querySelector(`select[data-field="${field}"]`);
            if (!sel) continue;

            const section   = allSections.find((s) => s.fieldName === field);
            const currentId = selections[field] ? String(selections[field]) : "";
            const allValues = section?.values ? [...section.values.values()] : [];
            const sectionEmpty = allValues.length === 0;

            // ✅ No more __count filtering — show all values returned by server
            // With expand="0", the server already returns only matching values
            const options = allValues
                .filter((v) => {
                    // Always keep the currently selected value
                    if (String(v.id) === currentId || v.checked) return true;
                    return true;  // Show all — server filters via expand="0"
                })
                .sort((a, b) =>
                    (a.display_name || "").trim().localeCompare((b.display_name || "").trim())
                );

            const shouldEnable = isEnabled(selections);
            const enabled = shouldEnable && options.length > 0 && !sectionEmpty;

            const domKey = `${!enabled}|${currentId}|${options.length}`;
            if (sel.dataset.domKey === domKey) continue;
            sel.dataset.domKey = domKey;

            sel.innerHTML = "";
            sel.disabled = !enabled;
            sel.classList.remove("mmy_loading");

            let phText;
            if (!shouldEnable) {
                phText = field === "fitment_submodel_ids" && selections["fitment_make_ids"]
                    ? "-- Select Model first --"
                    : "-- Select Make first --";
            } else if (sectionEmpty) {
                phText = "-- Loading... --";
            } else if (options.length === 0) {
                phText = `-- No ${label}s available --`;
            } else {
                phText = `-- All ${label}s --`;
            }
            sel.appendChild(this._makePlaceholder(phText));

            // ✅ Use DocumentFragment for batch DOM insertion (faster)
            const frag = document.createDocumentFragment();
            for (const opt of options) {
                const o = document.createElement("option");
                o.value = String(opt.id);
                o.textContent = (opt.display_name || "").trim();
                if (String(opt.id) === currentId) o.selected = true;
                frag.appendChild(o);
            }
            sel.appendChild(frag);
        }
    },

    updateActiveValues() {
        const all = this.env.searchModel.getSections(() => true);
        if (this.sections.length === 0) this.state.sidebarExpanded = false;

        for (const section of all) {
            if (section.type === "category") {
                this.state.active[section.id] = section.activeValueId;
            } else {
                this.state.active[section.id] = {};
                const iter = (values) =>
                    values?.forEach((v) => {
                        this.state.active[section.id][v.id] = v.checked;
                    });
                section.groups?.forEach((g) => iter(g.values.values()));
                iter(section.values?.values());
            }
        }
        this._scheduleRefresh();
    },

    _onSelectChange(event) {
        const field    = event.target.dataset.field;
        const rawValue = event.target.value;
        if (!FITMENT_CONFIG.find((c) => c.field === field)) return;

        const allSections = this.env.searchModel.getSections(() => true);
        const section     = allSections.find((s) => s.fieldName === field);
        if (!section) return;

        event.target.classList.add("mmy_loading");
        event.target.dataset.domKey = "";

        let found = false;
        for (const { field: f } of FITMENT_CONFIG) {
            if (found) {
                const ds = document.querySelector(`select[data-field="${f}"]`);
                if (ds) ds.dataset.domKey = "";
            }
            if (f === field) found = true;
        }

        this.env.searchModel.searchPanelInfo.shouldReload = true;
        this.env.searchModel.clearSections([section.id]);

        if (rawValue) {
            const id = isNaN(rawValue) ? rawValue : parseInt(rawValue, 10);
            if (section.values && !section.values.has(id)) {
                section.values.set(id, {
                    id,
                    display_name: event.target.options[event.target.selectedIndex].text,
                    checked: false,
                });
            }
            this.env.searchModel.searchPanelInfo.shouldReload = true;
            this.env.searchModel.toggleFilterValues(section.id, [id]);
        }
    },

    _clearAll() {
        const allSections = this.env.searchModel.getSections(() => true);
        const ids = allSections
            .filter((s) => FITMENT_FIELDS.includes(s.fieldName))
            .map((s) => s.id);
        if (ids.length) {
            this.env.searchModel.searchPanelInfo.shouldReload = true;
            this.env.searchModel.clearSections(ids);
        }
        this._mmy_lastSelectionsKey = "__REBUILD__";
        document.querySelectorAll(".mmy_fitment_panel select").forEach(s => {
            s.dataset.domKey = "";
        });
    },

    _getCheckedIds(section) {
        if (!section?.values) return [];
        return [...section.values.entries()]
            .filter(([, v]) => v.checked)
            .map(([id]) => id);
    },

    _makePlaceholder(text) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = text;
        return o;
    },
});