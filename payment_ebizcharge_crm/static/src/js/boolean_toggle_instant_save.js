/** @odoo-module **/

import { BooleanToggleField } from '@web/views/fields/boolean_toggle/boolean_toggle_field';
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";

patch(BooleanToggleField.prototype, {

    async onChange(newValue) {
        // Call base method to keep original behavior (optional)
        await super.onChange(...arguments);
        const active_ids = this.props.record.context.active_ids;
        const active_model = this.props.record.context.active_model;
        const resId = this.props.record.evalContext.id;
        if (active_ids && ['account.move', 'account.move.line', 'sale.order'].includes(active_model)) {
            await rpc("/web/dataset/call_kw/" + active_model +"/js_update_enable_sur", {
                model: active_model,
                method: 'js_update_enable_sur',
                args : [[parseInt(active_ids[0])]],
                kwargs: {'enable_sur': newValue, 'res_id': resId}
            });
        }
        // Immediately save record after updating
        await this.props.record.save();
    }

});