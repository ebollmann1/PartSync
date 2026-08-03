/** @odoo-module **/
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class IconCharField extends CharField {
    static template = "payment_ebizcharge_crm.IconCharField";
    static components = { ...CharField.components };
    static props = {
        ...CharField.props,
        iconConditionField: { type: String, optional: true },
        iconTooltipDisplay: { type: String, optional: true },
        iconTooltipField: { type: String, optional: true },
    };

    get shouldShowIcon() {
        const conditionField = this.props.iconConditionField;
        if (!conditionField) return false;
        return !!this.props.record.data[conditionField];
    }

    get hasContent() {
        return !!this.props.record.data[this.props.name];
    }

    get iconTooltip() {
        const tooltipField = this.props.iconTooltipField;
        if (tooltipField) {
            return this.props.record.data[tooltipField] || '';
        }
        return this.props.iconTooltipDisplay || '';
    }
}

export const iconCharField = {
    ...charField,
    component: IconCharField,
    additionalClasses: [...(charField.additionalClasses || []), "d-flex"],
    extractProps: ({ attrs, options, placeholder }) => ({
        ...charField.extractProps({ attrs, options, placeholder }),
        iconConditionField: options.icon_condition_field || '',
        iconTooltipDisplay: options.icon_tooltip_display || '',
        iconTooltipField: options.icon_tooltip_field || '',
    }),
};

registry.category("fields").add("char_icon", iconCharField);
