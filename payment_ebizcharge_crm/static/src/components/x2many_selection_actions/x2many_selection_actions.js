/** @odoo-module **/

import { CheckBox } from "@web/core/checkbox/checkbox";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { StaticList } from "@web/model/relational_model/static_list";
import { SelectionBox } from "@web/views/view_components/selection_box";
import { MultiRecordViewButton } from "@web/views/view_button/multi_record_view_button";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { useState, onWillRender, useRef, onMounted, onPatched, onWillDestroy } from "@odoo/owl";

function stringifySearchValue(value) {
    if (value === false || value === null || value === undefined) {
        return "";
    }
    if (Array.isArray(value)) {
        return value.map(stringifySearchValue).join(" ");
    }
    if (typeof value === "object") {
        if ("display_name" in value) {
            return stringifySearchValue(value.display_name);
        }
        if ("name" in value) {
            return stringifySearchValue(value.name);
        }
        return Object.values(value).map(stringifySearchValue).join(" ");
    }
    return String(value);
}

patch(StaticList.prototype, {
    setup() {
        super.setup(...arguments);
        this.isDomainSelected = false;
    },

    get selection() {
        return this.records.filter((record) => record.selected);
    },

    get isRecordCountTrustable() {
        return true;
    },

    get hasLimitedCount() {
        return false;
    },

    async getResIds(isSelected) {
        const ids = isSelected
            ? this.isDomainSelected
                ? this.currentIds
                : this.selection.map((record) => record.resId)
            : this.records.map((record) => record.resId);
        return [...new Set(ids.filter((id) => typeof id === "number"))];
    },

    selectDomain(value) {
        return this.model.mutex.exec(() => this._selectDomain(value));
    },

    toggleSelection() {
        return this.model.mutex.exec(() => this._toggleSelection());
    },

    _selectDomain(value) {
        this.isDomainSelected = value;
    },

    _toggleSelection() {
        if (this.selection.length === this.records.length && this.records.length) {
            this.records.forEach((record) => record._toggleSelection(false));
            this._selectDomain(false);
        } else {
            this.records.forEach((record) => record._toggleSelection(true));
        }
    },
});

export class X2ManySelectionViewButton extends MultiRecordViewButton {
    static props = [...MultiRecordViewButton.props, "extraButtonContext?"];

    async onClick(ev, newWindow) {
        const resIds = await this.props.list.getResIds(true);
        // Apply any deferred toolbar field values (e.g. send_receipt) to the
        // selected records before the action runs.
        const toolbarValues = this.props.extraButtonContext?.selection_toolbar_values || {};
        const deferredWrite = {};
        for (const [key, value] of Object.entries(toolbarValues)) {
            if (key !== 'enable_surcharge_for_all') {
                deferredWrite[key] = value;
            }
        }
        if (Object.keys(deferredWrite).length && resIds.length) {
            await this.env.services.orm.write(
                this.props.list.resModel, resIds, deferredWrite,
            );
            const resIdSet = new Set(resIds);
            await Promise.all(
                this.props.list.records
                    .filter((r) => resIdSet.has(r.resId))
                    .map((r) => r.load())
            );
        }
        const clickParams = {
            ...this.props.clickParams,
            buttonContext: {
                ...(this.props.clickParams.buttonContext || {}),
                active_domain: this.props.domain,
                active_ids: resIds,
                active_model: this.props.list.resModel,
                ...(this.props.extraButtonContext || {}),
            },
        };

        this.env.onClickViewButton({
            clickParams,
            getResParams: () => ({
                context: this.props.list.context,
                evalContext: this.props.list.evalContext,
                resModel: this.props.list.resModel,
                resIds,
            }),
            newWindow,
        });
    }
}

export class X2ManySelectionField extends X2ManyField {
    static template = "payment_ebizcharge_crm.X2ManySelectionField";
    static components = {
        ...X2ManyField.components,
        CheckBox,
        SelectionBox,
        X2ManySelectionViewButton,
    };
    static props = {
        ...X2ManyField.props,
        showSearchBar: { type: Boolean, optional: true },
        showSelectionToggle: { type: Boolean, optional: true },
        showSelectionToggleExpr: { type: String, optional: true },
    };

    setup() {
        super.setup();
        this.uiState = useState({
            searchQuery: "",
            selectionToolbarValues: {},
        });

        // refs for DOM elements
        this.root = useRef('root');
        this.controlRef = useRef('control');
        this.centerRef = useRef('center');
        this.pagerRef = useRef('pager');

        // keep enable_surcharge_for_all header synced with visible records
        onWillRender(() => {
            try {
                const visible = this.list.records || [];
                if (!visible.length) {
                    this.uiState.selectionToolbarValues['enable_surcharge_for_all'] = false;
                    return;
                }
                const allEnabled = visible.every((rec) => {
                    const data = rec.data || {};
                    // ACH tokens and records with a generated link are neutral — they cannot
                    // change surcharge state so they should not influence the header toggle.
                    if (data['token_type'] === 'ach') return true;
                    if (data['generated_link']) return true;
                    return Boolean(data['inv_enable_sur']);
                });
                this.uiState.selectionToolbarValues['enable_surcharge_for_all'] = allEnabled;
                // Drop deferred toolbar values (e.g. send_receipt) whenever the
                // selection changes, so newly-selected records reflect their own
                // record state instead of the previous toggle.
                const sel = this.list.selection || [];
                const fingerprint = sel.map((r) => r.resId).sort().join(',');
                if (this._lastSelectionFingerprint !== undefined && this._lastSelectionFingerprint !== fingerprint) {
                    for (const fieldName of Object.keys(this.uiState.selectionToolbarValues)) {
                        if (fieldName === 'enable_surcharge_for_all') continue;
                        delete this.uiState.selectionToolbarValues[fieldName];
                    }
                }
                this._lastSelectionFingerprint = fingerprint;
            } catch (e) {
                // ignore
            }
        });

        onMounted(() => this._updatePositions());
        onPatched(() => this._updatePositions());
        this._onResize = () => this._updatePositions();
        window.addEventListener('resize', this._onResize);

        onWillDestroy(() => {
            window.removeEventListener('resize', this._onResize);
        });
    }

    _updatePositions() {
        try {
            const controlEl = this.controlRef.el;
            const centerEl = this.centerRef.el;
            const pagerEl = this.pagerRef.el;
            if (!controlEl || !centerEl) {
                return;
            }
            // Center relative to the control panel (toolbar) width — this stays stable
            // when the inner table gains/loses a vertical scrollbar, which would otherwise
            // shift the table's effective center and pull the button group off-axis.
            const controlRect = controlEl.getBoundingClientRect();
            centerEl.style.position = 'absolute';
            centerEl.style.left = `${controlRect.width / 2}px`;
            centerEl.style.transform = 'translateX(-50%)';
            centerEl.style.top = '0px';
            centerEl.style.zIndex = '10';
            if (pagerEl) {
                pagerEl.style.position = 'absolute';
                pagerEl.style.right = '0px';
                pagerEl.style.left = 'auto';
                pagerEl.style.top = '0px';
                pagerEl.style.zIndex = '10';
            }
        } catch (e) {
            // ignore
        }
    }

    get showSearchBar() {
        return this.props.viewMode === "list" && this.props.showSearchBar;
    }

    // Always show line selection checkboxes regardless of enable_selection_toggle option
    get showSelectionToggle() {
        return true;
    }

    get searchQuery() {
        return this.uiState.searchQuery.trim().toLowerCase();
    }

    get searchFieldNames() {
        return [...new Set(
            this.archInfo.columns
                .filter((column) => column.type === "field" && column.name)
                .map((column) => column.name)
        )];
    }

    get hasSelectedRecords() {
        return this.showSelectionToggle && this.props.viewMode === "list" && this.list.selection.length > 0;
    }

    get selectionHeaderButtons() {
        return this.archInfo.headerButtons.filter(
            (button) =>
                (button.clickParams.name || button.clickParams.type || button.clickParams.special) &&
                button.display !== "always" && !['Enable Surcharge for ALL', 'Send receipt to customer'].includes(button.string)
        );
    }

    get selectionHeaderFields() {
        if (!this.archInfo.xmlDoc) {
            return [];
        }
        const headerNode = [...this.archInfo.xmlDoc.children].find((node) => node.tagName === "header");
        if (!headerNode) {
            return [];
        }
        return [...headerNode.children]
            .filter((node) => node.tagName === "field")
            .map((node) => ({
                name: node.getAttribute("name"),
                string: node.getAttribute("string") || node.getAttribute("name"),
                invisible: node.getAttribute("invisible"),
                readonly: node.getAttribute("readonly"),
            }))
            .filter((field) => field.name);
    }

    get hasSelectionToolbarActions() {
        return this.selectionHeaderButtons.length > 0 || this.selectionHeaderFields.length > 0;
    }

    get selectionToolbarButtonContext() {
        return {
            selection_toolbar_values: { ...this.uiState.selectionToolbarValues },
        };
    }

    get filteredList() {
        if (!this.showSearchBar || !this.searchQuery) {
            return this.list;
        }

        const filteredRecords = this.list.records.filter((record) =>
            this.searchFieldNames.some((fieldName) =>
                stringifySearchValue(record.data[fieldName]).toLowerCase().includes(this.searchQuery)
            )
        );
        const filteredList = Object.create(this.list);
        filteredList.records = filteredRecords;
        filteredList.count = filteredRecords.length;
        filteredList.isDomainSelected = false;
        Object.defineProperty(filteredList, "selection", {
            get: () => filteredRecords.filter((record) => record.selected),
        });
        filteredList.toggleSelection = async () => {
            const allSelected =
                filteredRecords.length > 0 &&
                filteredRecords.every((record) => record.selected);
            filteredRecords.forEach((record) => record._toggleSelection(!allSelected));
            this.list._selectDomain(false);
        };
        filteredList.selectDomain = () => {};
        return filteredList;
    }

    onSearchInput(ev) {
        this.uiState.searchQuery = ev.target.value;
    }

    async onSelectionToolbarValueChange(fieldName, value) {
        // update UI state immediately
        this.uiState.selectionToolbarValues[fieldName] = value;
        // Defer non-surcharge toolbar fields to button click so the user can
        // toggle without losing their selection; applied in onClick below.
        if (fieldName !== 'enable_surcharge_for_all') {
            return;
        }
        try {
            // For enable_surcharge_for_all: all current-page non-ACH records.
            // For other fields: only selected non-ACH records.
            // ACH tokens cannot carry surcharge; token_type is column_invisible so always in rec.data.
            const resIds = fieldName === 'enable_surcharge_for_all'
                ? this.list.records
                    .filter((r) => r.data['token_type'] !== 'ach' && !r.data['generated_link'] && typeof r.resId === 'number')
                    .map((r) => r.resId)
                : (await this.list.getResIds(true)).filter((id) => {
                    const rec = this.list.records.find((r) => r.resId === id);
                    return !rec || rec.data['token_type'] !== 'ach';
                });
            if (!resIds || !resIds.length) {
                return;
            }
            // Write only inv_enable_sur (the stored field) for enable_surcharge_for_all.
            // Writing the computed inverse would retrigger write() and cause a second DB round-trip.
            const writePayload = fieldName === 'enable_surcharge_for_all'
                ? { inv_enable_sur: value }
                : { [fieldName]: value };
            await this.env.services.orm.write(this.list.resModel, resIds, writePayload);
            // Reload only the written records in-place via r.load(), which updates each
            // record through OWL's reactive system without replacing the StaticList.
            // Pagination state is preserved — the pager stays on the current page.
            const resIdSet = new Set(resIds);
            await Promise.all(
                this.list.records.filter((r) => resIdSet.has(r.resId)).map((r) => r.load())
            );
            const model = this.list.model || this.props.record?.model;
            if (model?.notify) {
                model.notify();
            }
            // mimic button behaviour: deselect records after per-selection operations
            if (fieldName !== 'enable_surcharge_for_all') {
                this.list.records.forEach((record) => {
                    if (record.selected) {
                        record._toggleSelection(false);
                    }
                });
                this.list._selectDomain(false);
            }
        } catch (err) {
            console.error('Error updating selection toolbar field', fieldName, err);
        }
    }

    isEnableSurchargeForAllVisible() {
        const field = this.selectionHeaderFields.find((f) => f.name === 'enable_surcharge_for_all');
        if (!field) return false;
        if (!field.invisible) return true;
        return !this.evalInvisible(field.invisible);
    }

    hasAllInvoicesSurchargedEnabled() {
        return this.getSelectionToolbarValue('enable_surcharge_for_all');
    }

    onEnableSurAllInputChange(checked) {
        return this.onSelectionToolbarValueChange('enable_surcharge_for_all', checked);
    }

    getSelectionToolbarValue(fieldName) {
        if (fieldName in this.uiState.selectionToolbarValues) {
            return Boolean(this.uiState.selectionToolbarValues[fieldName]);
        }
        // for enable_surcharge_for_all: consider checked only if all visible records have it true
        if (fieldName === 'enable_surcharge_for_all') {
            const visible = this.list.records || [];
            if (!visible.length) {
                return false;
            }
            return visible.every((record) => Boolean(record.data && record.data[fieldName]));
        }
        const sel = this.list.selection || [];
        if (!sel.length) {
            return false;
        }
        // for other fields: checked if any selected record has the field truthy
        return sel.some((record) => Boolean(record.data && record.data[fieldName]));
    }

    get rendererProps() {
        const props = super.rendererProps;
        if (this.props.viewMode === "list") {
            // Always enable row selectors
            props.allowSelectors = true;
            props.list = this.filteredList;
        }
        return props;
    }
}

export const x2ManySelectionField = {
    ...x2ManyField,
    component: X2ManySelectionField,
    displayName: _t("Relational table with selection actions"),
    extractProps: (fieldInfo, dynamicInfo) => {
        const props = x2ManyField.extractProps(fieldInfo, dynamicInfo);
        const options = fieldInfo.options || {};
        props.showSearchBar = Boolean(options.show_search_bar);
        props.showSelectionToggle =
            typeof options.show_selection_toggle === "boolean"
                ? options.show_selection_toggle
                : true;
        props.showSelectionToggleExpr =
            typeof options.show_selection_toggle === "string"
                ? options.show_selection_toggle
                : options.show_selection_toggle_expr;
        return props;
    },
};

registry.category("fields").add("x2many_selection_actions", x2ManySelectionField);
