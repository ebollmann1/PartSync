/** @odoo-module **/
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { ControlPanel } from "@web/search/control_panel/control_panel";

export class FormControlPanelEbiz extends ControlPanel {
   setup() {
       this.controlPanelDisplay = {};
    }
}

FormControlPanelEbiz.template = "payment_ebizcharge_crm.FormControlPanelEbiz";

export const FormControlPanelEbizView = {
    ...formView,
    ControlPanel: FormControlPanelEbiz,
};

registry.category("views").add("ebiz_custom_form", FormControlPanelEbizView);
