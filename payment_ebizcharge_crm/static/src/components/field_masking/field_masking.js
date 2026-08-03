/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FieldMaskingBase } from "./field_masking_base";

export class FieldMaskingEbizA extends FieldMaskingBase {
    static template = "payment_ebizcharge_crm.FieldMasking";
    static fieldName = "ebiz_security_key";
    static refName = "inputebizsecurity";
}

registry.category("fields").add("security_field_masking", {
    component: FieldMaskingEbizA,
});
