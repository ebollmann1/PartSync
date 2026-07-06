// /** @odoo-module */

import { SearchModel } from "@web/search/search_model";
import { patch } from "@web/core/utils/patch";

patch(SearchModel.prototype, {
    async _reloadSections() {
        super._reloadSections(...arguments);
        if (this.ak_domains) {
            this._domain = this.domain.concat(this.ak_domains);
        }
    },
});
