/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FieldMaskingBase } from "../field_masking/field_masking_base";

export class FieldMaskingEbizSource extends FieldMaskingBase {
    static template = "payment_ebizcharge_crm.FieldMaskingSource";
    static fieldName = "source_key";
    static refName = "inputdate";
}

registry.category("fields").add("eb_device_field_masking", {
    component: FieldMaskingEbizSource,
});
