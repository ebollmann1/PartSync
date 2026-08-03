/** @odoo-module **/

import { registry } from '@web/core/registry';
import { listView } from '@web/views/list/list_view';
import { ListRenderer } from '@web/views/list/list_renderer';

export class HideTooltipRenderer extends ListRenderer {
    getCellTitle(column, record) {
        return false;
    }
}

registry.category('views').add('hide_tooltip', {
    ...listView,
    Renderer: HideTooltipRenderer,
});
