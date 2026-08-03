/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { onWillStart } from "@odoo/owl";

const APP_MODELS = [
    'payment.request.bulk.email',
    'batch.processing',
    'inv.payment.link.bulk',
    'sale.order.payment.link.bulk',
];

patch(FormController.prototype, {
    setup() {
        super.setup();
        onWillStart(async () => {
            if (APP_MODELS.includes(this.props.resModel) && this.props.resId) {
                await this._regenerateParentLines(this.props.resModel);
            }
        });
    },

    async _regenerateParentLines(resModel) {
        try {
            await this.orm.call(resModel, 'regenerate_line_ids', [this.props.resId, 'none']);
            await this.model.root.load();
            this.render(true);
        } catch (error) {
            console.error('Error regenerating lines:', error);
        }
    },
});
